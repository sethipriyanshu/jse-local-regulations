from fastapi.testclient import TestClient

from app.api import admin_auth


def test_health_reports_db_ok(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_admin_session_defaults_to_user_view(client: TestClient) -> None:
    assert client.get("/api/admin/session").json() == {"admin": False}


def test_admin_login_sets_cookie_and_logout_clears_it(client: TestClient) -> None:
    admin_auth._attempts.clear()
    assert client.post("/api/admin/login", json={"passcode": "test-pass"}).status_code == 200
    assert client.get("/api/admin/session").json() == {"admin": True}

    client.post("/api/admin/logout")
    assert client.get("/api/admin/session").json() == {"admin": False}


def test_wrong_passcode_rejected_then_rate_limited(client: TestClient) -> None:
    admin_auth._attempts.clear()
    for _ in range(admin_auth.MAX_ATTEMPTS_PER_MINUTE):
        assert client.post("/api/admin/login", json={"passcode": "nope"}).status_code == 401
    assert client.post("/api/admin/login", json={"passcode": "test-pass"}).status_code == 429


def test_tampered_cookie_is_not_admin(client: TestClient) -> None:
    client.cookies.set(admin_auth.COOKIE, "9999999999.deadbeef")
    assert client.get("/api/admin/session").json() == {"admin": False}
