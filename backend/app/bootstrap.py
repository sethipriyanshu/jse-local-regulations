"""Prepare a database: create it if missing (SQL Server), migrate to head, seed reference data.

Safe to run repeatedly. Used by docker-compose, the deploy pipeline, and local dev:
    uv run python -m app.bootstrap
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import Taxonomy, TaxonomyKind

log = logging.getLogger("bootstrap")
BACKEND_DIR = Path(__file__).resolve().parents[1]

# Provisional taxonomy (PLAN.md §1.5). Admins can edit it later; this only inserts missing keys.
DISCIPLINES = [
    ("mechanical", "Mechanical"),
    ("electrical", "Electrical"),
    ("plumbing", "Plumbing"),
    ("fire_protection", "Fire Protection"),
    ("fuel_gas", "Fuel Gas"),
    ("energy", "Energy"),
    ("general", "General / Admin"),
]
CATEGORIES = [
    ("adopted_code", "Adopted code & edition"),
    ("local_amendment", "Local amendment"),
    ("permit_submittal", "Permit & submittal requirement"),
    ("plan_review", "Plan review requirement"),
    ("inspection", "Inspection requirement"),
    ("licensing", "Licensing & seal requirement"),
    ("utility", "Utility requirement"),
    ("environmental", "Environmental"),
    ("fees", "Fees"),
    ("pending_change", "Pending / proposed change"),
]


def ensure_database() -> None:
    url = make_url(get_settings().database_url)
    if not url.drivername.startswith("mssql") or not url.database:
        return
    master = create_engine(url.set(database="master"), isolation_level="AUTOCOMMIT")
    with master.connect() as conn:
        exists = conn.execute(text("SELECT DB_ID(:n)"), {"n": url.database}).scalar()
        if exists is None:
            log.info("creating database %s", url.database)
            conn.execute(text(f"CREATE DATABASE [{url.database}]"))
    master.dispose()


def migrate() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["skip_logging"] = True  # keep our logging config
    command.upgrade(cfg, "head")


def seed_taxonomy(session: Session) -> int:
    existing = {(t.kind, t.key) for t in session.scalars(select(Taxonomy))}
    added = 0
    for kind, rows in ((TaxonomyKind.DISCIPLINE, DISCIPLINES), (TaxonomyKind.CATEGORY, CATEGORIES)):
        for order, (key, label) in enumerate(rows):
            if (kind, key) not in existing:
                session.add(Taxonomy(kind=kind, key=key, label=label, sort_order=order))
                added += 1
    session.commit()
    return added


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ensure_database()
    migrate()
    with Session(get_engine()) as session:
        log.info("taxonomy rows added: %d", seed_taxonomy(session))


if __name__ == "__main__":
    main()
