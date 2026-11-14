"""Admin endpoints for weeks 5–7: the rules and changes lanes of the review queue,
AI discovery, jobs & health, the audit log, and Teams channels."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import discovery, teams
from app.api.admin_auth import require_admin
from app.api.regulations import ChangeOut, change_out
from app.api.sources import RejectIn, RuleOut, SourceOut, _rule_out, _source_out
from app.audit import record
from app.coverage import refresh_coverage
from app.db import get_session, get_session_factory
from app.models import (
    AiRun,
    AuditLog,
    ChangeEvent,
    ChangeStatus,
    JobRun,
    JobStatus,
    Jurisdiction,
    Rule,
    RuleStatus,
    Snapshot,
    Source,
    SourceHealth,
    SourceStatus,
    TeamsChannel,
)
from app.pipeline import extract_saved_snapshot, ingest_in_background
from app.review import ReviewError, reject_rule, verify_rule

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
SessionDep = Annotated[Session, Depends(get_session)]
FactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]


# --- rules lane --------------------------------------------------------------


class VerifyIn(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    summary: str | None = Field(default=None, max_length=8000)
    discipline: str | None = None
    category: str | None = None
    excerpt: str | None = Field(default=None, max_length=8000)
    code_ref: str | None = Field(default=None, max_length=255)
    code_edition: str | None = Field(default=None, max_length=32)
    effective_on: str | None = None  # YYYY-MM-DD or "" to clear
    supersedes_id: int | None = None


class VerifyOut(BaseModel):
    rule: RuleOut
    superseded: list[RuleOut]


class RuleQueueOut(BaseModel):
    rules: list[RuleOut]
    total: int


def _get_rule(session: Session, rule_id: int) -> Rule:
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return rule


@router.get("/rules", response_model=RuleQueueOut)
def rule_queue(
    session: SessionDep, fips: str | None = None, source_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> RuleQueueOut:
    """Pending rules, grouped by source so a reviewer can work through one document."""
    stmt = select(Rule).where(Rule.status == RuleStatus.PENDING)
    if fips:
        stmt = stmt.join(Jurisdiction, Jurisdiction.id == Rule.jurisdiction_id).where(
            Jurisdiction.fips == fips)
    if source_id is not None:
        stmt = stmt.where(Rule.source_id == source_id)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(Rule.jurisdiction_id, Rule.source_id, Rule.id)
                           .limit(limit)).all()
    return RuleQueueOut(rules=_rule_out(session, list(rows)), total=total)


@router.post("/rules/{rule_id}/verify", response_model=VerifyOut)
def verify(rule_id: int, body: VerifyIn, session: SessionDep) -> VerifyOut:
    """Verify, or edit and verify. Fields left out are unchanged."""
    rule = _get_rule(session, rule_id)
    edits: dict[str, Any] = body.model_dump(exclude_unset=True, exclude={"supersedes_id"})
    if "effective_on" in edits:
        try:
            raw = edits["effective_on"]
            edits["effective_on"] = datetime.strptime(raw, "%Y-%m-%d").date() if raw else None
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "effective_on must be YYYY-MM-DD") from exc
    try:
        superseded = verify_rule(session, rule, edits=edits or None,
                                 supersedes_id=body.supersedes_id)
    except ReviewError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()
    return VerifyOut(rule=_rule_out(session, [rule])[0],
                     superseded=_rule_out(session, superseded))


@router.post("/rules/{rule_id}/reject", response_model=RuleOut)
def reject(rule_id: int, body: RejectIn, session: SessionDep) -> RuleOut:
    rule = _get_rule(session, rule_id)
    reject_rule(session, rule, body.reason)
    session.commit()
    return _rule_out(session, [rule])[0]


class BulkOut(BaseModel):
    count: int


@router.post("/sources/{source_id}/verify-grounded", response_model=BulkOut)
def verify_grounded(source_id: int, session: SessionDep) -> BulkOut:
    """REV-4: verify every pending rule from this source whose quote was found
    verbatim in the snapshot. Ungrounded items stay for individual review."""
    rows = session.scalars(select(Rule).where(
        Rule.source_id == source_id, Rule.status == RuleStatus.PENDING,
        Rule.grounded.is_(True)).order_by(Rule.id)).all()
    for r in rows:
        verify_rule(session, r, actor="admin (bulk)")
    session.commit()
    return BulkOut(count=len(rows))


class BulkApproveIn(BaseModel):
    ids: list[int] = Field(max_length=100)


@router.post("/sources/approve-bulk", response_model=BulkOut)
def approve_bulk(
    body: BulkApproveIn, session: SessionDep, tasks: BackgroundTasks, factory: FactoryDep
) -> BulkOut:
    rows = session.scalars(select(Source).where(
        Source.id.in_(body.ids), Source.status == SourceStatus.SUBMITTED)).all()
    now = datetime.now(UTC)
    for s in rows:
        s.status, s.reviewed_at, s.reject_reason = SourceStatus.APPROVED, now, None
        record(session, "admin (bulk)", "source.approve", "source", s.id,
               {"status": "submitted"}, {"status": "approved"})
    session.commit()
    for s in rows:
        tasks.add_task(ingest_in_background, factory, s.id)
    return BulkOut(count=len(rows))


# --- changes lane ------------------------------------------------------------


@router.get("/changes", response_model=list[ChangeOut])
def change_queue(session: SessionDep, include_irrelevant: bool = False) -> list[ChangeOut]:
    stmt = select(ChangeEvent).where(ChangeEvent.status == ChangeStatus.NEW)
    if not include_irrelevant:
        stmt = stmt.where(ChangeEvent.mep_relevant.is_not(False))
    events = session.scalars(stmt.order_by(ChangeEvent.created_at.desc()).limit(100)).all()
    return change_out(session, list(events), with_diff=True)


def _get_change(session: Session, change_id: int) -> tuple[ChangeEvent, Source]:
    event = session.get(ChangeEvent, change_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change not found")
    src = session.get(Source, event.source_id)
    assert src is not None
    return event, src


def extract_change_in_background(factory: sessionmaker[Session], change_id: int) -> None:
    with factory() as session:
        event = session.get(ChangeEvent, change_id)
        if event is None:
            return
        src = session.get(Source, event.source_id)
        snap = session.get(Snapshot, event.new_snapshot_id)
        if src is not None and snap is not None:
            try:
                extract_saved_snapshot(session, src, snap)
            except Exception:
                session.rollback()
                log.exception("extraction for change %s failed", change_id)


@router.post("/changes/{change_id}/approve", response_model=ChangeOut)
def approve_change(
    change_id: int, session: SessionDep, tasks: BackgroundTasks, factory: FactoryDep
) -> ChangeOut:
    """Accept the change: the new snapshot is extracted, and its new or updated items
    arrive in the rules lane as pending (verifying them supersedes the old ones)."""
    event, src = _get_change(session, change_id)
    if event.status != ChangeStatus.NEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "This change was already reviewed")
    event.status, event.reviewed_at = ChangeStatus.APPROVED, datetime.now(UTC)
    record(session, "admin", "change.approve", "change", event.id)
    refresh_coverage(session, src.jurisdiction_id)
    session.commit()
    tasks.add_task(extract_change_in_background, factory, event.id)
    return change_out(session, [event], with_diff=True)[0]


@router.post("/changes/{change_id}/dismiss", response_model=ChangeOut)
def dismiss_change(change_id: int, session: SessionDep) -> ChangeOut:
    event, src = _get_change(session, change_id)
    event.status, event.reviewed_at = ChangeStatus.DISMISSED, datetime.now(UTC)
    record(session, "admin", "change.dismiss", "change", event.id)
    refresh_coverage(session, src.jurisdiction_id)
    session.commit()
    return change_out(session, [event], with_diff=True)[0]


# --- discovery ---------------------------------------------------------------


class JobOut(BaseModel):
    id: int
    job: str
    status: JobStatus
    started_at: datetime
    finished_at: datetime | None
    total: int | None
    done: int
    sources_checked: int
    changes_found: int
    errors: list[Any] | None
    summary: dict[str, Any] | None

    model_config = {"from_attributes": True}


class DiscoverIn(BaseModel):
    fips: list[str] | None = Field(default=None, max_length=200)  # default: all pilots


@router.post("/discovery", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def start_discovery(
    body: DiscoverIn, session: SessionDep, tasks: BackgroundTasks, factory: FactoryDep
) -> JobRun:
    """Find candidate sources with AI web search for the given jurisdictions (or every
    pilot jurisdiction). Runs in the background; poll GET /admin/jobs/{id}."""
    running = session.scalars(select(JobRun).where(
        JobRun.job == "discovery", JobRun.status == JobStatus.RUNNING)).first()
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A discovery run is already in progress")
    if body.fips:
        found = set(session.scalars(select(Jurisdiction.fips).where(
            Jurisdiction.fips.in_(body.fips))))
        fips = [f for f in body.fips if f in found]
        if not fips:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No matching jurisdictions")
    else:
        fips = [j.fips for j in discovery.pilot_targets(session)]
    run = discovery.start_job(session, fips)
    record(session, "admin", "discovery.start", "job", run.id, after={"count": len(fips)})
    session.commit()
    tasks.add_task(discovery.run_job_in_background, factory, run.id)
    return run


@router.get("/jobs", response_model=list[JobOut])
def jobs(session: SessionDep, job: str | None = None,
         limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[JobRun]:
    stmt = select(JobRun).order_by(JobRun.id.desc()).limit(limit)
    if job:
        stmt = stmt.where(JobRun.job == job)
    return list(session.scalars(stmt))


@router.get("/jobs/{job_id}", response_model=JobOut)
def job_detail(job_id: int, session: SessionDep) -> JobRun:
    run = session.get(JobRun, job_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return run


# --- jobs & health overview --------------------------------------------------


class CostOut(BaseModel):
    last_30d_usd: float
    by_kind: dict[str, float]
    calls_30d: int


class OverviewOut(BaseModel):
    counts: dict[str, int]
    last_daily: JobOut | None
    unhealthy_sources: list[SourceOut]
    cost: CostOut


@router.get("/overview", response_model=OverviewOut)
def overview(session: SessionDep) -> OverviewOut:
    def count(stmt: Any) -> int:
        return session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    since = datetime.now(UTC) - timedelta(days=30)
    by_kind = {kind: float(cost or 0) for kind, cost in session.execute(
        select(AiRun.kind, func.sum(AiRun.cost_usd))
        .where(AiRun.created_at >= since).group_by(AiRun.kind)).all()}
    calls = count(select(AiRun.id).where(AiRun.created_at >= since))
    unhealthy = session.scalars(select(Source).where(
        Source.status == SourceStatus.APPROVED,
        Source.health.in_([SourceHealth.NOT_FOUND, SourceHealth.BLOCKED, SourceHealth.ERROR]),
    ).order_by(Source.jurisdiction_id)).all()
    last_daily = session.scalars(select(JobRun).where(JobRun.job == "daily_monitor")
                                 .order_by(JobRun.id.desc())).first()
    return OverviewOut(
        counts={
            "sources": count(select(Source.id).where(Source.status == SourceStatus.SUBMITTED)),
            "rules": count(select(Rule.id).where(Rule.status == RuleStatus.PENDING)),
            "changes": count(select(ChangeEvent.id).where(
                ChangeEvent.status == ChangeStatus.NEW, ChangeEvent.mep_relevant.is_not(False))),
            "monitored": count(select(Source.id).where(Source.status == SourceStatus.APPROVED)),
            "verified_rules": count(select(Rule.id).where(Rule.status == RuleStatus.VERIFIED)),
        },
        last_daily=JobOut.model_validate(last_daily) if last_daily else None,
        unhealthy_sources=_source_out(session, list(unhealthy)),
        cost=CostOut(last_30d_usd=round(sum(by_kind.values()), 4),
                     by_kind={k: round(v, 4) for k, v in by_kind.items()}, calls_30d=calls),
    )


# --- audit log ---------------------------------------------------------------


class AuditOut(BaseModel):
    id: int
    actor: str
    action: str
    entity: str
    entity_id: int | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ts: datetime

    model_config = {"from_attributes": True}


@router.get("/audit", response_model=list[AuditOut])
def audit(
    session: SessionDep, entity: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    before_id: int | None = None,
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if before_id:
        stmt = stmt.where(AuditLog.id < before_id)
    return list(session.scalars(stmt))


# --- Teams channels ----------------------------------------------------------


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    webhook_url: str = Field(min_length=10, max_length=2048)
    metro: str | None = Field(default=None, max_length=64)
    sends_digest: bool = True
    sends_alerts: bool = True


class ChannelOut(BaseModel):
    id: int
    name: str
    webhook: str  # masked
    metro: str | None
    sends_digest: bool
    sends_alerts: bool
    created_at: datetime


def _channel_out(c: TeamsChannel) -> ChannelOut:
    return ChannelOut(id=c.id, name=c.name, webhook=teams.mask_webhook(c.webhook_url),
                      metro=c.metro, sends_digest=c.sends_digest, sends_alerts=c.sends_alerts,
                      created_at=c.created_at)


@router.get("/teams", response_model=list[ChannelOut])
def list_channels(session: SessionDep) -> list[ChannelOut]:
    rows = session.scalars(select(TeamsChannel).order_by(TeamsChannel.id))
    return [_channel_out(c) for c in rows]


@router.post("/teams", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
def add_channel(body: ChannelIn, session: SessionDep) -> ChannelOut:
    try:
        url = teams.validate_webhook_url(body.webhook_url)
    except teams.InvalidWebhook as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    c = TeamsChannel(name=body.name.strip(), webhook_url=url, metro=body.metro or None,
                     sends_digest=body.sends_digest, sends_alerts=body.sends_alerts)
    session.add(c)
    session.flush()
    record(session, "admin", "teams.add", "teams_channel", c.id,
           after={"name": c.name, "metro": c.metro})
    session.commit()
    return _channel_out(c)


@router.delete("/teams/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(channel_id: int, session: SessionDep) -> None:
    c = session.get(TeamsChannel, channel_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    record(session, "admin", "teams.delete", "teams_channel", c.id, before={"name": c.name})
    session.delete(c)
    session.commit()


@router.post("/teams/{channel_id}/test", response_model=BulkOut)
def test_channel(channel_id: int, session: SessionDep) -> BulkOut:
    c = session.get(TeamsChannel, channel_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    try:
        teams.post_card(c.webhook_url, teams.test_card(c.name))
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"Teams did not accept the message ({teams.describe_error(exc)})"
                            ) from exc
    return BulkOut(count=1)
