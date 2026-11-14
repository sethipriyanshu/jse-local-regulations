from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import monitor, pipeline, storage, teams, worker
from app.api import admin_auth
from app.db import get_session_factory
from app.fetcher import FetchResult
from app.llm import LLMResult
from app.models import (
    ChangeEvent,
    ChangeStatus,
    Coverage,
    JobStatus,
    Rule,
    RuleStatus,
    SourceHealth,
)
from tests.helpers import add_rule, add_source, login, make_world

V1 = "Building Division\nThe City adopts the 2018 International Plumbing Code.\nCall us."
V2 = "Building Division\nThe City adopts the 2021 International Plumbing Code.\nCall us."


class Provider:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def structured(self, system: str, user: str, schema_name: str, *_a: Any,
                   **_k: Any) -> LLMResult:
        self.calls.append(schema_name)
        if schema_name == "triage":
            return LLMResult({"mep_relevant": True,
                              "summary": "Plumbing code moved from 2018 to 2021.",
                              "proposed_actions": [{"action": "update", "title": "IPC 2021",
                                                    "detail": "Edition changed."}]}, 300, 50, "f")
        return LLMResult({"code_adoptions": [{
            "code": "IPC", "edition": "2021", "amendments_summary": "", "effective_on": "",
            "excerpt": "The City adopts the 2021 International Plumbing Code.",
            "confidence": 0.9}], "rules": []}, 300, 50, "f")


def page(text: str, health: SourceHealth = SourceHealth.OK):  # type: ignore[no-untyped-def]
    return lambda url: FetchResult(health, 200, url, "text/html", text.encode(), text, "Codes")


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> storage.LocalBlobStore:
    s = storage.LocalBlobStore(tmp_path / "blobs")
    monkeypatch.setattr(pipeline, "get_store", lambda: s)
    monkeypatch.setattr(monitor, "get_store", lambda: s)
    return s


def test_diff_text_shows_changed_lines() -> None:
    d = monitor.diff_text(V1, V2)
    assert "-The City adopts the 2018" in d and "+The City adopts the 2021" in d
    assert monitor.diff_text("a" * 10, "b" * 10, max_chars=5).endswith("(diff truncated)")


def test_daily_run_detects_change_and_triages(session: Session, store: Any) -> None:
    w = make_world(session)
    src = add_source(session, w.city, "https://city.gov/codes")
    provider = Provider()

    # First run: no snapshot yet, so the source is ingested and extracted.
    first = monitor.run_daily(session, fetch_fn=page(V1), provider=provider)
    assert first.events == [] and provider.calls == ["extraction"]
    # Unchanged page: nothing new.
    assert monitor.run_daily(session, fetch_fn=page(V1), provider=provider).events == []

    result = monitor.run_daily(session, fetch_fn=page(V2), provider=provider)
    assert result.run.status == JobStatus.SUCCEEDED and result.run.changes_found == 1
    event = result.events[0]
    assert event.mep_relevant and "2018 to 2021" in (event.ai_summary or "")
    assert "+The City adopts the 2021" in event.diff_text
    assert event.proposed_actions and event.proposed_actions[0]["action"] == "update"
    session.refresh(w.city)
    assert w.city.coverage == Coverage.CHANGES_PENDING
    assert src.last_hash is not None


def test_daily_run_reports_unhealthy_and_isolates_errors(session: Session, store: Any) -> None:
    w = make_world(session)
    add_source(session, w.city, "https://city.gov/gone")
    add_source(session, w.county, "https://county.gov/boom")

    def fetch(url: str) -> FetchResult:
        if "boom" in url:
            raise RuntimeError("kaboom")
        return FetchResult(SourceHealth.NOT_FOUND, 404, url, None, b"", "", None, "HTTP 404")

    result = monitor.run_daily(session, fetch_fn=fetch, provider=Provider())
    assert result.run.status == JobStatus.SUCCEEDED  # one error doesn't fail the run
    assert [s.url for s in result.unhealthy] == ["https://city.gov/gone"]
    assert result.run.errors and "kaboom" in result.run.errors[0]["error"]


def test_worker_posts_digest_and_alert(session: Session, store: Any,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_world(session)
    add_source(session, w.city, "https://city.gov/codes")
    session.add(teams.TeamsChannel(name="ops", webhook_url="https://x.logic.azure.com/wf",
                                   sends_digest=True, sends_alerts=True))
    session.commit()
    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(monitor, "get_provider", Provider)
    monkeypatch.setattr(pipeline, "get_provider", Provider)
    monkeypatch.setattr(pipeline.fetcher, "fetch", page(V1))

    worker.daily(session, post=lambda url, card: posted.append(card))
    assert len(posted) == 1
    texts = str(posted[0])
    assert "Daily regulations digest" in texts and "Sources checked" in texts

    def broken(_u: str) -> FetchResult:
        raise RuntimeError("network down")

    posted.clear()
    monkeypatch.setattr(pipeline.fetcher, "fetch", broken)
    result = worker.daily(session, post=lambda url, card: posted.append(card))
    assert result.run.status == JobStatus.FAILED
    assert "job failed" in str(posted[0]) and "Daily regulations digest" in str(posted[1])


def test_change_lane_approve_reextracts(client: TestClient, session: Session, store: Any,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    admin_auth._attempts.clear()
    w = make_world(session)
    src = add_source(session, w.city, "https://city.gov/codes")
    add_rule(session, w.city, "IPC 2018 adopted", code="IPC", edition="2018",
             status=RuleStatus.VERIFIED, source=src)
    provider = Provider()
    monitor.run_daily(session, fetch_fn=page(V1), provider=provider)
    monitor.run_daily(session, fetch_fn=page(V2), provider=provider)
    event = session.scalars(select(ChangeEvent)).one()

    monkeypatch.setattr(pipeline, "get_provider", lambda: provider)
    bind = session.get_bind()
    client.app.dependency_overrides[get_session_factory] = (  # type: ignore[attr-defined]
        lambda: sessionmaker(bind=bind, expire_on_commit=False))
    login(client)
    lane = client.get("/api/admin/changes").json()
    assert lane[0]["id"] == event.id and "+The City adopts" in lane[0]["diff_text"]
    assert client.get("/api/admin/queue").json()["counts"]["changes"] == 1
    public = client.get("/api/jurisdictions/0177256/changes").json()
    assert public[0]["diff_text"] is None and public[0]["ai_summary"]

    r = client.post(f"/api/admin/changes/{event.id}/approve")
    assert r.json()["status"] == "approved"
    assert client.post(f"/api/admin/changes/{event.id}/approve").status_code == 409
    session.expire_all()
    titles = {r.title: r.status.value for r in session.scalars(select(Rule))}
    assert titles == {"IPC 2018 adopted": "verified", "IPC 2021 adopted": "pending"}
    assert session.get(ChangeEvent, event.id).status == ChangeStatus.APPROVED  # type: ignore[union-attr]
