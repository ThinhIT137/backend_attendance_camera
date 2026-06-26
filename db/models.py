import sqlite3
from config.settings import FACES_DB, ATTENDANCE_DB, CAMERA_DB

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
    
    with sqlite3.connect(CAMERA_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_servers (
                server_id      TEXT PRIMARY KEY,       -- VD: 'SV_01', 'SV_02'
                ip_address     TEXT NOT NULL,          -- VD: 'http://10.40.1.11:5000'
                cpu_usage      REAL DEFAULT 0.0,       -- % CPU (số thực)
                has_gpu        BOOLEAN DEFAULT 0,      -- 0: Không, 1: Có
                vram_free_gb   REAL DEFAULT 0.0,       -- GB VRAM còn trống
                active_cam     INTEGER DEFAULT 0,      -- Đang gánh bao nhiêu cam
                status         TEXT DEFAULT 'offline', -- 'online' hoặc 'offline'
                last_heartbeat TEXT                    -- Thời gian ping cuối cùng
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cameras (
                cam_id         TEXT PRIMARY KEY,       -- VD: 'cam_46'
                name           TEXT,                   -- VD: 'Camera Cổng Chính'
                rtsp_url       TEXT NOT NULL,          -- Link gốc
                server_id      TEXT,                   -- Đang giao cho thằng SV nào? (Có thể NULL nếu chưa phân)
                status         TEXT DEFAULT 'stopped', -- 'running', 'stopped', 'error'
                is_recording   INTEGER DEFAULT 0, -- 0 là Không lưu, 1 là Đang lưu
                record_url     TEXT,              -- Nơi lưu trữ (VD: 'D:/records/cam_46/')
                FOREIGN KEY (server_id) REFERENCES ai_servers(server_id)
            );
        """)
        conn.commit()

if __name__ == "__main__":
    setup_databases()
