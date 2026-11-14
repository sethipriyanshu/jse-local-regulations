"""Background worker entry point. Deployed as an Azure Container Apps Job on a
daily cron; run locally with:

    uv run python -m app.worker daily               # monitor sources, post the Teams digest
    uv run python -m app.worker discover [FIPS ...]  # AI discovery (default: all pilots)
"""

import argparse
import logging
import sys
import traceback

from sqlalchemy.orm import Session

from app import discovery, teams
from app.db import get_engine
from app.models import JobStatus
from app.monitor import DailyResult, run_daily

log = logging.getLogger("worker")


def daily(session: Session, post: teams.PostFn = teams.post_card) -> DailyResult:
    """Run the monitor, then post the digest (or a failure alert) to Teams."""
    try:
        result = run_daily(session)
    except Exception:
        session.rollback()
        teams.send(session, "alert",
                   lambda _t: teams.alert_card("daily_monitor", traceback.format_exc()), post)
        raise
    if result.run.status == JobStatus.FAILED:
        detail = "\n".join(e["error"] for e in (result.run.errors or [])[:5])
        teams.send(session, "alert", lambda _t: teams.alert_card(
            "daily_monitor", f"Every source failed. First errors:\n{detail}"), post)
    teams.send(session, "digest", lambda t: teams.digest_card(
        session, result.run, result.events, result.unhealthy, metro=t.metro), post)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.worker")
    parser.add_argument("command", choices=["daily", "discover"])
    parser.add_argument("fips", nargs="*", help="discover: jurisdictions (default: all pilots)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    with Session(get_engine()) as session:
        if args.command == "daily":
            run = daily(session).run
            log.info("daily_monitor run %s: %s, %s sources, %s changes", run.id, run.status,
                     run.sources_checked, run.changes_found)
            return 0 if run.status == JobStatus.SUCCEEDED else 1
        fips = args.fips or [j.fips for j in discovery.pilot_targets(session)]
        job = discovery.run_job(session, discovery.start_job(session, fips))
        log.info("discovery run %s: %s, %s candidates added", job.id, job.status,
                 job.changes_found)
        return 0 if job.status == JobStatus.SUCCEEDED else 1


if __name__ == "__main__":
    sys.exit(main())
