"""
Cedar River Sanctuary
Website data worker

Reads weather information from sanctuary.db and creates a JSON file
that the public website can load.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "sanctuary.db"

DATA_DIR = BASE_DIR / "data"
WEATHER_JSON_PATH = DATA_DIR / "weather.json"

LOG_PATH = BASE_DIR / "website_worker.log"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)

logger = logging.getLogger("website_worker")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def connect_database() -> sqlite3.Connection:
    """Open the sanctuary database."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a SQLite row into a normal dictionary."""
    return dict(row)


# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------

def get_location(
    connection: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get the sanctuary's NWS grid information."""

    row = connection.execute(
        """
        SELECT
            latitude,
            longitude,
            grid_office,
            grid_x,
            grid_y,
            time_zone,
            city,
            state,
            updated_at
        FROM nws_location
        WHERE id = 1
        """
    ).fetchone()

    return row_to_dict(row) if row else None


def get_daily_forecast(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Get all currently stored daily forecast periods."""

    rows = connection.execute(
        """
        SELECT
            period_number,
            period_name,
            start_time,
            end_time,
            is_daytime,
            temperature,
            temperature_unit,
            probability_of_precipitation,
            relative_humidity,
            wind_speed,
            wind_direction,
            icon_url,
            short_forecast,
            detailed_forecast,
            fetched_at
        FROM nws_forecast_periods
        WHERE forecast_type = 'daily'
        ORDER BY start_time ASC
        """
    ).fetchall()

    return [row_to_dict(row) for row in rows]


def get_hourly_forecast(
    connection: sqlite3.Connection,
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Get the next several hourly forecast periods."""

    rows = connection.execute(
        """
        SELECT
            period_number,
            period_name,
            start_time,
            end_time,
            temperature,
            temperature_unit,
            probability_of_precipitation,
            relative_humidity,
            wind_speed,
            wind_direction,
            icon_url,
            short_forecast,
            fetched_at
        FROM nws_forecast_periods
        WHERE forecast_type = 'hourly'
        ORDER BY start_time ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    return [row_to_dict(row) for row in rows]


def get_active_alerts(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Get active NWS alerts."""

    rows = connection.execute(
        """
        SELECT
            alert_id,
            area_description,
            sent_time,
            effective_time,
            onset_time,
            expires_time,
            ends_time,
            severity,
            certainty,
            urgency,
            event,
            sender_name,
            headline,
            description,
            instruction,
            response,
            fetched_at
        FROM nws_alerts
        WHERE active = 1
        ORDER BY effective_time DESC
        """
    ).fetchall()

    return [row_to_dict(row) for row in rows]


def get_last_nws_run(
    connection: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get information about the most recent NWS worker run."""

    row = connection.execute(
        """
        SELECT
            started_at,
            completed_at,
            status,
            daily_periods,
            hourly_periods,
            active_alerts,
            error_message
        FROM nws_worker_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    return row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# JSON generation
# ---------------------------------------------------------------------------

def build_weather_document(
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    """Build the complete public weather document."""

    daily = get_daily_forecast(connection)
    hourly = get_hourly_forecast(connection)
    alerts = get_active_alerts(connection)

    current_forecast = hourly[0] if hourly else None

    return {
        "project": "Cedar River Sanctuary",
        "generated_at": utc_now(),
        "source": {
            "name": "National Weather Service",
            "website": "https://www.weather.gov/",
        },
        "location": get_location(connection),
        "current_forecast": current_forecast,
        "daily_forecast": daily,
        "hourly_forecast": hourly,
        "active_alerts": alerts,
        "alert_count": len(alerts),
        "last_nws_worker_run": get_last_nws_run(connection),
    }


def write_weather_json(document: dict[str, Any]) -> None:
    """Write weather data to the public website data folder."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temporary_path = WEATHER_JSON_PATH.with_suffix(".json.tmp")

    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(
            document,
            file,
            indent=2,
            ensure_ascii=False,
        )

    # Replace the old file only after the new file is completely written.
    temporary_path.replace(WEATHER_JSON_PATH)


# ---------------------------------------------------------------------------
# Main worker
# ---------------------------------------------------------------------------

def run_worker() -> None:
    logger.info("Starting Cedar River Sanctuary website worker")
    logger.info("Database: %s", DATABASE_PATH)
    logger.info("Output: %s", WEATHER_JSON_PATH)

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database does not exist: {DATABASE_PATH}"
        )

    with connect_database() as connection:
        document = build_weather_document(connection)

    write_weather_json(document)

    logger.info(
        "Website weather data complete: "
        "%s daily periods, %s hourly periods, %s active alerts",
        len(document["daily_forecast"]),
        len(document["hourly_forecast"]),
        document["alert_count"],
    )


if __name__ == "__main__":
    run_worker()