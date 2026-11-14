from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import admin_auth
from app.models import AuditLog, CodeAdoption, Coverage, Rule, RuleStatus
from tests.helpers import add_rule, add_source, login, make_world


def test_verify_edit_and_supersede_adoption(client: TestClient, session: Session) -> None:
    admin_auth._attempts.clear()
    w = make_world(session)
    old = add_rule(session, w.county, "IPC 2018 adopted", code="IPC", edition="2018",
                   status=RuleStatus.VERIFIED)
    new = add_rule(session, w.county, "IPC 2021 adopted", code="IPC", edition="2021")
    session.add(CodeAdoption(jurisdiction_id=w.county.id, code="IPC", edition="2021",
                             rule_id=new.id))
    session.commit()

    assert client.post(f"/api/admin/rules/{new.id}/verify", json={}).status_code == 401
    login(client)
    queue = client.get("/api/admin/rules").json()
    assert queue["total"] == 1 and queue["rules"][0]["jurisdiction_name"] == "Tuscaloosa County"

    r = client.post(f"/api/admin/rules/{new.id}/verify",
                    json={"summary": "Adopts the 2021 IPC with local amendments.",
                          "effective_on": "2024-03-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["rule"]["status"] == "verified" and body["rule"]["supersedes_id"] == old.id
    assert [s["id"] for s in body["superseded"]] == [old.id]
    session.expire_all()
    assert session.get(Rule, old.id).status == RuleStatus.SUPERSEDED  # type: ignore[union-attr]
    row = session.scalars(select(CodeAdoption).where(CodeAdoption.rule_id == new.id)).one()
    assert row.status == RuleStatus.VERIFIED and row.effective_on == date(2024, 3, 1)
    assert w.county.coverage == Coverage.VERIFIED

    history = client.get(f"/api/rules/{new.id}/history").json()
    assert [h["code_edition"] for h in history] == ["2018"]
    actions = [a.action for a in session.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions == ["rule.supersede", "rule.edit_verify"]


def test_reject_and_bad_edits(client: TestClient, session: Session) -> None:
    admin_auth._attempts.clear()
    w = make_world(session)
    rule = add_rule(session, w.city, "Odd item", category="fees")
    login(client)
    bad = client.post(f"/api/admin/rules/{rule.id}/verify", json={"discipline": "nope"})
    assert bad.status_code == 422
    assert client.post(f"/api/admin/rules/{rule.id}/verify",
                       json={"effective_on": "03/01/2024"}).status_code == 422
    r = client.post(f"/api/admin/rules/{rule.id}/reject", json={"reason": "Wrong county"})
    assert r.json()["status"] == "rejected" and r.json()["review_note"] == "Wrong county"
    session.expire_all()
    assert w.city.coverage == Coverage.NONE


def test_verify_grounded_bulk(client: TestClient, session: Session) -> None:
    admin_auth._attempts.clear()
    w = make_world(session)
    src = add_source(session, w.city, "https://city.gov/codes")
    add_rule(session, w.city, "NEC 2020 adopted", code="NEC", edition="2020", source=src)
    shaky = add_rule(session, w.city, "IMC 2021 adopted", code="IMC", edition="2021",
                     source=src, grounded=False)
    login(client)
    assert client.post(f"/api/admin/sources/{src.id}/verify-grounded").json() == {"count": 1}
    remaining = client.get("/api/admin/rules", params={"source_id": src.id}).json()
    assert [r["id"] for r in remaining["rules"]] == [shaky.id]
    session.expire_all()
    assert w.city.coverage == Coverage.PARTIAL


def test_merged_regulations_inner_layer_wins(client: TestClient, session: Session) -> None:
    w = make_world(session)
    add_rule(session, w.state, "IPC 2018 adopted", code="IPC", edition="2018",
             status=RuleStatus.VERIFIED)
    add_rule(session, w.state, "NEC 2020 adopted", code="NEC", edition="2020",
             status=RuleStatus.VERIFIED, discipline="electrical")
    add_rule(session, w.city, "IPC 2021 adopted", code="IPC", edition="2021")
    add_rule(session, w.city, "Sealed drawings", category="permit_submittal")

    body = client.get("/api/jurisdictions/0177256/regulations").json()
    assert [s["name"] for s in body["stack"]] == ["Alabama", "Tuscaloosa County",
                                                  "Tuscaloosa city"]
    codes = {c["code"]: c for c in body["effective_codes"]}
    assert codes["IPC"]["edition"] == "2021" and codes["IPC"]["jurisdiction_fips"] == "0177256"
    assert codes["IPC"]["overrides"] == [{"jurisdiction_fips": "01", "jurisdiction_name":
                                          "Alabama", "edition": "2018"}]
    assert codes["NEC"]["jurisdiction_name"] == "Alabama"
    assert len(body["rules"]) == 4

    verified_only = client.get("/api/jurisdictions/0177256/regulations",
                               params={"include_pending": False}).json()
    assert {c["edition"] for c in verified_only["effective_codes"]} == {"2018", "2020"}

    # An address stack can be passed explicitly.
    county_only = client.get("/api/jurisdictions/01125/regulations",
                             params={"stack": "01,01125"}).json()
    assert [s["fips"] for s in county_only["stack"]] == ["01", "01125"]
    assert client.get("/api/jurisdictions/99/regulations").status_code == 404


def test_coverage_rolls_up_from_city_to_county(client: TestClient, session: Session) -> None:
    w = make_world(session)
    add_rule(session, w.city, "IPC 2021 adopted", code="IPC", edition="2021")
    from app.coverage import refresh_coverage

    refresh_coverage(session, w.city.id)
    session.commit()
    items = {c["fips"]: c["coverage"] for c in client.get("/api/jurisdictions/coverage").json()}
    assert items["0177256"] == "partial" and items["01125"] == "partial"
    assert items["01"] == "none"
