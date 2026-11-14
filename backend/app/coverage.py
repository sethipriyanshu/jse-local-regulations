"""Coverage status that drives the map shading (PLAN.md A2). Recomputed whenever a
rule is reviewed or a detected change is created or reviewed."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ChangeEvent,
    ChangeStatus,
    Coverage,
    Jurisdiction,
    Rule,
    RuleStatus,
    Source,
    not_false,
)


def compute_coverage(session: Session, jurisdiction_id: int) -> Coverage:
    open_changes = session.scalar(
        select(func.count()).select_from(ChangeEvent)
        .join(Source, Source.id == ChangeEvent.source_id)
        .where(Source.jurisdiction_id == jurisdiction_id, ChangeEvent.status == ChangeStatus.NEW,
               not_false(ChangeEvent.mep_relevant))
    ) or 0
    counts = dict(session.execute(
        select(Rule.status, func.count()).where(
            Rule.jurisdiction_id == jurisdiction_id,
            Rule.status.in_([RuleStatus.PENDING, RuleStatus.VERIFIED]),
        ).group_by(Rule.status)
    ).all())
    verified, pending = counts.get(RuleStatus.VERIFIED, 0), counts.get(RuleStatus.PENDING, 0)
    if open_changes and (verified or pending):
        return Coverage.CHANGES_PENDING
    if verified and not pending:
        return Coverage.VERIFIED
    if verified or pending:
        return Coverage.PARTIAL
    return Coverage.NONE


def refresh_coverage(session: Session, *jurisdiction_ids: int) -> None:
    """Update the stored coverage; the caller commits."""
    for jid in set(jurisdiction_ids):
        j = session.get(Jurisdiction, jid)
        if j is not None:
            j.coverage = compute_coverage(session, jid)
