"""
Cedar River Sanctuary
National Weather Service data worker

Downloads:
- NWS 7-day forecast
- NWS hourly forecast
- Active weather alerts

Stores the results in sanctuary.db.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "sanctuary.db"

# Replace these with the sanctuary's actual coordinates.
LATITUDE = 43.9800
LONGITUDE = -84.4900

# NWS asks API users to identify their application.
USER_AGENT = (
    "CedarRiverSanctuary/0.1 "
    "(cedarriversanctuary.org; wildlife and environmental monitoring)"
)

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

NWS_POINTS_URL = (
    f"https://api.weather.gov/points/{LATITUDE:.4f},{LONGITUDE:.4f}"
)

LOG_PATH = BASE_DIR / "nws_worker.log"


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

logger = logging.getLogger("nws_worker")


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def json_text(value: Any) -> str | None:
    """Convert lists or dictionaries to JSON text for SQLite."""
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False)


def get_json(url: str) -> dict[str, Any]:
    """
    Download JSON from the NWS API.

    Retries temporary network and server errors.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json",
    }

    request = urllib.request.Request(url, headers=headers)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Requesting %s", url)

            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read().decode(charset)
                return json.loads(body)

        except urllib.error.HTTPError as error:
            logger.error(
                "NWS returned HTTP %s for %s",
                error.code,
                url,
            )

            # Retry server-side failures, but not ordinary bad requests.
            if error.code < 500 or attempt == MAX_RETRIES:
                raise

        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as error:
            logger.error(
                "Request attempt %s of %s failed: %s",
                attempt,
                MAX_RETRIES,
                error,
            )

            if attempt == MAX_RETRIES:
                raise

        sleep_seconds = attempt * 3
        logger.info("Retrying in %s seconds", sleep_seconds)
        time.sleep(sleep_seconds)

    raise RuntimeError("NWS request failed unexpectedly.")


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def connect_database() -> sqlite3.Connection:
    """Open the sanctuary SQLite database."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def create_tables(connection: sqlite3.Connection) -> None:
    """Create the NWS tables without altering existing sanctuary tables."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS nws_location (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            grid_office TEXT,
            grid_x INTEGER,
            grid_y INTEGER,
            forecast_url TEXT,
            hourly_forecast_url TEXT,
            forecast_zone_url TEXT,
            county_url TEXT,
            time_zone TEXT,
            city TEXT,
            state TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS nws_forecast_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            forecast_type TEXT NOT NULL
                CHECK (forecast_type IN ('daily', 'hourly')),
            period_number INTEGER,
            period_name TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            is_daytime INTEGER,
            temperature REAL,
            temperature_unit TEXT,
            temperature_trend TEXT,
            probability_of_precipitation REAL,
            dewpoint_value REAL,
            dewpoint_unit TEXT,
            relative_humidity REAL,
            wind_speed TEXT,
            wind_direction TEXT,
            icon_url TEXT,
            short_forecast TEXT,
            detailed_forecast TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(forecast_type, start_time)
        );

        CREATE INDEX IF NOT EXISTS idx_nws_forecast_start_time
            ON nws_forecast_periods(start_time);

        CREATE INDEX IF NOT EXISTS idx_nws_forecast_type
            ON nws_forecast_periods(forecast_type);

        CREATE TABLE IF NOT EXISTS nws_alerts (
            alert_id TEXT PRIMARY KEY,
            area_description TEXT,
            sent_time TEXT,
            effective_time TEXT,
            onset_time TEXT,
            expires_time TEXT,
            ends_time TEXT,
            status TEXT,
            message_type TEXT,
            category TEXT,
            severity TEXT,
            certainty TEXT,
            urgency TEXT,
            event TEXT,
            sender_name TEXT,
            headline TEXT,
            description TEXT,
            instruction TEXT,
            response TEXT,
            affected_zones_json TEXT,
            parameters_json TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            fetched_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_nws_alerts_active
            ON nws_alerts(active);

        CREATE INDEX IF NOT EXISTS idx_nws_alerts_expires
            ON nws_alerts(expires_time);

        CREATE TABLE IF NOT EXISTS nws_worker_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            daily_periods INTEGER DEFAULT 0,
            hourly_periods INTEGER DEFAULT 0,
            active_alerts INTEGER DEFAULT 0,
            error_message TEXT
        );
        """
    )

    connection.commit()


# ---------------------------------------------------------------------------
# NWS location discovery
# ---------------------------------------------------------------------------

def update_location(
    connection: sqlite3.Connection,
    point_data: dict[str, Any],
) -> dict[str, Any]:
    """Save NWS grid and endpoint information for the sanctuary."""

    properties = point_data["properties"]
    relative_location = properties.get("relativeLocation", {})
    location_properties = relative_location.get("properties", {})

    location = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "grid_office": properties.get("gridId"),
        "grid_x": properties.get("gridX"),
        "grid_y": properties.get("gridY"),
        "forecast_url": properties.get("forecast"),
        "hourly_forecast_url": properties.get("forecastHourly"),
        "forecast_zone_url": properties.get("forecastZone"),
        "county_url": properties.get("county"),
        "time_zone": properties.get("timeZone"),
        "city": location_properties.get("city"),
        "state": location_properties.get("state"),
        "updated_at": utc_now(),
    }

    connection.execute(
        """
        INSERT INTO nws_location (
            id,
            latitude,
            longitude,
            grid_office,
            grid_x,
            grid_y,
            forecast_url,
            hourly_forecast_url,
            forecast_zone_url,
            county_url,
            time_zone,
            city,
            state,
            updated_at
        )
        VALUES (
            1, :latitude, :longitude, :grid_office, :grid_x, :grid_y,
            :forecast_url, :hourly_forecast_url, :forecast_zone_url,
            :county_url, :time_zone, :city, :state, :updated_at
        )
        ON CONFLICT(id) DO UPDATE SET
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            grid_office = excluded.grid_office,
            grid_x = excluded.grid_x,
            grid_y = excluded.grid_y,
            forecast_url = excluded.forecast_url,
            hourly_forecast_url = excluded.hourly_forecast_url,
            forecast_zone_url = excluded.forecast_zone_url,
            county_url = excluded.county_url,
            time_zone = excluded.time_zone,
            city = excluded.city,
            state = excluded.state,
            updated_at = excluded.updated_at
        """,
        location,
    )

    connection.commit()
    return location


# ---------------------------------------------------------------------------
# Forecast handling
# ---------------------------------------------------------------------------

def measurement_value(
    measurement: dict[str, Any] | None,
) -> tuple[float | None, str | None]:
    """Extract a value and unit code from an NWS measurement object."""

    if not measurement:
        return None, None

    return measurement.get("value"), measurement.get("unitCode")


def save_forecast(
    connection: sqlite3.Connection,
    forecast_data: dict[str, Any],
    forecast_type: str,
) -> int:
    """Replace the stored daily or hourly forecast."""

    periods = forecast_data.get("properties", {}).get("periods", [])
    fetched_at = utc_now()

    connection.execute(
        "DELETE FROM nws_forecast_periods WHERE forecast_type = ?",
        (forecast_type,),
    )

    for period in periods:
        precipitation = period.get("probabilityOfPrecipitation") or {}
        humidity = period.get("relativeHumidity") or {}

        dewpoint_value, dewpoint_unit = measurement_value(
            period.get("dewpoint")
        )

        connection.execute(
            """
            INSERT INTO nws_forecast_periods (
                forecast_type,
                period_number,
                period_name,
                start_time,
                end_time,
                is_daytime,
                temperature,
                temperature_unit,
                temperature_trend,
                probability_of_precipitation,
                dewpoint_value,
                dewpoint_unit,
                relative_humidity,
                wind_speed,
                wind_direction,
                icon_url,
                short_forecast,
                detailed_forecast,
                fetched_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                forecast_type,
                period.get("number"),
                period.get("name"),
                period.get("startTime"),
                period.get("endTime"),
                int(period.get("isDaytime", False)),
                period.get("temperature"),
                period.get("temperatureUnit"),
                period.get("temperatureTrend"),
                precipitation.get("value"),
                dewpoint_value,
                dewpoint_unit,
                humidity.get("value"),
                period.get("windSpeed"),
                period.get("windDirection"),
                period.get("icon"),
                period.get("shortForecast"),
                period.get("detailedForecast"),
                fetched_at,
            ),
        )

    connection.commit()
    return len(periods)


# ---------------------------------------------------------------------------
# Alert handling
# ---------------------------------------------------------------------------

def build_alerts_url() -> str:
    """Build the active-alert request for the sanctuary coordinates."""

    point = f"{LATITUDE:.4f},{LONGITUDE:.4f}"

    return (
        "https://api.weather.gov/alerts/active?"
        + urllib.parse.urlencode({"point": point})
    )


def save_alerts(
    connection: sqlite3.Connection,
    alert_data: dict[str, Any],
) -> int:
    """Save active NWS alerts and mark old alerts inactive."""

    features = alert_data.get("features", [])
    fetched_at = utc_now()

    # Existing alerts become inactive unless returned again below.
    connection.execute("UPDATE nws_alerts SET active = 0")

    for feature in features:
        properties = feature.get("properties", {})
        alert_id = feature.get("id") or properties.get("id")

        if not alert_id:
            logger.warning("Skipping an alert with no ID")
            continue

        connection.execute(
            """
            INSERT INTO nws_alerts (
                alert_id,
                area_description,
                sent_time,
                effective_time,
                onset_time,
                expires_time,
                ends_time,
                status,
                message_type,
                category,
                severity,
                certainty,
                urgency,
                event,
                sender_name,
                headline,
                description,
                instruction,
                response,
                affected_zones_json,
                parameters_json,
                active,
                fetched_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, 1, ?
            )
            ON CONFLICT(alert_id) DO UPDATE SET
                area_description = excluded.area_description,
                sent_time = excluded.sent_time,
                effective_time = excluded.effective_time,
                onset_time = excluded.onset_time,
                expires_time = excluded.expires_time,
                ends_time = excluded.ends_time,
                status = excluded.status,
                message_type = excluded.message_type,
                category = excluded.category,
                severity = excluded.severity,
                certainty = excluded.certainty,
                urgency = excluded.urgency,
                event = excluded.event,
                sender_name = excluded.sender_name,
                headline = excluded.headline,
                description = excluded.description,
                instruction = excluded.instruction,
                response = excluded.response,
                affected_zones_json = excluded.affected_zones_json,
                parameters_json = excluded.parameters_json,
                active = 1,
                fetched_at = excluded.fetched_at
            """,
            (
                alert_id,
                properties.get("areaDesc"),
                properties.get("sent"),
                properties.get("effective"),
                properties.get("onset"),
                properties.get("expires"),
                properties.get("ends"),
                properties.get("status"),
                properties.get("messageType"),
                properties.get("category"),
                properties.get("severity"),
                properties.get("certainty"),
                properties.get("urgency"),
                properties.get("event"),
                properties.get("senderName"),
                properties.get("headline"),
                properties.get("description"),
                properties.get("instruction"),
                properties.get("response"),
                json_text(properties.get("affectedZones")),
                json_text(properties.get("parameters")),
                fetched_at,
            ),
        )

    connection.commit()
    return len(features)


# ---------------------------------------------------------------------------
# Worker run tracking
# ---------------------------------------------------------------------------

def begin_worker_run(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        """
        INSERT INTO nws_worker_runs (started_at, status)
        VALUES (?, 'running')
        """,
        (utc_now(),),
    )

    connection.commit()
    return int(cursor.lastrowid)


def complete_worker_run(
    connection: sqlite3.Connection,
    run_id: int,
    daily_periods: int,
    hourly_periods: int,
    active_alerts: int,
) -> None:
    connection.execute(
        """
        UPDATE nws_worker_runs
        SET completed_at = ?,
            status = 'success',
            daily_periods = ?,
            hourly_periods = ?,
            active_alerts = ?
        WHERE id = ?
        """,
        (
            utc_now(),
            daily_periods,
            hourly_periods,
            active_alerts,
            run_id,
        ),
    )

    connection.commit()


def fail_worker_run(
    connection: sqlite3.Connection,
    run_id: int,
    error: Exception,
) -> None:
    connection.execute(
        """
        UPDATE nws_worker_runs
        SET completed_at = ?,
            status = 'error',
            error_message = ?
        WHERE id = ?
        """,
        (
            utc_now(),
            str(error),
            run_id,
        ),
    )

    connection.commit()


# ---------------------------------------------------------------------------
# Main worker
# ---------------------------------------------------------------------------

def run_worker() -> None:
    logger.info("Starting Cedar River Sanctuary NWS worker")
    logger.info("Database: %s", DATABASE_PATH)

    with connect_database() as connection:
        create_tables(connection)
        run_id = begin_worker_run(connection)

        try:
            # Discover the appropriate NWS grid and forecast URLs.
            point_data = get_json(NWS_POINTS_URL)
            location = update_location(connection, point_data)

            logger.info(
                "NWS grid: %s %s,%s",
                location["grid_office"],
                location["grid_x"],
                location["grid_y"],
            )

            if not location["forecast_url"]:
                raise RuntimeError("NWS did not provide a forecast URL.")

            if not location["hourly_forecast_url"]:
                raise RuntimeError(
                    "NWS did not provide an hourly forecast URL."
                )

            # Download and store forecasts.
            daily_data = get_json(location["forecast_url"])
            daily_count = save_forecast(
                connection,
                daily_data,
                "daily",
            )

            hourly_data = get_json(location["hourly_forecast_url"])
            hourly_count = save_forecast(
                connection,
                hourly_data,
                "hourly",
            )

            # Download and store active alerts.
            alerts_data = get_json(build_alerts_url())
            alert_count = save_alerts(connection, alerts_data)

            complete_worker_run(
                connection,
                run_id,
                daily_count,
                hourly_count,
                alert_count,
            )

            logger.info(
                "NWS update complete: %s daily periods, "
                "%s hourly periods, %s active alerts",
                daily_count,
                hourly_count,
                alert_count,
            )

        except Exception as error:
            fail_worker_run(connection, run_id, error)
            logger.exception("NWS worker failed")
            raise


if __name__ == "__main__":
    run_worker()