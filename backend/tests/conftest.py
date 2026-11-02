"""Unit tests run against in-memory SQLite so they need no containers.
Migrations are checked against real SQL Server in CI (see .github/workflows/ci.yml)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import get_session
from app.main import create_app
from app.models import Base

TEST_SETTINGS = Settings(
    database_url="sqlite://", admin_passcode="test-pass", session_secret="test-secret"
)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s
    engine.dispose()


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: TEST_SETTINGS
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
