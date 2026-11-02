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
from app.jurisdictions import load_jurisdictions
from app.models import Taxonomy, TaxonomyKind
from app.taxonomy import CATEGORIES, DISCIPLINES

log = logging.getLogger("bootstrap")
BACKEND_DIR = Path(__file__).resolve().parents[1]

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
        log.info("jurisdictions added: %d", load_jurisdictions(session))


if __name__ == "__main__":
    main()
