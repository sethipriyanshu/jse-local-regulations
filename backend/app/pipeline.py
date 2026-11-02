"""Source ingestion: fetch (or read an upload) → snapshot → AI extraction."""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import fetcher
from app.extract import ExtractStats, extract_snapshot
from app.fetcher import FetchResult, pdf_to_text
from app.llm import LLMNotConfigured, LLMProvider, get_provider
from app.models import FetchMode, Snapshot, Source, SourceHealth
from app.storage import get_store

log = logging.getLogger(__name__)
UPLOAD_SCHEME = "upload://"


@dataclass
class IngestResult:
    source_id: int
    health: SourceHealth
    snapshot_id: int | None = None
    changed: bool = False
    error: str | None = None
    extract: ExtractStats | None = field(default=None)


def upload_blob_name(sha: str) -> str:
    return f"uploads/{sha}.pdf"


def _read_upload(source: Source) -> FetchResult:
    sha = source.url.removeprefix(UPLOAD_SCHEME).split("/", 1)[0]
    raw = get_store().get(upload_blob_name(sha))
    text, title = pdf_to_text(raw)
    return FetchResult(SourceHealth.OK, None, source.url, "application/pdf", raw, text, title)


def ingest_source(
    session: Session,
    source: Source,
    *,
    extract: bool = True,
    force_extract: bool = False,
    fetch_fn: Callable[[str], FetchResult] | None = None,
    provider: LLMProvider | None = None,
) -> IngestResult:
    """Fetch a source and store a snapshot if its text changed. Extraction runs on new
    snapshots (or always with force_extract). Returns what happened; never raises for
    fetch problems, which are recorded on the source's health instead."""
    is_upload = source.url.startswith(UPLOAD_SCHEME)
    fetched = _read_upload(source) if is_upload else (fetch_fn or fetcher.fetch)(source.url)
    now = datetime.now(UTC)
    source.health = fetched.health
    result = IngestResult(source.id, fetched.health, error=fetched.error)

    if not fetched.ok:
        source.last_fetched_at = now
        session.commit()
        log.warning("source %s fetch failed: %s", source.id, fetched.error)
        return result

    content_hash = hashlib.sha256(fetched.text.encode()).hexdigest()
    if fetched.content_type == "application/pdf":
        source.fetch_mode = FetchMode.PDF
    if not source.title and fetched.title:
        source.title = fetched.title[:512]

    snapshot: Snapshot | None = None
    if content_hash != source.last_hash:
        store = get_store()
        stem = f"snapshots/{source.id}/{now:%Y%m%dT%H%M%S}-{content_hash[:12]}"
        ext = "pdf" if fetched.content_type == "application/pdf" else "html"
        store.put(f"{stem}.{ext}", fetched.raw, fetched.content_type or "text/html")
        store.put(f"{stem}.txt", fetched.text.encode(), "text/plain; charset=utf-8")
        snapshot = Snapshot(
            source_id=source.id, http_status=fetched.http_status, final_url=fetched.final_url,
            content_hash=content_hash, blob_raw=f"{stem}.{ext}", blob_text=f"{stem}.txt",
            char_count=len(fetched.text),
        )
        session.add(snapshot)
        source.last_hash = content_hash
        session.commit()
        result.changed = True
        result.snapshot_id = snapshot.id
    elif force_extract:
        snapshot = (
            session.query(Snapshot).filter_by(source_id=source.id)
            .order_by(Snapshot.id.desc()).first()
        )
        result.snapshot_id = snapshot.id if snapshot else None
    else:
        session.commit()

    if extract and snapshot is not None:
        try:
            result.extract = extract_snapshot(
                session, provider or get_provider(), source, snapshot, fetched.text
            )
        except LLMNotConfigured as exc:
            result.error = str(exc)
            log.warning("skipping extraction: %s", exc)
    # Set last: the UI treats an approved source without last_fetched_at as still processing.
    source.last_fetched_at = now
    session.commit()
    return result


def ingest_in_background(session_factory: Callable[[], Session], source_id: int,
                         force_extract: bool = False) -> None:
    """Entry point for FastAPI BackgroundTasks: own session, never raises."""
    with session_factory() as session:
        source = session.get(Source, source_id)
        if source is None:
            return
        try:
            ingest_source(session, source, force_extract=force_extract)
        except Exception:
            log.exception("ingest failed for source %s", source_id)
            session.rollback()
            source = session.get(Source, source_id)
            if source is not None:
                source.health = SourceHealth.ERROR
                source.last_fetched_at = datetime.now(UTC)
                session.commit()
