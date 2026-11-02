"""Background worker entry point. Deployed as an Azure Container Apps Job on a
daily cron; run locally with `uv run python -m app.worker daily`.

The daily pipeline (fetch → diff → triage → Teams digest) lands in week 7. For now
the command records a job run so scheduling and monitoring can be wired up early.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import JobRun, JobStatus

log = logging.getLogger("worker")


def run_daily(session: Session) -> JobRun:
    run = JobRun(job="daily_monitor", status=JobStatus.RUNNING)
    session.add(run)
    session.commit()
    try:
        # Pipeline stages are added here as they are built.
        run.status = JobStatus.SUCCEEDED
    except Exception as exc:
        run.status = JobStatus.FAILED
        run.errors = [repr(exc)]
        raise
    finally:
        run.finished_at = datetime.now(UTC)
        session.commit()
    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.worker")
    parser.add_argument("command", choices=["daily"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    with Session(get_engine()) as session:
        if args.command == "daily":
            run = run_daily(session)
            log.info("daily_monitor run %s: %s", run.id, run.status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
