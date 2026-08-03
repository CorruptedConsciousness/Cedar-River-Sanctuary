PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    provider TEXT,
    endpoint TEXT,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS environmental_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    observed_at_utc TEXT NOT NULL,
    retrieved_at_utc TEXT NOT NULL,

    temperature_f REAL,
    humidity_percent REAL,
    pressure_hpa REAL,
    wind_speed_mph REAL,
    wind_direction_degrees REAL,
    precipitation_inches REAL,

    aqi INTEGER,
    pm25 REAL,
    ozone_ppb REAL,

    weather_description TEXT,
    quality_flag TEXT,
    raw_payload TEXT,

    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid TEXT NOT NULL UNIQUE,

    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,

    animal_class TEXT NOT NULL,
    probable_species TEXT,
    confidence REAL,

    individual_count INTEGER NOT NULL DEFAULT 1,
    camera_id TEXT,
    observation_zone TEXT,

    screenshot_path TEXT,
    model_name TEXT,
    model_version TEXT,

    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observation_environment (
    observation_id INTEGER NOT NULL,
    environmental_reading_id INTEGER NOT NULL,
    time_difference_seconds INTEGER,

    PRIMARY KEY (
        observation_id,
        environmental_reading_id
    ),

    FOREIGN KEY (observation_id)
        REFERENCES observations(id)
        ON DELETE CASCADE,

    FOREIGN KEY (environmental_reading_id)
        REFERENCES environmental_readings(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_status (
    service_name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    last_heartbeat_utc TEXT NOT NULL,
    message TEXT
);

CREATE TABLE IF NOT EXISTS archive_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start_utc TEXT NOT NULL,
    period_end_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',

    export_path TEXT,
    record_count INTEGER,
    image_count INTEGER,

    zenodo_deposit_id TEXT,
    zenodo_doi TEXT,

    created_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_environment_observed_at
ON environmental_readings(observed_at_utc);

CREATE INDEX IF NOT EXISTS idx_observations_started_at
ON observations(started_at_utc);

CREATE INDEX IF NOT EXISTS idx_observations_species
ON observations(probable_species);

CREATE INDEX IF NOT EXISTS idx_archive_jobs_status
ON archive_jobs(status);