"""AI source discovery (PLAN.md E1–E4): web search for official pages, verify each
candidate by fetching it, and file the good ones as AI-suggested sources in the admin
queue. Nothing is monitored until an admin approves it."""

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app import fetcher
from app.config import Settings, get_settings
from app.fetcher import FetchResult
from app.llm import LLMNotConfigured
from app.models import (
    AiRun,
    JobRun,
    JobStatus,
    Jurisdiction,
    JurisdictionType,
    Origin,
    Source,
    SourceHealth,
    SourceStatus,
)
from app.urls import (
    UnsafeUrl,
    assert_public,
    domain_of,
    is_official_domain,
    normalize_url,
    url_hash,
)

log = logging.getLogger(__name__)

PROMPT_VERSION = "discover_v1"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()
MAX_CANDIDATES = 8
OFFICIAL_BOOST = 0.15

SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["candidates"],
    "properties": {"candidates": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["url", "title", "reason", "kind", "relevance"],
        "properties": {
            "url": {"type": "string"}, "title": {"type": "string"},
            "reason": {"type": "string"},
            "kind": {"type": "string", "enum": ["government", "code_library", "other"]},
            "relevance": {"type": "number"},
        },
    }}},
}


@dataclass
class Candidate:
    url: str
    title: str
    reason: str
    kind: str
    relevance: float


class Searcher(Protocol):
    def search(self, session: Session, jurisdiction: Jurisdiction) -> list[Candidate]: ...


class AzureWebSearch:
    """Azure OpenAI Responses API with the built-in web_search tool. The tool is rate
    limited per resource, so 429s are retried with backoff."""

    name = "azure-openai-web"

    def __init__(self, settings: Settings | None = None, retries: int = 4,
                 backoff_s: float = 30.0) -> None:
        from openai import OpenAI

        s = settings or get_settings()
        if not (s.azure_openai_endpoint and s.azure_openai_api_key and s.azure_openai_deployment):
            raise LLMNotConfigured("Set AZURE_OPENAI_ENDPOINT, _API_KEY and _DEPLOYMENT")
        self.settings = s
        self.retries = retries
        self.backoff_s = backoff_s
        self.client = OpenAI(base_url=s.azure_openai_endpoint.rstrip("/") + "/openai/v1/",
                             api_key=s.azure_openai_api_key, max_retries=0, timeout=120)

    def search(self, session: Session, jurisdiction: Jurisdiction) -> list[Candidate]:
        from openai import RateLimitError

        label = jurisdiction_label(jurisdiction)
        for attempt in range(self.retries + 1):
            run = AiRun(kind="discover", provider=self.name,
                        model=self.settings.azure_openai_deployment,
                        prompt_version=PROMPT_VERSION, ref_type="jurisdiction",
                        ref_id=jurisdiction.id)
            start = time.monotonic()
            try:
                res = self.client.responses.create(
                    model=self.settings.azure_openai_deployment,
                    tools=[{"type": "web_search"}],
                    text={"format": {"type": "json_schema", "name": "candidates",
                                     "strict": True, "schema": SCHEMA}},
                    input=PROMPT.format(jurisdiction=label, limit=MAX_CANDIDATES,
                                        scope=scope_note(jurisdiction)),
                )
                usage = res.usage
                run.model = res.model or run.model
                run.input_tokens = usage.input_tokens if usage else 0
                run.output_tokens = usage.output_tokens if usage else 0
                searches = sum(1 for o in res.output if o.type == "web_search_call")
                run.cost_usd = round(
                    run.input_tokens / 1e6 * self.settings.llm_price_in_per_m
                    + run.output_tokens / 1e6 * self.settings.llm_price_out_per_m
                    + searches * self.settings.llm_web_search_price_per_call, 6)
                try:
                    data = json.loads(res.output_text or "")
                except json.JSONDecodeError:
                    # The model occasionally answers before searching; ask again.
                    run.ok = False
                    if attempt < self.retries:
                        continue
                    return []
                return [Candidate(c["url"], c["title"], c["reason"], c["kind"],
                                  max(0.0, min(1.0, float(c["relevance"]))))
                        for c in data.get("candidates", [])]
            except RateLimitError:
                run.ok = False
                if attempt >= self.retries:
                    raise
                time.sleep(self.backoff_s * 2**attempt)
            finally:
                run.latency_ms = int((time.monotonic() - start) * 1000)
                session.add(run)
                session.commit()
        return []


def get_searcher() -> Searcher:
    return AzureWebSearch()


def jurisdiction_label(j: Jurisdiction) -> str:
    if j.type == JurisdictionType.STATE:
        return f"State of {j.name} (state-level building code adoption)"
    if j.type == JurisdictionType.DISTRICT:
        return "Washington, District of Columbia (DC Department of Buildings)"
    # Census names already say "city" or "County" ("Tuscaloosa city", "Fulton County").
    suffix = " (consolidated city-county)" if j.type == JurisdictionType.CONSOLIDATED else ""
    return f"{j.name}, {j.state_code}{suffix}"


def scope_note(j: Jurisdiction) -> str:
    """Keep each layer's search to its own government; other layers have their own runs."""
    if j.type == JurisdictionType.STATE:
        return ("Only include pages published by the state government (for example the state "
                "building code council, fire marshal, or licensing board), not cities or counties.")
    if j.type == JurisdictionType.COUNTY:
        return ("Only include pages published by the county government itself. Leave out pages "
                "of the state government and of cities inside the county; they are tracked "
                "separately.")
    return ("Only include pages published by this city's own government. Leave out pages of the "
            "state government and of the county; they are tracked separately.")


# Code libraries host many pages per jurisdiction; one link per library is enough for review.
CODE_LIBRARY_HOSTS = ("municode.com", "amlegal.com", "ecode360.com", "codepublishing.com",
                      "codelibrary.amlegal.com", "library.municode.com")


def _library_host(domain: str) -> str | None:
    return next((h for h in CODE_LIBRARY_HOSTS if domain == h or domain.endswith("." + h)), None)


@dataclass
class DiscoveryResult:
    fips: str
    added: list[int] = field(default_factory=list)
    already_known: int = 0
    unreachable: int = 0
    unsafe: int = 0
    off_topic: int = 0


def discover(
    session: Session, j: Jurisdiction, *, searcher: Searcher | None = None,
    fetch_fn: Callable[[str], FetchResult] | None = None,
) -> DiscoveryResult:
    """Find candidate sources for one jurisdiction and add the reachable, new ones to
    the admin queue. Candidates whose URL is already a source here, in any status
    (including rejected), are skipped."""
    found = (searcher or get_searcher()).search(session, j)
    found.sort(key=lambda c: -c.relevance)
    result = DiscoveryResult(j.fips)
    # Any URL already filed anywhere (another layer often surfaces the same state page).
    known = set(session.scalars(select(Source.url_hash)))
    libraries_seen = {
        lib for d in session.scalars(select(Source.domain).where(Source.jurisdiction_id == j.id))
        if (lib := _library_host(d))
    }
    fetch = fetch_fn or fetcher.fetch

    for c in found[:MAX_CANDIDATES]:
        try:
            url = normalize_url(c.url)
            assert_public(url)
        except UnsafeUrl:
            result.unsafe += 1
            continue
        h = url_hash(url)
        if h in known:
            result.already_known += 1
            continue
        known.add(h)
        domain = domain_of(url)
        library = _library_host(domain)
        if c.kind == "other" and not is_official_domain(domain):
            result.off_topic += 1
            continue
        if library and library in libraries_seen:
            result.already_known += 1
            continue

        page = fetch(url)
        if page.health in (SourceHealth.NOT_FOUND, SourceHealth.ERROR):
            result.unreachable += 1
            continue
        if library:
            libraries_seen.add(library)
        official = is_official_domain(domain)
        reason = c.reason.strip()
        if page.health == SourceHealth.BLOCKED:
            reason += " (This site blocks automated reading; save the page as a PDF and upload it.)"
        src = Source(
            jurisdiction_id=j.id, url=url, url_hash=h, domain=domain,
            title=(page.title or c.title or "")[:512] or None,
            status=SourceStatus.SUBMITTED, origin=Origin.AI, health=page.health,
            discovery_reason=reason[:2000],
            discovery_score=round(min(1.0, c.relevance + (OFFICIAL_BOOST if official else 0)), 3),
        )
        session.add(src)
        session.flush()
        result.added.append(src.id)
    session.commit()
    log.info("discovery %s: %s", j.fips, result)
    return result


def pilot_targets(session: Session) -> list[Jurisdiction]:
    """Every pilot jurisdiction: states, counties, cities. States first, so the shared
    state layer is seeded before local layers."""
    rows = list(session.scalars(select(Jurisdiction).where(Jurisdiction.is_pilot == true())))
    return sorted(rows, key=lambda j: (len(j.fips), j.state_code, j.name))


def start_job(session: Session, fips: Sequence[str]) -> JobRun:
    run = JobRun(job="discovery", status=JobStatus.RUNNING, total=len(fips),
                 summary={"fips": list(fips), "added": 0})
    session.add(run)
    session.commit()
    return run


def run_job(
    session: Session, run: JobRun, *, searcher: Searcher | None = None,
    fetch_fn: Callable[[str], FetchResult] | None = None, interval_s: float | None = None,
) -> JobRun:
    """Run discovery for each FIPS in the job, recording progress on the job row."""
    fips_list: list[str] = list((run.summary or {}).get("fips", []))
    pause = get_settings().discovery_interval_s if interval_s is None else interval_s
    errors: list[dict[str, Any]] = []
    added = 0
    try:
        searcher = searcher or get_searcher()
        for i, fips in enumerate(fips_list):
            j = session.scalars(select(Jurisdiction).where(Jurisdiction.fips == fips)).first()
            if j is not None:
                try:
                    added += len(discover(session, j, searcher=searcher, fetch_fn=fetch_fn).added)
                except Exception as exc:
                    log.exception("discovery failed for %s", fips)
                    session.rollback()
                    errors.append({"fips": fips, "error": repr(exc)[:500]})
            run.done = i + 1
            run.changes_found = added
            run.summary = {**(run.summary or {}), "added": added}
            session.commit()
            if pause and i < len(fips_list) - 1:
                time.sleep(pause)
        run.status = (JobStatus.FAILED if fips_list and len(errors) == len(fips_list)
                      else JobStatus.SUCCEEDED)
    except Exception as exc:
        log.exception("discovery job %s failed", run.id)
        session.rollback()
        run.status = JobStatus.FAILED
        errors.append({"error": repr(exc)[:500]})
    run.errors = errors or None
    run.finished_at = datetime.now(UTC)
    session.commit()
    return run


def run_job_in_background(session_factory: Callable[[], Session], job_id: int) -> None:
    with session_factory() as session:
        run = session.get(JobRun, job_id)
        if run is not None:
            run_job(session, run)
