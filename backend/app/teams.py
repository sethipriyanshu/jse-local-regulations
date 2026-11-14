"""Microsoft Teams notifications through Workflows webhooks (PLAN.md G1–G4).

A Teams channel gets a webhook URL from the Workflows app ("Post to a channel when a
webhook request is received"). We POST an Adaptive Card to it. Webhook URLs are
secrets: they are stored in teams_channels (or TEAMS_WEBHOOK_URL) and never returned
in full by the API."""

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AiRun,
    ChangeEvent,
    JobRun,
    Jurisdiction,
    Rule,
    RuleStatus,
    Source,
    SourceStatus,
    TeamsChannel,
)

log = logging.getLogger(__name__)

# Hosts Teams Workflows webhooks live on. Anything else is refused, so the server can't
# be pointed at arbitrary URLs.
WEBHOOK_HOST_SUFFIXES = (".logic.azure.com", ".api.powerplatform.com", ".webhook.office.com")


class InvalidWebhook(ValueError):
    pass


def validate_webhook_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host.endswith(WEBHOOK_HOST_SUFFIXES):
        raise InvalidWebhook(
            "Use the HTTPS webhook URL from the Teams Workflows app "
            "(it ends in logic.azure.com or api.powerplatform.com)."
        )
    return url


def mask_webhook(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}/…{url[-6:]}"


@dataclass
class Target:
    name: str
    url: str
    metro: str | None


def targets(session: Session, kind: str) -> list[Target]:
    """Channels for "digest", "alert" or "submission" posts. The env webhook gets
    everything; submissions go to alert channels."""
    flag = TeamsChannel.sends_digest if kind == "digest" else TeamsChannel.sends_alerts
    out = [Target(c.name, c.webhook_url, c.metro)
           for c in session.scalars(select(TeamsChannel).where(flag == true()))]
    env_url = get_settings().teams_webhook_url
    if env_url:
        out.append(Target("default", env_url, None))
    return out


PostFn = Callable[[str, dict[str, Any]], None]


def describe_error(exc: Exception) -> str:
    """Error text without the webhook URL (httpx messages include it)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, InvalidWebhook):
        return str(exc)
    return type(exc).__name__


def post_card(url: str, card: dict[str, Any]) -> None:
    payload = {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": card,
    }]}
    res = httpx.post(validate_webhook_url(url), json=payload, timeout=20)
    res.raise_for_status()


def _card(title: str, body: list[dict[str, Any]], actions: list[tuple[str, str]],
          style: str = "default") -> dict[str, Any]:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard", "version": "1.4", "msteams": {"width": "Full"},
        "body": [
            {"type": "Container", "style": style, "bleed": True, "items": [
                {"type": "TextBlock", "text": "JSE Local Regulations", "size": "Small",
                 "weight": "Bolder", "color": "Attention" if style == "attention" else "Accent"},
                {"type": "TextBlock", "text": title, "size": "Large", "weight": "Bolder",
                 "wrap": True},
            ]},
            *body,
        ],
        "actions": [{"type": "Action.OpenUrl", "title": t, "url": u} for t, u in actions],
    }


def _link(path: str) -> str:
    return get_settings().public_base_url.rstrip("/") + path


def digest_card(
    session: Session, run: JobRun, events: list[ChangeEvent], unhealthy: list[Source],
    metro: str | None = None,
) -> dict[str, Any] | None:
    """The daily digest. Returns None for a metro channel with nothing to report."""
    jur_ids = {s.jurisdiction_id for s in unhealthy}
    srcs = {s.id: s for s in session.scalars(
        select(Source).where(Source.id.in_({e.source_id for e in events})))}
    jur_ids |= {s.jurisdiction_id for s in srcs.values()}
    jurs = {j.id: j for j in session.scalars(
        select(Jurisdiction).where(Jurisdiction.id.in_(jur_ids)))}

    def in_metro(jurisdiction_id: int) -> bool:
        return metro is None or jurs[jurisdiction_id].pilot_metro == metro

    relevant = [e for e in events if e.mep_relevant is not False
                and in_metro(srcs[e.source_id].jurisdiction_id)]
    broken = [s for s in unhealthy if in_metro(s.jurisdiction_id)]
    if metro is not None and not relevant and not broken:
        return None

    pending_rules = session.scalar(select(func.count()).select_from(Rule)
                                   .where(Rule.status == RuleStatus.PENDING)) or 0
    pending_sources = session.scalar(select(func.count()).select_from(Source)
                                     .where(Source.status == SourceStatus.SUBMITTED)) or 0
    spend = session.scalar(select(func.coalesce(func.sum(AiRun.cost_usd), 0.0))
                           .where(AiRun.created_at >= run.started_at)) or 0.0

    facts = [
        {"title": "Sources checked", "value": str(run.sources_checked)},
        {"title": "MEP-relevant changes", "value": str(len(relevant))},
        {"title": "Broken or blocked sources", "value": str(len(broken))},
        {"title": "Waiting for review",
         "value": f"{pending_rules} rules · {pending_sources} sources"},
        {"title": "AI spend today", "value": f"${spend:.2f}"},
    ]
    body: list[dict[str, Any]] = [{"type": "FactSet", "facts": facts}]
    if relevant:
        body.append({"type": "TextBlock", "text": "Changes", "weight": "Bolder",
                     "spacing": "Medium"})
        by_jur = Counter(jurs[srcs[e.source_id].jurisdiction_id].name for e in relevant)
        for e in relevant[:8]:
            j = jurs[srcs[e.source_id].jurisdiction_id]
            summary = e.ai_summary or "Page changed."
            body.append({"type": "TextBlock", "wrap": True, "spacing": "Small",
                         "text": f"**{j.name}, {j.state_code}**: {summary}"})
        if len(relevant) > 8:
            rest = ", ".join(f"{n} ({c})" for n, c in by_jur.most_common())
            body.append({"type": "TextBlock", "wrap": True, "isSubtle": True,
                         "text": f"…and {len(relevant) - 8} more. By place: {rest}"})
    if broken:
        body.append({"type": "TextBlock", "text": "Sources needing attention",
                     "weight": "Bolder", "spacing": "Medium"})
        for s in broken[:6]:
            j = jurs[s.jurisdiction_id]
            body.append({"type": "TextBlock", "wrap": True, "spacing": "Small",
                         "text": f"{j.name}: {s.title or s.domain} ({s.health.value})"})
    if run.errors:
        body.append({"type": "TextBlock", "wrap": True, "color": "Warning",
                     "text": f"{len(run.errors)} source(s) failed with an error during the run."})

    title = "Daily regulations digest" + (f" · {metro.upper()}" if metro else "")
    return _card(title, body, [("Open review queue", _link("/admin")),
                               ("Open map", _link("/"))])


def alert_card(job: str, error: str) -> dict[str, Any]:
    return _card(f"The {job.replace('_', ' ')} job failed", [
        {"type": "TextBlock", "wrap": True, "text": error[:1500], "fontType": "Monospace"},
        {"type": "TextBlock", "wrap": True, "isSubtle": True,
         "text": "Check the job logs in Azure (Container Apps Job executions)."},
    ], [("Open admin", _link("/admin?tab=health"))], style="attention")


def submission_card(source: Source, jurisdiction: Jurisdiction) -> dict[str, Any]:
    who = source.submitted_by_name or "Someone"
    what = source.title if source.url.startswith("upload://") else source.url
    return _card(f"New source suggested for {jurisdiction.name}, {jurisdiction.state_code}", [
        {"type": "TextBlock", "wrap": True, "text": f"{who} suggested: {what}"},
        *([{"type": "TextBlock", "wrap": True, "isSubtle": True, "text": source.note}]
          if source.note else []),
    ], [("Review", _link("/admin"))])


def test_card(channel_name: str) -> dict[str, Any]:
    return _card("Test message", [{"type": "TextBlock", "wrap": True,
                  "text": f"Channel “{channel_name}” is connected. Daily digests and alerts "
                          "will arrive here."}], [("Open the app", _link("/"))])


def send(session: Session, kind: str, build: Callable[[Target], dict[str, Any] | None],
         post: PostFn = post_card) -> int:
    """Post to every target of a kind; failures are logged, not raised. Returns posts sent."""
    sent = 0
    for t in targets(session, kind):
        card = build(t)
        if card is None:
            continue
        try:
            post(t.url, card)
            sent += 1
        except Exception as exc:
            log.warning("Teams post to %s failed: %s", t.name, describe_error(exc))
    return sent


def notify_submission(session_factory: Callable[[], Session], source_id: int,
                      post: PostFn = post_card) -> None:
    """Background task: tell alert channels that a user suggested a source (G4)."""
    with session_factory() as session:
        src = session.get(Source, source_id)
        jur = session.get(Jurisdiction, src.jurisdiction_id) if src else None
        if src is not None and jur is not None:
            send(session, "submission", lambda _t: submission_card(src, jur), post)
