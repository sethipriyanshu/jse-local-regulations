"""Sources, uploads, rules, and the admin review queue for sources (weeks 3–4)."""

import hashlib
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session, sessionmaker

from app.api.admin_auth import is_admin, require_admin
from app.audit import actor_for, record
from app.coverage import refresh_coverage
from app.db import get_session, get_session_factory
from app.models import (
    ChangeEvent,
    ChangeStatus,
    Jurisdiction,
    Origin,
    Rule,
    RuleStatus,
    Source,
    SourceHealth,
    SourceStatus,
    Taxonomy,
    TaxonomyKind,
    not_false,
)
from app.pipeline import UPLOAD_SCHEME, ingest_in_background, upload_blob_name
from app.storage import get_store
from app.teams import notify_submission
from app.urls import (
    UnsafeUrl,
    assert_public,
    domain_of,
    is_official_domain,
    normalize_url,
    url_hash,
)

router = APIRouter(tags=["sources"])
SessionDep = Annotated[Session, Depends(get_session)]
FactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]
AdminDep = Annotated[bool, Depends(is_admin)]
MAX_UPLOAD_BYTES = 25_000_000


# --- schemas -----------------------------------------------------------------


class SourceOut(BaseModel):
    id: int
    jurisdiction_fips: str
    jurisdiction_name: str
    url: str
    title: str | None
    domain: str
    status: SourceStatus
    origin: Origin
    health: SourceHealth
    official: bool
    is_upload: bool
    submitted_by_name: str | None
    note: str | None
    reject_reason: str | None
    discovery_reason: str | None
    last_fetched_at: datetime | None
    created_at: datetime
    rule_count: int


class SourceIn(BaseModel):
    url: str = Field(min_length=4, max_length=2048)
    note: str | None = Field(default=None, max_length=2000)
    submitted_by_name: str | None = Field(default=None, max_length=128)


class TaxonomyItem(BaseModel):
    key: str
    label: str


class TaxonomyOut(BaseModel):
    disciplines: list[TaxonomyItem]
    categories: list[TaxonomyItem]


class RuleOut(BaseModel):
    id: int
    jurisdiction_fips: str
    jurisdiction_name: str
    title: str
    summary: str
    excerpt: str | None
    discipline: str | None
    category: str | None
    code_ref: str | None
    code_edition: str | None
    effective_on: date | None
    status: RuleStatus
    origin: Origin
    confidence: float | None
    grounded: bool | None
    source_id: int | None
    source_url: str | None
    source_title: str | None
    submitted_by_name: str | None
    review_note: str | None
    supersedes_id: int | None
    snapshot_id: int | None
    created_at: datetime
    verified_at: datetime | None


class RuleIn(BaseModel):
    title: str = Field(min_length=3, max_length=512)
    summary: str = Field(min_length=3, max_length=8000)
    discipline: str
    category: str
    excerpt: str | None = Field(default=None, max_length=8000)
    code_ref: str | None = Field(default=None, max_length=255)
    code_edition: str | None = Field(default=None, max_length=32)
    effective_on: date | None = None
    source_url: str | None = Field(default=None, max_length=2048)
    submitted_by_name: str | None = Field(default=None, max_length=128)


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=2000)


class QueueOut(BaseModel):
    sources: list[SourceOut]
    counts: dict[str, int]


# --- helpers -----------------------------------------------------------------


def _jurisdiction(session: Session, fips: str) -> Jurisdiction:
    j = session.scalars(select(Jurisdiction).where(Jurisdiction.fips == fips)).first()
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No jurisdiction with FIPS {fips}")
    return j


def _source_out(session: Session, sources: list[Source]) -> list[SourceOut]:
    if not sources:
        return []
    ids = [s.id for s in sources]
    counts = dict(session.execute(
        select(Rule.source_id, func.count()).where(Rule.source_id.in_(ids))
        .where(Rule.status.in_([RuleStatus.PENDING, RuleStatus.VERIFIED]))
        .group_by(Rule.source_id)
    ).all())
    jurs = {j.id: j for j in session.scalars(
        select(Jurisdiction).where(Jurisdiction.id.in_({s.jurisdiction_id for s in sources})))}
    return [
        SourceOut(
            id=s.id, jurisdiction_fips=jurs[s.jurisdiction_id].fips,
            jurisdiction_name=jurs[s.jurisdiction_id].name, url=s.url, title=s.title,
            domain=s.domain, status=s.status, origin=s.origin, health=s.health,
            official=is_official_domain(s.domain), is_upload=s.url.startswith(UPLOAD_SCHEME),
            submitted_by_name=s.submitted_by_name, note=s.note, reject_reason=s.reject_reason,
            discovery_reason=s.discovery_reason, last_fetched_at=s.last_fetched_at,
            created_at=s.created_at, rule_count=counts.get(s.id, 0),
        )
        for s in sources
    ]


def _rule_out(session: Session, rules: list[Rule]) -> list[RuleOut]:
    if not rules:
        return []
    tax = {t.id: t.key for t in session.scalars(select(Taxonomy))}
    src_ids = {r.source_id for r in rules if r.source_id}
    srcs = {s.id: s for s in session.scalars(select(Source).where(Source.id.in_(src_ids)))}
    jurs = {j.id: j for j in session.scalars(
        select(Jurisdiction).where(Jurisdiction.id.in_({r.jurisdiction_id for r in rules})))}
    out = []
    for r in rules:
        src = srcs.get(r.source_id) if r.source_id else None
        out.append(RuleOut(
            id=r.id, jurisdiction_fips=jurs[r.jurisdiction_id].fips,
            jurisdiction_name=jurs[r.jurisdiction_id].name, title=r.title, summary=r.summary,
            excerpt=r.excerpt, discipline=tax.get(r.discipline_id) if r.discipline_id else None,
            category=tax.get(r.category_id) if r.category_id else None, code_ref=r.code_ref,
            code_edition=r.code_edition, effective_on=r.effective_on, status=r.status,
            origin=r.origin, confidence=r.confidence, grounded=r.grounded,
            source_id=r.source_id, source_url=src.url if src else None,
            source_title=src.title if src else None, submitted_by_name=r.submitted_by_name,
            review_note=r.review_note, supersedes_id=r.supersedes_id, snapshot_id=r.snapshot_id,
            created_at=r.created_at, verified_at=r.verified_at,
        ))
    return out


def _snapshot(s: Source) -> dict[str, str | None]:
    return {"status": s.status.value, "reject_reason": s.reject_reason}


# --- public endpoints --------------------------------------------------------


@router.get("/taxonomy", response_model=TaxonomyOut)
def taxonomy(session: SessionDep) -> TaxonomyOut:
    rows = session.scalars(
        select(Taxonomy).where(Taxonomy.active == true()).order_by(Taxonomy.sort_order)
    ).all()
    item = lambda t: TaxonomyItem(key=t.key, label=t.label)  # noqa: E731
    return TaxonomyOut(
        disciplines=[item(t) for t in rows if t.kind == TaxonomyKind.DISCIPLINE],
        categories=[item(t) for t in rows if t.kind == TaxonomyKind.CATEGORY],
    )


@router.get("/jurisdictions/{fips}/sources", response_model=list[SourceOut])
def list_sources(fips: str, session: SessionDep, admin: AdminDep) -> list[SourceOut]:
    j = _jurisdiction(session, fips)
    stmt = select(Source).where(Source.jurisdiction_id == j.id).order_by(Source.created_at.desc())
    if not admin:
        stmt = stmt.where(Source.status != SourceStatus.REJECTED)
    return _source_out(session, list(session.scalars(stmt)))


@router.post("/jurisdictions/{fips}/sources", response_model=SourceOut,
             status_code=status.HTTP_201_CREATED)
def submit_source(
    fips: str, body: SourceIn, session: SessionDep, admin: AdminDep, tasks: BackgroundTasks,
    factory: FactoryDep,
) -> SourceOut:
    """Users suggest a URL (goes to the admin queue); admins add it approved and it is
    fetched and extracted right away."""
    j = _jurisdiction(session, fips)
    try:
        url = normalize_url(body.url)
        assert_public(url)
    except UnsafeUrl as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    existing = session.scalars(
        select(Source).where(Source.jurisdiction_id == j.id, Source.url_hash == url_hash(url))
    ).first()
    if existing is not None:
        msg = {
            SourceStatus.REJECTED: "This URL was already reviewed and rejected for this place.",
            SourceStatus.SUBMITTED: "This URL is already waiting for review.",
        }.get(existing.status, "This URL is already a source for this place.")
        raise HTTPException(status.HTTP_409_CONFLICT, msg)

    src = Source(
        jurisdiction_id=j.id, url=url, url_hash=url_hash(url), domain=domain_of(url),
        status=SourceStatus.APPROVED if admin else SourceStatus.SUBMITTED,
        origin=Origin.ADMIN if admin else Origin.USER,
        submitted_by_name=(body.submitted_by_name or "").strip() or None,
        note=(body.note or "").strip() or None,
        reviewed_at=datetime.now(UTC) if admin else None,
    )
    session.add(src)
    session.flush()
    record(session, actor_for(admin, body.submitted_by_name), "source.submit", "source", src.id,
           after={"url": url, "status": src.status.value})
    session.commit()
    if admin:
        tasks.add_task(ingest_in_background, factory, src.id)
    else:
        tasks.add_task(notify_submission, factory, src.id)
    return _source_out(session, [src])[0]


@router.post("/jurisdictions/{fips}/uploads", response_model=SourceOut,
             status_code=status.HTTP_201_CREATED)
async def upload_document(
    fips: str, session: SessionDep, admin: AdminDep, tasks: BackgroundTasks, factory: FactoryDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=512)] = None,
    submitted_by_name: Annotated[str | None, Form(max_length=128)] = None,
) -> SourceOut:
    """PDF upload, e.g. an ordinance saved from a code library we can't fetch directly."""
    j = _jurisdiction(session, fips)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "PDF is larger than 25 MB")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only PDF files are accepted")

    sha = hashlib.sha256(data).hexdigest()
    url = f"{UPLOAD_SCHEME}{sha}/{(file.filename or 'document.pdf')[:200]}"
    if session.scalars(select(Source).where(
        Source.jurisdiction_id == j.id, Source.url_hash == sha)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "This file was already uploaded here.")
    get_store().put(upload_blob_name(sha), data, "application/pdf")

    src = Source(
        jurisdiction_id=j.id, url=url, url_hash=sha, domain="upload",
        title=(title or "").strip() or file.filename,
        status=SourceStatus.APPROVED if admin else SourceStatus.SUBMITTED,
        origin=Origin.ADMIN if admin else Origin.USER,
        submitted_by_name=(submitted_by_name or "").strip() or None,
        reviewed_at=datetime.now(UTC) if admin else None,
    )
    session.add(src)
    session.flush()
    record(session, actor_for(admin, submitted_by_name), "source.upload", "source", src.id,
           after={"file": file.filename, "status": src.status.value})
    session.commit()
    if admin:
        tasks.add_task(ingest_in_background, factory, src.id)
    else:
        tasks.add_task(notify_submission, factory, src.id)
    return _source_out(session, [src])[0]


@router.get("/jurisdictions/{fips}/rules", response_model=list[RuleOut])
def list_rules(fips: str, session: SessionDep, admin: AdminDep) -> list[RuleOut]:
    j = _jurisdiction(session, fips)
    visible = [RuleStatus.PENDING, RuleStatus.VERIFIED]
    if admin:
        visible.append(RuleStatus.REJECTED)
    rules = session.scalars(
        select(Rule).where(Rule.jurisdiction_id == j.id, Rule.status.in_(visible))
        .order_by(Rule.status.desc(), Rule.created_at.desc())
    ).all()
    return _rule_out(session, list(rules))


@router.post("/jurisdictions/{fips}/rules", response_model=RuleOut,
             status_code=status.HTTP_201_CREATED)
def add_rule(fips: str, body: RuleIn, session: SessionDep, admin: AdminDep) -> RuleOut:
    """Manual entry. Always pending; even admin entries are reviewed in the queue."""
    j = _jurisdiction(session, fips)
    tax = {(t.kind, t.key): t.id for t in session.scalars(select(Taxonomy))}
    discipline_id = tax.get((TaxonomyKind.DISCIPLINE, body.discipline))
    category_id = tax.get((TaxonomyKind.CATEGORY, body.category))
    if discipline_id is None or category_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown discipline or category")

    source_id = None
    if body.source_url:
        try:
            url = normalize_url(body.source_url)
        except UnsafeUrl as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        src = session.scalars(select(Source).where(
            Source.jurisdiction_id == j.id, Source.url_hash == url_hash(url))).first()
        if src is None:
            # Record the citation as a submitted source so an admin can approve monitoring it.
            src = Source(jurisdiction_id=j.id, url=url, url_hash=url_hash(url),
                         domain=domain_of(url), status=SourceStatus.SUBMITTED,
                         origin=Origin.ADMIN if admin else Origin.USER,
                         submitted_by_name=body.submitted_by_name, note="Cited by a manual entry")
            session.add(src)
            session.flush()
        source_id = src.id

    rule = Rule(
        jurisdiction_id=j.id, discipline_id=discipline_id, category_id=category_id,
        title=body.title.strip(), summary=body.summary.strip(),
        excerpt=(body.excerpt or "").strip() or None, code_ref=body.code_ref,
        code_edition=body.code_edition, effective_on=body.effective_on,
        status=RuleStatus.PENDING, origin=Origin.ADMIN if admin else Origin.USER,
        source_id=source_id, submitted_by_name=(body.submitted_by_name or "").strip() or None,
    )
    session.add(rule)
    session.flush()
    record(session, actor_for(admin, body.submitted_by_name), "rule.submit", "rule", rule.id,
           after={"title": rule.title})
    refresh_coverage(session, j.id)
    session.commit()
    return _rule_out(session, [rule])[0]


# --- admin: source review ----------------------------------------------------

admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@admin_router.get("/queue", response_model=QueueOut)
def queue(session: SessionDep) -> QueueOut:
    sources = session.scalars(
        select(Source).where(Source.status == SourceStatus.SUBMITTED).order_by(Source.created_at)
    ).all()
    pending_rules = session.scalar(
        select(func.count()).select_from(Rule).where(Rule.status == RuleStatus.PENDING)) or 0
    new_changes = session.scalar(
        select(func.count()).select_from(ChangeEvent).where(
            ChangeEvent.status == ChangeStatus.NEW, not_false(ChangeEvent.mep_relevant))) or 0
    # AI suggestions first by score, then user submissions oldest first.
    ordered = sorted(sources, key=lambda s: (s.origin != Origin.AI, -(s.discovery_score or 0)))
    return QueueOut(
        sources=_source_out(session, ordered),
        counts={"sources": len(sources), "rules": pending_rules, "changes": new_changes},
    )


def _get_source(session: Session, source_id: int) -> Source:
    src = session.get(Source, source_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return src


@admin_router.post("/sources/{source_id}/approve", response_model=SourceOut)
def approve_source(
    source_id: int, session: SessionDep, tasks: BackgroundTasks, factory: FactoryDep
) -> SourceOut:
    src = _get_source(session, source_id)
    before = _snapshot(src)
    src.status = SourceStatus.APPROVED
    src.reject_reason = None
    src.reviewed_at = datetime.now(UTC)
    record(session, "admin", "source.approve", "source", src.id, before, _snapshot(src))
    session.commit()
    tasks.add_task(ingest_in_background, factory, src.id)
    return _source_out(session, [src])[0]


@admin_router.post("/sources/{source_id}/reject", response_model=SourceOut)
def reject_source(source_id: int, body: RejectIn, session: SessionDep) -> SourceOut:
    src = _get_source(session, source_id)
    before = _snapshot(src)
    src.status = SourceStatus.REJECTED
    src.reject_reason = body.reason.strip() or None
    src.reviewed_at = datetime.now(UTC)
    record(session, "admin", "source.reject", "source", src.id, before, _snapshot(src))
    session.commit()
    return _source_out(session, [src])[0]


@admin_router.post("/sources/{source_id}/refresh", response_model=SourceOut)
def refresh_source(
    source_id: int, session: SessionDep, tasks: BackgroundTasks, factory: FactoryDep,
    reextract: bool = False,
) -> SourceOut:
    """"Check now": fetch again; with reextract=true, re-run AI on the latest snapshot."""
    src = _get_source(session, source_id)
    if src.status != SourceStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only approved sources are fetched")
    record(session, "admin", "source.refresh", "source", src.id)
    session.commit()
    tasks.add_task(ingest_in_background, factory, src.id, reextract)
    return _source_out(session, [src])[0]
