"""Admin review of extracted and submitted rules (PLAN.md REV-2, REV-3)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.coverage import refresh_coverage
from app.models import CodeAdoption, Rule, RuleStatus, Taxonomy, TaxonomyKind


class ReviewError(ValueError):
    pass


EDITABLE = ("title", "summary", "excerpt", "code_ref", "code_edition", "effective_on")


def _state(r: Rule) -> dict[str, Any]:
    return {
        "status": r.status.value, "title": r.title, "summary": r.summary,
        "code_ref": r.code_ref, "code_edition": r.code_edition,
        "effective_on": r.effective_on.isoformat() if r.effective_on else None,
        "discipline_id": r.discipline_id, "category_id": r.category_id,
        "supersedes_id": r.supersedes_id, "review_note": r.review_note,
    }


def _adopted_category(session: Session) -> int | None:
    return session.scalars(select(Taxonomy.id).where(
        Taxonomy.kind == TaxonomyKind.CATEGORY, Taxonomy.key == "adopted_code")).first()


def apply_edits(session: Session, rule: Rule, edits: dict[str, Any]) -> None:
    tax = {(t.kind, t.key): t.id for t in session.scalars(select(Taxonomy))}
    for key in EDITABLE:
        if key in edits:
            value = edits[key]
            if isinstance(value, str):
                value = value.strip() or None
            if key in ("title", "summary") and not value:
                raise ReviewError(f"{key} cannot be empty")
            setattr(rule, key, value)
    if edits.get("discipline"):
        rule.discipline_id = tax.get((TaxonomyKind.DISCIPLINE, edits["discipline"]))
        if rule.discipline_id is None:
            raise ReviewError("Unknown discipline")
    if edits.get("category"):
        rule.category_id = tax.get((TaxonomyKind.CATEGORY, edits["category"]))
        if rule.category_id is None:
            raise ReviewError("Unknown category")


def _sync_adoption(session: Session, rule: Rule, adopted_cat: int | None) -> None:
    """Keep the code_adoptions row (headline table) in step with its rule."""
    row = session.scalars(select(CodeAdoption).where(CodeAdoption.rule_id == rule.id)).first()
    is_adoption = rule.category_id == adopted_cat and bool(rule.code_ref and rule.code_edition)
    if row is None and is_adoption:
        row = CodeAdoption(jurisdiction_id=rule.jurisdiction_id, rule_id=rule.id,
                           code=(rule.code_ref or "")[:32], edition=(rule.code_edition or "")[:32])
        session.add(row)
    if row is None:
        return
    if not is_adoption:
        row.status = RuleStatus.REJECTED
        return
    row.code = (rule.code_ref or "")[:32]
    row.edition = (rule.code_edition or "")[:32]
    row.effective_on = rule.effective_on
    row.amendments_summary = rule.summary
    row.status = rule.status


def verify_rule(
    session: Session, rule: Rule, *, edits: dict[str, Any] | None = None,
    supersedes_id: int | None = None, actor: str = "admin",
) -> list[Rule]:
    """Verify a rule (optionally editing it first). A verified adoption of a code
    replaces the previously verified adoption of the same code in the same
    jurisdiction; other rules supersede only when `supersedes_id` says so.
    Returns the rules that were superseded. The caller commits."""
    if rule.status not in (RuleStatus.PENDING, RuleStatus.REJECTED, RuleStatus.VERIFIED):
        raise ReviewError(f"A {rule.status.value} rule cannot be verified")
    before = _state(rule)
    if edits:
        apply_edits(session, rule, edits)
    adopted_cat = _adopted_category(session)

    targets: list[Rule] = []
    if supersedes_id is not None:
        old = session.get(Rule, supersedes_id)
        if old is None or old.jurisdiction_id != rule.jurisdiction_id or old.id == rule.id:
            raise ReviewError("The superseded rule must be another rule of this jurisdiction")
        targets = [old]
    elif rule.category_id == adopted_cat and rule.code_ref:
        targets = list(session.scalars(select(Rule).where(
            Rule.jurisdiction_id == rule.jurisdiction_id, Rule.id != rule.id,
            Rule.category_id == adopted_cat, Rule.status == RuleStatus.VERIFIED,
            func.upper(Rule.code_ref) == rule.code_ref.upper(),
        )))

    now = datetime.now(UTC)
    for old in targets:
        old_before = _state(old)
        old.status = RuleStatus.SUPERSEDED
        _sync_adoption(session, old, adopted_cat)
        record(session, actor, "rule.supersede", "rule", old.id, old_before,
               {**_state(old), "superseded_by": rule.id})
    if targets:
        newest = max(targets, key=lambda r: (r.verified_at or r.created_at, r.id))
        rule.supersedes_id = newest.id

    rule.status = RuleStatus.VERIFIED
    rule.verified_at = now
    rule.review_note = None
    _sync_adoption(session, rule, adopted_cat)
    record(session, actor, "rule.verify" if not edits else "rule.edit_verify", "rule", rule.id,
           before, _state(rule))
    refresh_coverage(session, rule.jurisdiction_id)
    return targets


def reject_rule(session: Session, rule: Rule, reason: str, actor: str = "admin") -> None:
    before = _state(rule)
    rule.status = RuleStatus.REJECTED
    rule.review_note = reason.strip() or None
    _sync_adoption(session, rule, _adopted_category(session))
    record(session, actor, "rule.reject", "rule", rule.id, before, _state(rule))
    refresh_coverage(session, rule.jurisdiction_id)


def history(session: Session, rule: Rule, limit: int = 20) -> list[Rule]:
    """The chain of rules this one replaced, newest first."""
    chain: list[Rule] = []
    seen = {rule.id}
    current = rule
    while current.supersedes_id and len(chain) < limit:
        prev = session.get(Rule, current.supersedes_id)
        if prev is None or prev.id in seen:
            break
        chain.append(prev)
        seen.add(prev.id)
        current = prev
    return chain
