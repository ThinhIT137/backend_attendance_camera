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
        
    # Thêm phần này vào cuối file master-node/db/repository.py, bên trong class Repository

    @staticmethod
    def get_dashboard_stats(today_date):
        # 1. Lấy tổng số nhân sự (đếm theo tên duy nhất trong faces db)
        with sqlite3.connect(FACES_DB) as conn:
            total_employees = conn.execute(
                "SELECT COUNT(DISTINCT person_name) FROM user_embeddings"
            ).fetchone()[0] or 0

        # 2. Lấy số lượng điểm danh hôm nay và số lượng camera
        with sqlite3.connect(ATTENDANCE_DB) as conn:
            # Những người đã điểm danh hôm nay
            present_today = conn.execute(
                "SELECT COUNT(DISTINCT person_name) FROM attendance_logs WHERE timestamp LIKE ?",
                (f"{today_date}%",)
            ).fetchone()[0] or 0

            # Camera hoạt động hôm nay (có gửi log điểm danh)
            active_cameras = conn.execute(
                "SELECT COUNT(DISTINCT device_id) FROM attendance_logs WHERE timestamp LIKE ?",
                (f"{today_date}%",)
            ).fetchone()[0] or 0
            
            # Tổng số camera từng được ghi nhận trong hệ thống
            total_cameras = conn.execute(
                "SELECT COUNT(DISTINCT device_id) FROM attendance_logs"
            ).fetchone()[0] or 0

        # Nếu chưa có log camera nào, giả định tối thiểu là bằng active
        total_cameras = max(total_cameras, active_cameras)

        return {
            "totalEmployees": total_employees,
            "presentToday": present_today,
            "absentToday": max(0, total_employees - present_today),
            "activeCameras": active_cameras,
            "totalCameras": total_cameras
        }

    @staticmethod
    def get_today_timeline(today_date):
        with sqlite3.connect(ATTENDANCE_DB) as conn:
            # Trích xuất 2 ký tự của giờ (VD: từ "2024-06-22 08:30:00" -> "08")
            # SQLite function: substr(chuỗi, vị trí_bắt_đầu, độ_dài)
            query = """
                SELECT substr(timestamp, 12, 2) as hour, COUNT(DISTINCT person_name) as checkins
                FROM attendance_logs
                WHERE timestamp LIKE ?
                GROUP BY hour
                ORDER BY hour ASC
            """
            rows = conn.execute(query, (f"{today_date}%",)).fetchall()

        # Định dạng lại output cho Recharts ở Frontend
        timeline = []
        for row in rows:
            hour = row[0]
            count = row[1]
            timeline.append({
                "timeSlot": f"{hour}:00", 
                "checkIns": count
            })
            
        return timeline
    
    @staticmethod
    def get_user_summary(today_date):
        # 1. Lấy tổng số người có trong hệ thống
        with sqlite3.connect(FACES_DB) as conn:
            total_users = conn.execute(
                "SELECT COUNT(DISTINCT person_name) FROM user_embeddings"
            ).fetchone()[0] or 0
            
        # 2. Lấy số lượng người ĐÃ điểm danh hôm nay
        with sqlite3.connect(ATTENDANCE_DB) as conn:
            present_today = conn.execute(
                "SELECT COUNT(DISTINCT person_name) FROM attendance_logs WHERE timestamp LIKE ?",
                (f"{today_date}%",)
            ).fetchone()[0] or 0
            
        # 3. Tính số người CHƯA điểm danh
        absent_today = max(0, total_users - present_today)
        
        return {
            "total_users": total_users,
            "present_today": present_today,
            "absent_today": absent_today
        }
