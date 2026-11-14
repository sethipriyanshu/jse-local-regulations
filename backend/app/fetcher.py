"""Fetch a source URL politely and turn it into clean text.

- Public addresses only, re-checked on every redirect hop (see urls.assert_public).
- robots.txt is honored; requests to one domain are spaced out.
- Bot-challenge pages (Cloudflare "Just a moment...", used by Municode and American
  Legal) are reported as BLOCKED. We do not try to get around them; those codes come
  in through PDF upload or manual entry instead.
- HTML → main-content text (trafilatura); PDF → text (PyMuPDF).
"""

import re
import threading
import time
from dataclasses import dataclass
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import get_settings
from app.models import SourceHealth
from app.urls import UnsafeUrl, assert_public

MAX_REDIRECTS = 5
CHALLENGE_MARKERS = (
    "just a moment...",
    "enable javascript and cookies to continue",
    "cf-chl-",
    "challenge-platform",
    "attention required! | cloudflare",
)


@dataclass
class FetchResult:
    health: SourceHealth
    http_status: int | None
    final_url: str
    content_type: str
    raw: bytes
    text: str
    title: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.health in (SourceHealth.OK, SourceHealth.REDIRECTED) and bool(self.text)


_last_hit: dict[str, float] = {}
_robots: dict[str, robotparser.RobotFileParser | None] = {}
_lock = threading.Lock()


def _throttle(domain: str) -> None:
    gap = get_settings().fetch_min_interval_s
    with _lock:
        wait = _last_hit.get(domain, 0) + gap - time.monotonic()
        _last_hit[domain] = time.monotonic() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)


def _robots_allows(client: httpx.Client, url: str, agent: str) -> bool:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots:
        rp: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
        try:
            res = client.get(origin + "/robots.txt", follow_redirects=True)
            if res.status_code >= 400:
                rp = None  # no robots.txt: everything allowed
            else:
                assert rp is not None
                rp.parse(res.text.splitlines())
        except httpx.HTTPError:
            rp = None
        _robots[origin] = rp
    rp = _robots[origin]
    return rp is None or rp.can_fetch(agent, url)


def _looks_like_challenge(status: int, body: bytes) -> bool:
    if status not in (403, 429, 503):
        return False
    head = body[:20_000].decode("utf-8", "ignore").lower()
    return any(m in head for m in CHALLENGE_MARKERS)


def html_to_text(html: str) -> tuple[str, str | None]:
    import trafilatura

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else None
    main = normalize_text(trafilatura.extract(
        html, include_tables=True, include_links=False, favor_recall=True, deduplicate=True
    ) or "")
    # trafilatura drops link-only lists as boilerplate, and an adopted-codes page is often
    # exactly that (each code links to the ICC viewer). When it keeps less than half of
    # the page's text, use the whole page body instead.
    full = normalize_text(_block_text(html))
    return (main if len(main) >= FALLBACK_RATIO * len(full) else full), title


FALLBACK_RATIO = 0.5
_DROP = re.compile(r"<(script|style|noscript|template|svg|nav|header|footer|head)\b[^>]*>.*?</\1>",
                   re.S | re.I)
_BLOCK = re.compile(r"</?(p|div|li|ul|ol|h[1-6]|br|tr|table|section|article|dd|dt)\b[^>]*>",
                    re.I)


def _block_text(html: str) -> str:
    """Tag stripping that keeps one line per block element."""
    from html import unescape

    text = _DROP.sub(" ", re.sub(r"<!--.*?-->", " ", html, flags=re.S))
    text = _BLOCK.sub("\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(text)


def pdf_to_text(data: bytes) -> tuple[str, str | None]:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        title = (doc.metadata or {}).get("title") or None
        pages = [f"[page {i + 1}]\n{page.get_text()}" for i, page in enumerate(doc)]
    return normalize_text("\n".join(pages)), title


def normalize_text(text: str) -> str:
    """Stable text for hashing and diffing: unify whitespace, drop empty lines."""
    lines = (re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def fetch(url: str, client: httpx.Client | None = None) -> FetchResult:
    settings = get_settings()
    agent = settings.fetch_user_agent
    owns = client is None
    client = client or httpx.Client(
        timeout=settings.fetch_timeout_s, headers={"User-Agent": agent}, follow_redirects=False
    )

    def fail(health: SourceHealth, status: int | None, error: str) -> FetchResult:
        return FetchResult(health, status, url, "", b"", "", None, error)

    try:
        current = url
        redirected = False
        for _ in range(MAX_REDIRECTS + 1):
            try:
                assert_public(current)
            except UnsafeUrl as exc:
                return fail(SourceHealth.BLOCKED, None, str(exc))
            if not _robots_allows(client, current, agent):
                return fail(SourceHealth.BLOCKED, None, "Disallowed by the site's robots.txt")
            _throttle(urlsplit(current).hostname or "")

            with client.stream("GET", current) as res:
                if res.is_redirect and "location" in res.headers:
                    current = urljoin(current, res.headers["location"])
                    redirected = True
                    continue
                body = b""
                for chunk in res.iter_bytes():
                    body += chunk
                    if len(body) > settings.fetch_max_bytes:
                        return fail(SourceHealth.ERROR, res.status_code, "Page is too large")
                status = res.status_code
                ctype = res.headers.get("content-type", "").split(";")[0].strip().lower()
            break
        else:
            return fail(SourceHealth.ERROR, None, "Too many redirects")

        if _looks_like_challenge(status, body):
            return FetchResult(SourceHealth.BLOCKED, status, current, ctype, body, "", None,
                               "Site requires a browser challenge (bot protection)")
        if status == 404 or status == 410:
            return fail(SourceHealth.NOT_FOUND, status, f"HTTP {status}")
        if status >= 400:
            health = SourceHealth.BLOCKED if status in (401, 403) else SourceHealth.ERROR
            return fail(health, status, f"HTTP {status}")

        is_pdf = ctype == "application/pdf" or body[:5] == b"%PDF-"
        if is_pdf:
            text, title = pdf_to_text(body)
            ctype = "application/pdf"
        else:
            text, title = html_to_text(body.decode(res.encoding or "utf-8", "replace"))
        health = SourceHealth.REDIRECTED if redirected else SourceHealth.OK
        return FetchResult(health, status, current, ctype or "text/html", body, text, title)
    except httpx.HTTPError as exc:
        return fail(SourceHealth.ERROR, None, f"{type(exc).__name__}: {exc}")
    finally:
        if owns:
            client.close()
