import httpx
import pymupdf
import pytest

from app import fetcher
from app.models import SourceHealth
from app.urls import UnsafeUrl, assert_public, normalize_url, url_hash


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetcher, "_throttle", lambda _d: None)
    fetcher._robots.clear()


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, follow_redirects=False)


def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat every *.gov test host as public without real DNS."""
    real = fetcher.assert_public

    def fake(url: str) -> None:
        if ".gov" in url:
            return
        real(url)

    monkeypatch.setattr(fetcher, "assert_public", fake)


def test_normalize_and_hash_dedupe() -> None:
    a = normalize_url("HTTPS://WWW.Example.gov/codes/?utm_source=x&page=2#top")
    assert a == "https://www.example.gov/codes?page=2"
    assert normalize_url("example.gov") == "https://example.gov/"
    assert url_hash("https://example.gov/codes/") == url_hash("https://EXAMPLE.gov/codes")
    with pytest.raises(UnsafeUrl):
        normalize_url("ftp://example.gov/file")


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000/x",
                                 "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/"])
def test_private_addresses_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrl):
        assert_public(url)


def test_html_fetch_extracts_main_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)
    html = ("<html><head><title>Adopted Codes</title></head><body><nav>Home | About</nav>"
            "<main><h1>Adopted Codes</h1><p>The City has adopted the 2021 International "
            "Mechanical Code with local amendments effective January 1, 2023.</p></main></body></html>")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, html=html)

    r = fetcher.fetch("https://city.gov/codes", client=_client(httpx.MockTransport(handler)))
    assert r.ok and r.health == SourceHealth.OK
    assert r.title == "Adopted Codes"
    assert "2021 International Mechanical Code" in r.text


def test_redirect_to_private_address_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    r = fetcher.fetch("https://city.gov/x", client=_client(httpx.MockTransport(handler)))
    assert r.health == SourceHealth.BLOCKED and not r.ok


def test_bot_challenge_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(403, html="<title>Just a moment...</title>Enable JavaScript and "
                                        "cookies to continue")

    r = fetcher.fetch("https://library.gov/codes", client=_client(httpx.MockTransport(handler)))
    assert r.health == SourceHealth.BLOCKED
    assert r.error and "bot protection" in r.error


def test_robots_disallow_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(200, html="<p>secret</p>")

    r = fetcher.fetch("https://city.gov/private/page", client=_client(httpx.MockTransport(handler)))
    assert r.health == SourceHealth.BLOCKED and "robots" in (r.error or "")


def test_pdf_fetch_and_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "2020 National Electrical Code adopted.")
    pdf = doc.tobytes()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/gone":
            return httpx.Response(404)
        return httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})

    client = _client(httpx.MockTransport(handler))
    r = fetcher.fetch("https://state.gov/bulletin.pdf", client=client)
    assert r.ok and r.content_type == "application/pdf"
    assert "2020 National Electrical Code" in r.text
    assert fetcher.fetch("https://state.gov/gone", client=client).health == SourceHealth.NOT_FOUND
