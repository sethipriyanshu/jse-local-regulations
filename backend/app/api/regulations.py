"""Public read endpoints for the detail panel: the merged stack view, the changes
timeline, rule history, and exports (weeks 5 and 8)."""

import json
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.jurisdictions import JurisdictionOut
from app.api.sources import RuleOut, _rule_out
from app.db import get_session
from app.exports import build_export, filename, to_docx, to_pdf
from app.models import ChangeEvent, ChangeStatus, Jurisdiction, Rule, Source, not_false
from app.regulations import UnknownJurisdiction, collect, resolve_stack
from app.review import history

router = APIRouter(tags=["regulations"])
SessionDep = Annotated[Session, Depends(get_session)]
StackQuery = Annotated[str | None, Query(
    max_length=64, description="Comma-separated FIPS of an address's stack")]


class Override(BaseModel):
    jurisdiction_fips: str
    jurisdiction_name: str
    edition: str


class EffectiveCodeOut(BaseModel):
    code: str
    edition: str
    effective_on: date | None
    status: str
    rule_id: int
    jurisdiction_fips: str
    jurisdiction_name: str
    overrides: list[Override]


class RegulationsOut(BaseModel):
    stack: list[JurisdictionOut]
    rules: list[RuleOut]
    effective_codes: list[EffectiveCodeOut]


class ChangeOut(BaseModel):
    id: int
    source_id: int
    source_url: str
    source_title: str | None
    jurisdiction_fips: str
    jurisdiction_name: str
    mep_relevant: bool | None
    ai_summary: str | None
    proposed_actions: list[Any] | None
    status: ChangeStatus
    created_at: datetime
    reviewed_at: datetime | None
    diff_text: str | None = None  # admin lane only


def _split(stack: str | None) -> list[str] | None:
    return [s.strip() for s in stack.split(",") if s.strip()] if stack else None


def _resolve(
    session: Session, fips: str, stack: str | None
) -> tuple[Jurisdiction, list[Jurisdiction]]:
    try:
        return resolve_stack(session, fips, _split(stack))
    except UnknownJurisdiction as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No jurisdiction with FIPS {fips}") from exc


def change_out(
    session: Session, events: list[ChangeEvent], with_diff: bool = False
) -> list[ChangeOut]:
    if not events:
        return []
    srcs = {s.id: s for s in session.scalars(
        select(Source).where(Source.id.in_({e.source_id for e in events})))}
    jurs = {j.id: j for j in session.scalars(select(Jurisdiction).where(
        Jurisdiction.id.in_({s.jurisdiction_id for s in srcs.values()})))}
    out = []
    for e in events:
        src = srcs[e.source_id]
        j = jurs[src.jurisdiction_id]
        out.append(ChangeOut(
            id=e.id, source_id=src.id, source_url=src.url, source_title=src.title,
            jurisdiction_fips=j.fips, jurisdiction_name=j.name, mep_relevant=e.mep_relevant,
            ai_summary=e.ai_summary, proposed_actions=e.proposed_actions, status=e.status,
            created_at=e.created_at, reviewed_at=e.reviewed_at,
            diff_text=e.diff_text if with_diff else None,
        ))
    return out


@router.get("/jurisdictions/{fips}/regulations", response_model=RegulationsOut)
def regulations(
    fips: str, session: SessionDep, stack: StackQuery = None, include_pending: bool = True,
) -> RegulationsOut:
    """Everything that applies at this jurisdiction, across its stack, with the
    effective adopted-code table (inner layers override outer ones)."""
    j, layers = _resolve(session, fips, stack)
    regs = collect(session, j, layers, include_pending=include_pending)
    return RegulationsOut(
        stack=[JurisdictionOut.model_validate(s) for s in layers],
        rules=_rule_out(session, regs.rules),
        effective_codes=[EffectiveCodeOut(
            code=e.code, edition=e.edition, effective_on=e.effective_on, status=e.status.value,
            rule_id=e.rule.id, jurisdiction_fips=e.jurisdiction.fips,
            jurisdiction_name=e.jurisdiction.name,
            overrides=[Override(jurisdiction_fips=o.jurisdiction.fips,
                                jurisdiction_name=o.jurisdiction.name, edition=o.edition)
                       for o in e.overrides],
        ) for e in regs.effective_codes],
    )


@router.get("/jurisdictions/{fips}/changes", response_model=list[ChangeOut])
def changes(fips: str, session: SessionDep, stack: StackQuery = None) -> list[ChangeOut]:
    """Detected changes for the stack's sources, newest first (dismissed and
    irrelevant ones are hidden)."""
    _, layers = _resolve(session, fips, stack)
    events = session.scalars(
        select(ChangeEvent).join(Source, Source.id == ChangeEvent.source_id)
        .where(Source.jurisdiction_id.in_([s.id for s in layers]),
               ChangeEvent.status != ChangeStatus.DISMISSED,
               not_false(ChangeEvent.mep_relevant))
        .order_by(ChangeEvent.created_at.desc(), ChangeEvent.id.desc()).limit(50)
    ).all()
    return change_out(session, list(events))


@router.get("/rules/{rule_id}/history", response_model=list[RuleOut])
def rule_history(rule_id: int, session: SessionDep) -> list[RuleOut]:
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return _rule_out(session, history(session, rule))


MEDIA = {
    "json": "application/json",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@router.get("/jurisdictions/{fips}/export.{fmt}")
def export(
    fips: str, fmt: Literal["json", "docx", "pdf"], session: SessionDep,
    stack: StackQuery = None, include_pending: bool = True,
    disciplines: Annotated[str | None, Query(max_length=200)] = None,
    address: Annotated[str | None, Query(max_length=300)] = None,
) -> Response:
    j, layers = _resolve(session, fips, stack)
    regs = collect(session, j, layers, include_pending=include_pending)
    wanted = {d.strip() for d in disciplines.split(",") if d.strip()} if disciplines else None
    data = build_export(session, regs, disciplines=wanted, address=address)
    if fmt == "json":
        body = json.dumps(data, indent=2, ensure_ascii=False).encode()
    elif fmt == "docx":
        body = to_docx(data)
    else:
        body = to_pdf(data)
    return Response(body, media_type=MEDIA[fmt], headers={
        "Content-Disposition": f'attachment; filename="{filename(data, fmt)}"',
        "Cache-Control": "no-store",
    })
