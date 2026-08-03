from pathlib import Path
import sqlite3
from sqlite3 import Connection

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "sanctuary.db"


def get_connection() -> Connection:
    """
    Open a connection to the Cedar River Sanctuary database.

    Foreign-key enforcement is enabled for every connection.
    Rows can be accessed by column name.
    """
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def database_exists() -> bool:
    """Return True if the SQLite database file exists."""
    return DATABASE_PATH.exists()


def test_connection() -> None:
    """Confirm that the database can be opened successfully."""
    with get_connection() as connection:
        result = connection.execute(
            "SELECT sqlite_version() AS version;"
        ).fetchone()

    print("Database connection successful.")
    print(f"SQLite version: {result['version']}")
    print(f"Database path: {DATABASE_PATH}")


if __name__ == "__main__":
    test_connection()