import sqlite3
from config.settings import FACES_DB, ATTENDANCE_DB

def setup_databases():
    # Setup Faces Database
    with sqlite3.connect(FACES_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_embeddings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                person_name   TEXT,
                embedding     BLOB,
                device_id     TEXT,
                registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                synced        INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS faces_version (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                version    INTEGER DEFAULT 0,
                updated_at TEXT    DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("INSERT OR IGNORE INTO faces_version (id, version) VALUES (1, 0)")
        conn.commit()

    # Setup Attendance Database
    with sqlite3.connect(ATTENDANCE_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance_logs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                person_name   TEXT,
                timestamp     TEXT,
                synced        INTEGER DEFAULT 0,
                device_id     TEXT
            )
        """)
        conn.commit()

if __name__ == "__main__":
    setup_databases()
