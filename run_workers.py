"""
Cedar River Sanctuary
Scheduled worker runner

Runs data workers in the correct order:

1. Download current NWS information into sanctuary.db
2. Export the latest database information into data/weather.json
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "scheduler.log"

WORKERS = [
    "nws_worker.py",
    "website_worker.py",
]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)

logger = logging.getLogger("scheduler")


def utc_now() -> str:
    """Return the current UTC time."""
    return datetime.now(timezone.utc).isoformat()


def run_worker(filename: str) -> None:
    """Run one worker and stop if it fails."""

    worker_path = BASE_DIR / filename

    if not worker_path.exists():
        raise FileNotFoundError(f"Worker not found: {worker_path}")

    logger.info("Starting worker: %s", filename)

    result = subprocess.run(
        [sys.executable, str(worker_path)],
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.stdout.strip():
        logger.info(
            "%s output:\n%s",
            filename,
            result.stdout.strip(),
        )

    if result.stderr.strip():
        logger.warning(
            "%s error output:\n%s",
            filename,
            result.stderr.strip(),
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"{filename} failed with exit code {result.returncode}"
        )

    logger.info("Worker completed successfully: %s", filename)


def run_all_workers() -> None:
    """Run every sanctuary worker in sequence."""

    started_at = utc_now()

    logger.info("=" * 60)
    logger.info("Cedar River Sanctuary scheduled update started")
    logger.info("Started at: %s", started_at)

    completed = 0

    try:
        for worker in WORKERS:
            run_worker(worker)
            completed += 1

    except Exception:
        logger.exception(
            "Scheduled update failed after %s of %s workers",
            completed,
            len(WORKERS),
        )
        raise

    logger.info(
        "Scheduled update completed: %s of %s workers successful",
        completed,
        len(WORKERS),
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    run_all_workers()