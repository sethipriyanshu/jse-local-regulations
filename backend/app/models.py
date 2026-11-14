"""Database schema. See PLAN.md §3.2 for the reasoning behind each table.

Portability notes (SQL Server in deployed envs, SQLite in unit tests):
- Strings are Unicode (NVARCHAR) so place names and page text survive.
- Enums are stored as short strings (validated in Python), not native enums.
- URLs can be longer than SQL Server's index key limit, so uniqueness is enforced
  on a SHA-256 of the normalized URL instead of the URL itself.
- Foreign keys use the default NO ACTION; SQL Server rejects multiple cascade
  paths, and we never hard-delete regulatory history anyway.
"""

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Unicode,
    UnicodeText,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        str: Unicode(255),
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


def _enum(cls: type[enum.Enum]) -> Enum:
    return Enum(
        cls,
        native_enum=False,
        values_callable=lambda e: [m.value for m in e],
        length=32,
        name=cls.__name__.lower(),
        validate_strings=True,
    )


def _now() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


# --- enums -------------------------------------------------------------------


class JurisdictionType(enum.StrEnum):
    STATE = "state"
    COUNTY = "county"
    CITY = "city"
    CONSOLIDATED = "consolidated"  # city-county, e.g. Denver
    DISTRICT = "district"  # Washington DC


class Coverage(enum.StrEnum):
    NONE = "none"
    PARTIAL = "partial"
    VERIFIED = "verified"
    CHANGES_PENDING = "changes_pending"


class TaxonomyKind(enum.StrEnum):
    DISCIPLINE = "discipline"
    CATEGORY = "category"


class SourceStatus(enum.StrEnum):
    SUBMITTED = "submitted"  # awaiting admin review
    APPROVED = "approved"  # monitored daily
    REJECTED = "rejected"  # remembered so it is not suggested again
    BROKEN = "broken"


class Origin(enum.StrEnum):
    USER = "user"
    ADMIN = "admin"
    AI = "ai"
    SEED = "seed"


class FetchMode(enum.StrEnum):
    STATIC = "static"
    BROWSER = "browser"
    PDF = "pdf"


class SourceHealth(enum.StrEnum):
    UNKNOWN = "unknown"
    OK = "ok"
    REDIRECTED = "redirected"
    NOT_FOUND = "not_found"
    BLOCKED = "blocked"
    ERROR = "error"


class RuleStatus(enum.StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ChangeStatus(enum.StrEnum):
    NEW = "new"
    APPROVED = "approved"
    DISMISSED = "dismissed"


class JobStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# --- tables ------------------------------------------------------------------


class Jurisdiction(Base):
    __tablename__ = "jurisdictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Census GEOID: 2 digits for a state, 5 for a county, 7 for a place.
    fips: Mapped[str] = mapped_column(Unicode(7), unique=True)
    name: Mapped[str]
    type: Mapped[JurisdictionType] = mapped_column(_enum(JurisdictionType))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("jurisdictions.id"))
    state_code: Mapped[str] = mapped_column(Unicode(2), index=True)
    coverage: Mapped[Coverage] = mapped_column(_enum(Coverage), default=Coverage.NONE)
    is_pilot: Mapped[bool] = mapped_column(Boolean, default=False)
    pilot_metro: Mapped[str | None] = mapped_column(Unicode(64))
    created_at: Mapped[datetime] = _now()

    parent: Mapped["Jurisdiction | None"] = relationship(remote_side=[id])


class PlaceCounty(Base):
    """Which counties a city lies in. Many-to-many: Atlanta spans Fulton and DeKalb,
    Dallas spans five counties. Seeded for pilots, then learned from geocoded addresses."""

    __tablename__ = "place_counties"

    place_id: Mapped[int] = mapped_column(ForeignKey("jurisdictions.id"), primary_key=True)
    county_id: Mapped[int] = mapped_column(
        ForeignKey("jurisdictions.id"), primary_key=True, index=True
    )


class Taxonomy(Base):
    """Disciplines and categories. Kept as data because the final scope will be
    defined by a JSE engineer before production (PLAN.md D3)."""

    __tablename__ = "taxonomy"
    __table_args__ = (UniqueConstraint("kind", "key", name="uq_taxonomy_kind_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[TaxonomyKind] = mapped_column(_enum(TaxonomyKind))
    key: Mapped[str] = mapped_column(Unicode(64))
    label: Mapped[str] = mapped_column(Unicode(128))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("jurisdiction_id", "url_hash", name="uq_sources_jurisdiction_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdictions.id"), index=True)
    url: Mapped[str] = mapped_column(Unicode(2048))
    url_hash: Mapped[str] = mapped_column(Unicode(64))
    title: Mapped[str | None] = mapped_column(Unicode(512))
    domain: Mapped[str]
    status: Mapped[SourceStatus] = mapped_column(_enum(SourceStatus), index=True)
    origin: Mapped[Origin] = mapped_column(_enum(Origin))
    submitted_by_name: Mapped[str | None] = mapped_column(Unicode(128))
    note: Mapped[str | None] = mapped_column(UnicodeText)
    reject_reason: Mapped[str | None] = mapped_column(UnicodeText)
    # Discovery metadata (AI search): why it was suggested, 0-1 relevance.
    discovery_reason: Mapped[str | None] = mapped_column(UnicodeText)
    discovery_score: Mapped[float | None] = mapped_column(Float)
    fetch_mode: Mapped[FetchMode] = mapped_column(_enum(FetchMode), default=FetchMode.STATIC)
    scope_selector: Mapped[str | None] = mapped_column(Unicode(512))
    health: Mapped[SourceHealth] = mapped_column(_enum(SourceHealth), default=SourceHealth.UNKNOWN)
    last_fetched_at: Mapped[datetime | None]
    last_hash: Mapped[str | None] = mapped_column(Unicode(64))
    created_at: Mapped[datetime] = _now()
    reviewed_at: Mapped[datetime | None]

    jurisdiction: Mapped[Jurisdiction] = relationship()


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    fetched_at: Mapped[datetime] = _now()
    http_status: Mapped[int | None]
    final_url: Mapped[str | None] = mapped_column(Unicode(2048))
    content_hash: Mapped[str] = mapped_column(Unicode(64))
    blob_raw: Mapped[str] = mapped_column(Unicode(512))
    blob_text: Mapped[str] = mapped_column(Unicode(512))
    char_count: Mapped[int]


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdictions.id"), index=True)
    discipline_id: Mapped[int | None] = mapped_column(ForeignKey("taxonomy.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("taxonomy.id"))
    title: Mapped[str] = mapped_column(Unicode(512))
    summary: Mapped[str] = mapped_column(UnicodeText)
    excerpt: Mapped[str | None] = mapped_column(UnicodeText)  # verbatim from the source
    code_ref: Mapped[str | None] = mapped_column(Unicode(255))  # e.g. "NEC 2020 §210.8"
    code_edition: Mapped[str | None] = mapped_column(Unicode(32))
    adopted_on: Mapped[date | None] = mapped_column(Date)
    effective_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[RuleStatus] = mapped_column(
        _enum(RuleStatus), default=RuleStatus.PENDING, index=True
    )
    origin: Mapped[Origin] = mapped_column(_enum(Origin))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id"))
    confidence: Mapped[float | None] = mapped_column(Float)
    grounded: Mapped[bool | None] = mapped_column(Boolean)  # excerpt found verbatim
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id"))
    submitted_by_name: Mapped[str | None] = mapped_column(Unicode(128))
    review_note: Mapped[str | None] = mapped_column(UnicodeText)  # e.g. the reject reason
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    verified_at: Mapped[datetime | None]


class CodeAdoption(Base):
    """One row per (jurisdiction, model code): the headline table on the Overview tab."""

    __tablename__ = "code_adoptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdictions.id"), index=True)
    code: Mapped[str] = mapped_column(Unicode(32))  # IBC | IMC | IPC | NEC | IECC | ...
    edition: Mapped[str] = mapped_column(Unicode(32))
    amendments_summary: Mapped[str | None] = mapped_column(UnicodeText)
    effective_on: Mapped[date | None] = mapped_column(Date)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id"))
    status: Mapped[RuleStatus] = mapped_column(_enum(RuleStatus), default=RuleStatus.PENDING)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    prev_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id"))
    new_snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    diff_text: Mapped[str] = mapped_column(UnicodeText)
    mep_relevant: Mapped[bool | None] = mapped_column(Boolean)
    ai_summary: Mapped[str | None] = mapped_column(UnicodeText)
    proposed_actions: Mapped[list[Any] | None]
    status: Mapped[ChangeStatus] = mapped_column(
        _enum(ChangeStatus), default=ChangeStatus.NEW, index=True
    )
    created_at: Mapped[datetime] = _now()
    reviewed_at: Mapped[datetime | None]


class AiRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(Unicode(32))  # extract | triage | summarize | discover
    provider: Mapped[str] = mapped_column(Unicode(64))
    model: Mapped[str] = mapped_column(Unicode(128))
    prompt_version: Mapped[str] = mapped_column(Unicode(32))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4, asdecimal=False))
    latency_ms: Mapped[int | None]
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    ref_type: Mapped[str | None] = mapped_column(Unicode(32))
    ref_id: Mapped[int | None]
    created_at: Mapped[datetime] = _now()


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(Unicode(64))
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.RUNNING)
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None]
    sources_checked: Mapped[int] = mapped_column(Integer, default=0)
    changes_found: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[Any] | None]
    # Progress for long jobs (bulk discovery): items planned / done, plus a free-form summary.
    total: Mapped[int | None]
    done: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict[str, Any] | None]


class TeamsChannel(Base):
    __tablename__ = "teams_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(128))
    # Teams Workflows "post to a channel when a webhook request is received" URL.
    # Admin-only; never returned in full by the API.
    webhook_url: Mapped[str] = mapped_column(Unicode(2048))
    metro: Mapped[str | None] = mapped_column(Unicode(64))  # null = all metros
    sends_digest: Mapped[bool] = mapped_column(Boolean, default=True)
    sends_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now()


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(Unicode(128))  # "admin" or the free-text name
    action: Mapped[str] = mapped_column(Unicode(64))
    entity: Mapped[str] = mapped_column(Unicode(64))
    entity_id: Mapped[int | None]
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    ts: Mapped[datetime] = _now()
