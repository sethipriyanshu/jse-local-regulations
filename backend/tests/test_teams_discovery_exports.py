import io
import json
from typing import Any

import pymupdf
import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import discovery, teams
from app.api import admin_auth
from app.fetcher import FetchResult
from app.models import JobStatus, RuleStatus, Source, SourceHealth, SourceStatus
from tests.helpers import add_rule, add_source, login, make_world

# --- Teams --------------------------------------------------------------------


def test_webhook_validation_and_masking() -> None:
    good = "https://prod-12.westus.logic.azure.com:443/workflows/abc/triggers/manual?sig=SECRET1"
    assert teams.validate_webhook_url(good) == good
    for bad in ["http://prod.logic.azure.com/x", "https://evil.example.com/hook",
                "https://169.254.169.254/latest", "https://logic.azure.com.evil.io/x"]:
        with pytest.raises(teams.InvalidWebhook):
            teams.validate_webhook_url(bad)
    assert "SECRET" not in teams.mask_webhook(good)[:-6]


def test_teams_channel_admin_api(client: TestClient, session: Session,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    admin_auth._attempts.clear()
    make_world(session)
    login(client)
    url = "https://x.environment.api.powerplatform.com/powerautomate/flows/1?sig=TOPSECRET"
    bad = client.post("/api/admin/teams", json={"name": "x", "webhook_url": "https://a.com/h"})
    assert bad.status_code == 422
    r = client.post("/api/admin/teams", json={"name": "Atlanta office", "webhook_url": url,
                                              "metro": "atlanta"})
    assert r.status_code == 201 and "TOPSECRET" not in json.dumps(r.json())
    listed = client.get("/api/admin/teams").json()
    assert listed[0]["metro"] == "atlanta" and "TOPSECRET" not in json.dumps(listed)

    sent: list[str] = []
    monkeypatch.setattr(teams, "post_card", lambda u, card: sent.append(u))
    assert client.post(f"/api/admin/teams/{r.json()['id']}/test").status_code == 200
    assert sent == [url]
    assert client.delete(f"/api/admin/teams/{r.json()['id']}").status_code == 204
    assert client.get("/api/admin/teams").json() == []


def test_digest_card_filters_by_metro(session: Session) -> None:
    from app.models import ChangeEvent, JobRun, Snapshot

    w = make_world(session)
    src = add_source(session, w.city, "https://city.gov/codes")
    snap = Snapshot(source_id=src.id, content_hash="h", blob_raw="r", blob_text="t", char_count=1)
    session.add(snap)
    session.flush()
    event = ChangeEvent(source_id=src.id, new_snapshot_id=snap.id, diff_text="+x",
                        mep_relevant=True, ai_summary="IPC edition changed.")
    run = JobRun(job="daily_monitor", sources_checked=3)
    session.add_all([event, run])
    session.commit()
    card = teams.digest_card(session, run, [event], [])
    assert card and "IPC edition changed." in json.dumps(card)
    assert teams.digest_card(session, run, [event], [], metro="denver") is None
    assert teams.digest_card(session, run, [event], [], metro="tuscaloosa") is not None


# --- discovery ----------------------------------------------------------------


class FakeSearcher:
    def __init__(self, cands: list[discovery.Candidate]) -> None:
        self.cands = cands

    def search(self, session: Session, jurisdiction: Any) -> list[discovery.Candidate]:
        return self.cands


def _fetch(url: str) -> FetchResult:
    if "missing" in url:
        return FetchResult(SourceHealth.NOT_FOUND, 404, url, None, b"", "", None, "404")
    if "municode" in url:
        return FetchResult(SourceHealth.BLOCKED, 403, url, None, b"", "", None, "challenge")
    return FetchResult(SourceHealth.OK, 200, url, "text/html", b"x", "x", "Adopted Codes")


def test_discover_filters_and_queues_candidates(session: Session,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "assert_public", lambda _u: None)
    w = make_world(session)
    add_source(session, w.city, "https://www.tuscaloosa.com/rejected",
               status=SourceStatus.REJECTED)
    # Known URLs are matched on the normalized hash, like user submissions.
    session.scalars(select(Source)).one().url_hash = discovery.url_hash(
        "https://www.tuscaloosa.com/rejected")
    session.commit()
    C = discovery.Candidate
    searcher = FakeSearcher([
        C("https://www.tuscaloosa.com/adoptedcodes", "", "Lists adopted codes", "government", 0.8),
        C("tuscaloosa.com/adoptedcodes/", "", "Same page again", "government", 0.7),
        C("https://tuscaloosa.com/rejected", "", "Was rejected", "government", 0.9),
        C("https://www.tuscaloosa.com/missing", "", "Dead link", "government", 0.9),
        C("https://library.municode.com/al/tuscaloosa", "Code", "Buildings chapter",
          "code_library", 0.6),
        C("https://library.municode.com/al/tuscaloosa?nodeId=2", "Code", "Same library",
          "code_library", 0.5),
        C("https://permits-r-us.com/tuscaloosa", "", "A contractor blog", "other", 0.4),
        C("ftp://weird", "", "Unsafe", "other", 0.1),
    ])
    result = discovery.discover(session, w.city, searcher=searcher, fetch_fn=_fetch)
    assert len(result.added) == 2 and result.already_known == 3
    assert result.unreachable == 1 and result.unsafe == 1 and result.off_topic == 1
    added = session.scalars(select(Source).where(Source.id.in_(result.added))
                            .order_by(Source.id)).all()
    # A URL already filed under another layer is not suggested again.
    again = discovery.discover(session, w.county, searcher=searcher, fetch_fn=_fetch)
    again_urls = [session.get(Source, i).url for i in again.added]  # type: ignore[union-attr]
    assert again_urls == ["https://library.municode.com/al/tuscaloosa?nodeId=2"]
    assert added[0].origin.value == "ai" and added[0].status == SourceStatus.SUBMITTED
    assert added[0].title == "Adopted Codes" and added[0].discovery_score == 0.8
    assert "upload it" in (added[1].discovery_reason or "")


def test_discovery_job_api(client: TestClient, session: Session,
                           monkeypatch: pytest.MonkeyPatch) -> None:
    admin_auth._attempts.clear()
    make_world(session)
    calls: list[int] = []
    monkeypatch.setattr(discovery, "run_job_in_background",
                        lambda factory, job_id: calls.append(job_id))
    login(client)
    r = client.post("/api/admin/discovery", json={})
    assert r.status_code == 202 and r.json()["total"] == 3
    assert r.json()["summary"]["fips"] == ["01", "01125", "0177256"]  # state first
    assert calls == [r.json()["id"]]
    assert client.post("/api/admin/discovery", json={}).status_code == 409  # one at a time

    job = session.get(discovery.JobRun, r.json()["id"])
    assert job is not None
    discovery.run_job(session, job, searcher=FakeSearcher([]), fetch_fn=_fetch, interval_s=0)
    done = client.get(f"/api/admin/jobs/{job.id}").json()
    assert done["status"] == JobStatus.SUCCEEDED and done["done"] == 3


# --- exports ------------------------------------------------------------------


@pytest.fixture
def seeded(session: Session) -> Session:
    w = make_world(session)
    src = add_source(session, w.city, "https://city.gov/codes")
    add_rule(session, w.state, "IPC 2018 adopted", code="IPC", edition="2018",
             status=RuleStatus.VERIFIED)
    add_rule(session, w.city, "IPC 2021 adopted", code="IPC", edition="2021", source=src)
    add_rule(session, w.city, "Sealed MEP drawings – § 6-22", category="permit_submittal",
             status=RuleStatus.VERIFIED, discipline="general", source=src)
    return session


def test_json_export(client: TestClient, seeded: Session) -> None:
    r = client.get("/api/jurisdictions/0177256/export.json", params={"address": "1 Main St"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["schema_version"] == "1.0" and data["address"] == "1 Main St"
    assert [c["edition"] for c in data["effective_codes"]] == ["2021"]
    assert data["sources"][0]["url"] == "https://city.gov/codes"
    verified = client.get("/api/jurisdictions/0177256/export.json",
                          params={"include_pending": False, "disciplines": "general"}).json()
    assert [r["title"] for r in verified["rules"]] == ["Sealed MEP drawings – § 6-22"]
    assert verified["effective_codes"] == []


def test_docx_and_pdf_exports(client: TestClient, seeded: Session) -> None:
    docx = client.get("/api/jurisdictions/0177256/export.docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    text = "\n".join(p.text for p in Document(io.BytesIO(docx.content)).paragraphs)
    assert "MEP Regulations Summary" in text and "Sealed MEP drawings" in text
    assert "Disclaimer" in text

    pdf = client.get("/api/jurisdictions/0177256/export.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    pdf_text = "".join(page.get_text() for page in pymupdf.open(stream=pdf.content))
    assert "Tuscaloosa city, AL" in pdf_text and "IPC" in pdf_text
    assert "§ 6-22" in pdf_text
