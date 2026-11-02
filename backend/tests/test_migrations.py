from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migrations_match_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    cfg.attributes["skip_logging"] = True
    command.upgrade(cfg, "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], f"models changed without a migration: {diff}"
