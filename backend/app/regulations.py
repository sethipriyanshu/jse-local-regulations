"""The merged view of everything that applies at one place: every layer of the
jurisdiction stack (state → county → city), plus the effective adopted-code table.
Shared by the detail panel API and the exports so they always agree."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jurisdictions import default_stack
from app.models import Jurisdiction, Rule, RuleStatus, Taxonomy, TaxonomyKind

MAX_STACK = 4


class UnknownJurisdiction(LookupError):
    pass


@dataclass
class Override:
    jurisdiction: Jurisdiction
    edition: str


@dataclass
class EffectiveCode:
    code: str
    edition: str
    effective_on: date | None
    status: RuleStatus
    rule: Rule
    jurisdiction: Jurisdiction
    # The same code adopted at an outer layer with a different edition (the inner one wins).
    overrides: list[Override] = field(default_factory=list)


@dataclass
class Regulations:
    jurisdiction: Jurisdiction
    stack: list[Jurisdiction]
    rules: list[Rule]  # outermost layer first; verified before pending within a layer
    effective_codes: list[EffectiveCode]
    include_pending: bool


def resolve_stack(
    session: Session, fips: str, stack_fips: list[str] | None = None
) -> tuple[Jurisdiction, list[Jurisdiction]]:
    """The selected jurisdiction and its stack. A caller that resolved an address passes
    the address's stack explicitly (it knows which county a multi-county city is in)."""
    j = session.scalars(select(Jurisdiction).where(Jurisdiction.fips == fips)).first()
    if j is None:
        raise UnknownJurisdiction(fips)
    if not stack_fips:
        return j, default_stack(session, j)
    wanted = list(dict.fromkeys(f for f in stack_fips if f))[:MAX_STACK]
    rows = {r.fips: r for r in session.scalars(
        select(Jurisdiction).where(Jurisdiction.fips.in_(wanted)))}
    if fips not in wanted:
        rows[fips] = j
    # FIPS length orders the layers: state (2) → county (5) → place (7).
    return j, sorted(rows.values(), key=lambda r: len(r.fips))


def collect(
    session: Session, j: Jurisdiction, stack: list[Jurisdiction], include_pending: bool = True
) -> Regulations:
    statuses = [RuleStatus.VERIFIED] + ([RuleStatus.PENDING] if include_pending else [])
    layer_rank = {s.id: i for i, s in enumerate(stack)}
    rules = list(session.scalars(
        select(Rule).where(Rule.jurisdiction_id.in_(layer_rank), Rule.status.in_(statuses))
    ))
    rules.sort(key=lambda r: (layer_rank[r.jurisdiction_id], r.status != RuleStatus.VERIFIED,
                              (r.title or "").lower()))
    adopted = session.scalars(select(Taxonomy.id).where(
        Taxonomy.kind == TaxonomyKind.CATEGORY, Taxonomy.key == "adopted_code")).first()
    by_id = {s.id: s for s in stack}
    return Regulations(
        jurisdiction=j, stack=stack, rules=rules, include_pending=include_pending,
        effective_codes=_effective_codes(
            [r for r in rules if r.category_id == adopted and r.code_ref], layer_rank, by_id),
    )


def _effective_codes(
    adoptions: list[Rule], layer_rank: dict[int, int], by_id: dict[int, Jurisdiction]
) -> list[EffectiveCode]:
    def preference(r: Rule) -> tuple[int, bool, int, int]:
        # Innermost layer, then verified, then the newest effective date, then newest row.
        return (-layer_rank[r.jurisdiction_id], r.status != RuleStatus.VERIFIED,
                -r.effective_on.toordinal() if r.effective_on else 0, -r.id)

    groups: dict[str, list[Rule]] = {}
    for r in adoptions:
        groups.setdefault((r.code_ref or "").upper(), []).append(r)

    out: list[EffectiveCode] = []
    for code, rules in groups.items():
        rules.sort(key=preference)
        best = rules[0]
        overrides: dict[int, Override] = {}
        for r in rules[1:]:
            if (layer_rank[r.jurisdiction_id] < layer_rank[best.jurisdiction_id]
                    and r.code_edition != best.code_edition
                    and r.jurisdiction_id not in overrides):
                overrides[r.jurisdiction_id] = Override(by_id[r.jurisdiction_id],
                                                        r.code_edition or "")
        out.append(EffectiveCode(
            code=best.code_ref or code, edition=best.code_edition or "",
            effective_on=best.effective_on, status=best.status, rule=best,
            jurisdiction=by_id[best.jurisdiction_id], overrides=list(overrides.values()),
        ))
    out.sort(key=lambda e: _CODE_ORDER.get(e.code, 99))
    return out


_CODE_ORDER = {c: i for i, c in enumerate([
    "IBC", "IRC", "IEBC", "IMC", "UMC", "IPC", "UPC", "IFGC", "NEC", "IECC", "ASHRAE 90.1",
    "IFC", "NFPA 13", "NFPA 72", "NFPA 101", "OTHER",
])}
