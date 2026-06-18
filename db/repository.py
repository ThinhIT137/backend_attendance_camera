import sqlite3
import numpy as np
from config.settings import FACES_DB, ATTENDANCE_DB

class Repository:
    @staticmethod
    def get_all_users():
        with sqlite3.connect(FACES_DB) as conn:
            return conn.execute("""
                SELECT person_name, COUNT(*) as embedding_count, MAX(registered_at) as last_registered
                FROM user_embeddings
                GROUP BY person_name
                ORDER BY person_name ASC
            """).fetchall()

    @staticmethod
    def delete_user(name):
        with sqlite3.connect(FACES_DB) as conn:
            conn.execute("DELETE FROM user_embeddings WHERE person_name = ?", (name,))
            conn.commit()

    @staticmethod
    def save_embedding(name, embedding, device_id="master"):
        with sqlite3.connect(FACES_DB) as conn:
            conn.execute(
                "INSERT INTO user_embeddings (person_name, embedding, device_id, synced) VALUES (?, ?, ?, 1)",
                (name, embedding.tobytes(), device_id)
            )
            conn.commit()

    @staticmethod
    def get_attendance_by_date(date, limit=10, offset=0):
        with sqlite3.connect(ATTENDANCE_DB) as conn:
            total = conn.execute(
                "SELECT COUNT(DISTINCT person_name) FROM attendance_logs WHERE timestamp LIKE ?",
                (f"{date}%",)
            ).fetchone()[0]
            
            rows = conn.execute("""
                SELECT person_name, MIN(timestamp), MAX(timestamp) 
                FROM attendance_logs 
                WHERE timestamp LIKE ? 
                GROUP BY person_name 
                ORDER BY MIN(timestamp) DESC 
                LIMIT ? OFFSET ?
            """, (f"{date}%", limit, offset)).fetchall()
            return rows, total

    @staticmethod
    def search_attendance(name=None, date=None, limit=10, offset=0):
        conditions = []
        params = []
        if date:
            conditions.append("timestamp LIKE ?")
            params.append(f"{date}%")
        if name:
            conditions.append("person_name LIKE ?")
            params.append(f"%{name}%")
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        with sqlite3.connect(ATTENDANCE_DB) as conn:
            count_query = f"SELECT COUNT(*) FROM (SELECT person_name FROM attendance_logs {where_clause} GROUP BY person_name, substr(timestamp, 1, 10))"
            total = conn.execute(count_query, tuple(params)).fetchone()[0]
            
            data_query = f"""
                SELECT person_name, MIN(timestamp), MAX(timestamp) 
                FROM attendance_logs 
                {where_clause}
                GROUP BY person_name, substr(timestamp, 1, 10) 
                ORDER BY MIN(timestamp) DESC 
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(data_query, tuple(params + [limit, offset])).fetchall()
            return rows, total
