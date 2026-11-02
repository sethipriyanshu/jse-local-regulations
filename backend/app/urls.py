"""URL normalization and safety checks for user-submitted sources.

The server fetches URLs that users type in, so every hop (including redirects) is
checked to be a public http(s) address to avoid SSRF into Azure-internal services.
"""

import hashlib
import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "_ga"}


class UnsafeUrl(ValueError):
    pass


def normalize_url(raw: str) -> str:
    """Canonical form used for dedupe: lowercase scheme/host, no fragment, no default
    port, no tracking params, no trailing slash on non-root paths."""
    raw = raw.strip()
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise UnsafeUrl("Only http(s) URLs with a host name are allowed")
    host = parts.hostname.lower()
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    query = urlencode([
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ])
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def url_hash(url: str) -> str:
    """Dedupe key: the normalized URL, ignoring http vs https and a leading "www."."""
    parts = urlsplit(normalize_url(url))
    key = urlunsplit(("", parts.netloc.removeprefix("www."), parts.path, parts.query, ""))
    return hashlib.sha256(key.encode()).hexdigest()


def domain_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


def assert_public(url: str) -> None:
    """Raise UnsafeUrl unless every address the host resolves to is public."""
    host = urlsplit(url).hostname
    if not host:
        raise UnsafeUrl("URL has no host")
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise UnsafeUrl("Local addresses are not allowed")
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"Could not resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UnsafeUrl("URL resolves to a private or reserved address")


def is_official_domain(domain: str) -> bool:
    """Government domains get a trust boost in discovery and bulk approval."""
    return domain.endswith((".gov", ".us", ".mil")) or ".gov." in domain
