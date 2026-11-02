from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import pipeline, storage
from app.api import admin_auth, sources
from app.bootstrap import seed_taxonomy
from app.db import get_session_factory
from app.fetcher import FetchResult
from app.llm import LLMResult
from app.models import AuditLog, Jurisdiction, JurisdictionType, Rule, Source, SourceHealth

PAGE_TEXT = "The City adopts the 2021 International Plumbing Code effective March 1, 2024."


class FakeProvider:
    name = "fake"

    def structured(self, *_a: object, **_k: object) -> LLMResult:
        return LLMResult({"code_adoptions": [{
            "code": "IPC", "edition": "2021", "amendments_summary": "",
            "effective_on": "2024-03-01", "confidence": 0.9,
            "excerpt": "The City adopts the 2021 International Plumbing Code effective March 1, 2024.",
        }], "rules": []}, 500, 100, "fake-1")


@pytest.fixture
def api(client: TestClient, session: Session, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    seed_taxonomy(session)
    session.add(Jurisdiction(fips="01125", name="Tuscaloosa County",
                             type=JurisdictionType.COUNTY, state_code="AL"))
    session.commit()

    store = storage.LocalBlobStore(tmp_path / "blobs")
    monkeypatch.setattr(pipeline, "get_store", lambda: store)
    monkeypatch.setattr(sources, "get_store", lambda: store)
    monkeypatch.setattr(sources, "assert_public", lambda _u: None)
    monkeypatch.setattr(pipeline, "get_provider", lambda: FakeProvider())
    monkeypatch.setattr(pipeline.fetcher, "fetch", lambda url: FetchResult(
        SourceHealth.OK, 200, url, "text/html", PAGE_TEXT.encode(), PAGE_TEXT, "Codes"))
    # Background tasks need a session bound to the same in-memory DB.
    bind = session.get_bind()
    client.app.dependency_overrides[get_session_factory] = (  # type: ignore[attr-defined]
        lambda: sessionmaker(bind=bind, expire_on_commit=False))
    admin_auth._attempts.clear()
    yield client


def _login(c: TestClient) -> None:
    assert c.post("/api/admin/login", json={"passcode": "test-pass"}).status_code == 200


def test_user_submission_goes_to_queue_then_admin_approves_and_extracts(
    api: TestClient, session: Session
) -> None:
    r = api.post("/api/jurisdictions/01125/sources",
                 json={"url": "https://www.tuscaloosa-al.gov/codes/", "submitted_by_name": "Pat"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "submitted" and body["url"] == "https://www.tuscaloosa-al.gov/codes"
    assert api.get("/api/admin/queue").status_code == 401  # user view can't see the queue

    # Duplicate submissions are refused with a clear message.
    dup = api.post("/api/jurisdictions/01125/sources", json={"url": "tuscaloosa-al.gov/codes"})
    assert dup.status_code == 409 and "waiting for review" in dup.json()["detail"]

    _login(api)
    queue = api.get("/api/admin/queue").json()
    assert queue["counts"]["sources"] == 1
    approved = api.post(f"/api/admin/sources/{body['id']}/approve").json()
    assert approved["status"] == "approved"

    # Background ingest ran: snapshot, extraction, pending rule linked to the source.
    session.expire_all()
    rules = session.scalars(select(Rule)).all()
    assert [r.title for r in rules] == ["IPC 2021 adopted"]
    assert rules[0].grounded is True and rules[0].status.value == "pending"
    listed = api.get("/api/jurisdictions/01125/sources").json()
    assert listed[0]["health"] == "ok" and listed[0]["rule_count"] == 1
    actors = [a.actor for a in session.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actors == ["Pat", "admin"]


def test_rejected_url_is_remembered_and_hidden_from_users(api: TestClient) -> None:
    src = api.post("/api/jurisdictions/01125/sources", json={"url": "https://spam.example.com"})
    _login(api)
    api.post(f"/api/admin/sources/{src.json()['id']}/reject", json={"reason": "Not official"})
    api.post("/api/admin/logout")
    again = api.post("/api/jurisdictions/01125/sources", json={"url": "spam.example.com/"})
    assert again.status_code == 409 and "rejected" in again.json()["detail"]
    assert api.get("/api/jurisdictions/01125/sources").json() == []


def test_admin_added_source_is_approved_immediately(api: TestClient) -> None:
    _login(api)
    r = api.post("/api/jurisdictions/01125/sources", json={"url": "https://county.gov/building"})
    assert r.json()["status"] == "approved" and r.json()["origin"] == "admin"
    rules = api.get("/api/jurisdictions/01125/rules").json()
    assert rules[0]["source_url"] == "https://county.gov/building"


def test_pdf_upload_flow(api: TestClient, session: Session) -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), PAGE_TEXT)
    pdf = doc.tobytes()
    files = {"file": ("ordinance.pdf", pdf, "application/pdf")}
    r = api.post("/api/jurisdictions/01125/uploads", files=files, data={"title": "Ord. 9876"})
    assert r.status_code == 201 and r.json()["is_upload"] and r.json()["status"] == "submitted"
    assert api.post("/api/jurisdictions/01125/uploads", files=files).status_code == 409

    not_pdf = {"file": ("x.pdf", b"hello", "application/pdf")}
    assert api.post("/api/jurisdictions/01125/uploads", files=not_pdf).status_code == 422

    _login(api)
    api.post(f"/api/admin/sources/{r.json()['id']}/approve")
    session.expire_all()
    src = session.scalars(select(Source)).one()
    assert src.fetch_mode.value == "pdf" and src.health == SourceHealth.OK
    assert session.scalars(select(Rule)).one().title == "IPC 2021 adopted"


def test_manual_rule_entry(api: TestClient) -> None:
    r = api.post("/api/jurisdictions/01125/rules", json={
        "title": "Backflow preventer required on irrigation", "summary": "Testable RPZ required.",
        "discipline": "plumbing", "category": "local_amendment",
        "source_url": "https://county.gov/plumbing", "submitted_by_name": "Sam",
    })
    assert r.status_code == 201
    rule = r.json()
    assert rule["status"] == "pending" and rule["origin"] == "user"
    assert rule["discipline"] == "plumbing" and rule["source_url"] == "https://county.gov/plumbing"
    # The cited URL became a submitted source for the admin to consider monitoring.
    assert api.get("/api/jurisdictions/01125/sources").json()[0]["status"] == "submitted"

    bad = api.post("/api/jurisdictions/01125/rules", json={
        "title": "x" * 5, "summary": "y" * 5, "discipline": "nope", "category": "fees"})
    assert bad.status_code == 422


def test_taxonomy_endpoint(api: TestClient) -> None:
    t = api.get("/api/taxonomy").json()
    assert t["disciplines"][0]["key"] == "mechanical"
    assert any(c["key"] == "permit_submittal" for c in t["categories"])
