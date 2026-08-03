from pathlib import Path
import sqlite3

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "sanctuary.db"
SCHEMA_PATH = PROJECT_ROOT / "database" / "schema.sql"


def initialize_database():
    """Create the Cedar River Sanctuary database."""

    DATA_DIR.mkdir(exist_ok=True)

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON;")

        with open(SCHEMA_PATH, "r", encoding="utf-8") as schema:
            connection.executescript(schema.read())

    print("Database created successfully!")
    print(f"Location: {DATABASE_PATH}")


if __name__ == "__main__":
    initialize_database()