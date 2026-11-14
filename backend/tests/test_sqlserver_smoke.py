"""Runs the main queries against a real database (SQL Server in CI). SQLite accepts
some SQL that SQL Server rejects (e.g. `IS 1`), so unit tests alone aren't enough.

Skipped unless RUN_DB_SMOKE=1; uses DATABASE_URL and expects `app.bootstrap` to have run."""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.main import create_app
from app.models import (
    ChangeEvent,
    Jurisdiction,
    Origin,
    Rule,
    RuleStatus,
    Snapshot,
    Source,
    SourceStatus,
    TeamsChannel,
)
from tests.helpers import tax_id

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DB_SMOKE") != "1",
                                reason="set RUN_DB_SMOKE=1 to run against DATABASE_URL")


def test_endpoints_against_real_database() -> None:
    from app.models import TaxonomyKind

    get_settings.cache_clear()
    tag = uuid.uuid4().hex[:8]
    with Session(get_engine()) as s:
        city = s.scalars(select(Jurisdiction).where(Jurisdiction.fips == "0177256")).one()
        src = Source(jurisdiction_id=city.id, url=f"https://example.gov/{tag}", url_hash=tag,
                     domain="example.gov", status=SourceStatus.APPROVED, origin=Origin.ADMIN)
        s.add(src)
        s.flush()
        snap = Snapshot(source_id=src.id, content_hash=tag, blob_raw="r", blob_text="t",
                        char_count=1)
        s.add(snap)
        s.flush()
        s.add(ChangeEvent(source_id=src.id, new_snapshot_id=snap.id, diff_text="+x",
                          mep_relevant=None, ai_summary="smoke"))
        rule = Rule(jurisdiction_id=city.id, title=f"IPC 2021 adopted {tag}", summary="s",
                    code_ref="IPC", code_edition="2021", status=RuleStatus.PENDING,
                    origin=Origin.AI, grounded=True, source_id=src.id,
                    category_id=tax_id(s, TaxonomyKind.CATEGORY, "adopted_code"),
                    discipline_id=tax_id(s, TaxonomyKind.DISCIPLINE, "plumbing"))
        s.add(rule)
        s.add(TeamsChannel(name=tag, webhook_url="https://x.logic.azure.com/wf"))
        s.commit()
        rule_id, src_id = rule.id, src.id

    with TestClient(create_app()) as c:
        for path in ["/api/health", "/api/taxonomy", "/api/jurisdictions/coverage",
                     "/api/jurisdictions/search?q=tusca", "/api/jurisdictions/0177256",
                     "/api/jurisdictions/0177256/regulations",
                     "/api/jurisdictions/0177256/regulations?include_pending=false",
                     "/api/jurisdictions/0177256/changes", "/api/jurisdictions/0177256/sources",
                     "/api/jurisdictions/0177256/rules", f"/api/rules/{rule_id}/history",
                     "/api/jurisdictions/0177256/export.json",
                     "/api/jurisdictions/0177256/export.pdf"]:
            assert c.get(path).status_code == 200, path

        assert c.post("/api/admin/login",
                      json={"passcode": get_settings().admin_passcode}).status_code == 200
        for path in ["/api/admin/queue", "/api/admin/rules", "/api/admin/changes",
                     "/api/admin/changes?include_irrelevant=true", "/api/admin/overview",
                     "/api/admin/jobs", "/api/admin/audit", "/api/admin/teams"]:
            assert c.get(path).status_code == 200, path
        assert c.post(f"/api/admin/sources/{src_id}/verify-grounded").json()["count"] >= 1
        reg = c.get("/api/jurisdictions/0177256/regulations").json()
        assert any(e["code"] == "IPC" for e in reg["effective_codes"])
