import os
from flask import Blueprint, request, jsonify
from db.repository import Repository
from services.face_service import recognizer
from config.settings import FACES_DIR, DATA_DIR
import shutil
import threading
from datetime import datetime

attendance_bp = Blueprint('attendance', __name__)

@attendance_bp.route("/api/users")
def api_get_users():
    target_name = request.args.get("name", "").strip()
    try:
        page, limit = int(request.args.get("page", 1)), int(request.args.get("limit", 10))
    except ValueError:
        page, limit = 1, 10
    
    rows, total = Repository.search_attendance(name=target_name, limit=limit, offset=(page-1)*limit)
    # Note: Repository.search_attendance actually returns attendance search. 
    # The original api_get_users in attendance.py was getting users from attendance logs.
    # Let's fix Repository to have a proper get_users from attendance logs if needed, 
    # but usually users come from faces.db.
    
    # Let's use Repository.get_all_users() for user list
    users = Repository.get_all_users()
    # Filter by name if provided (simple filter for now, could be in repo)
    if target_name:
        users = [u for u in users if target_name.lower() in u[0].lower()]
    
    total_rows = len(users)
    start = (page - 1) * limit
    end = start + limit
    paged_users = users[start:end]

    records = [{"id": i+start, "name": u[0], "embeddings": u[1], "last_registered": u[2]} for i, u in enumerate(paged_users)]

    return jsonify({
        "records": records, 
        "pagination": {
            "total_records": total_rows, 
            "total_pages": (total_rows + limit - 1) // limit, 
            "current_page": page, 
            "limit": limit
        }
    })

@attendance_bp.route("/api/users/delete/<name>", methods=["POST"])
def api_delete_user(name):
    Repository.delete_user(name)
    user_dir = os.path.join(FACES_DIR, name)
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)
    recognizer.load_database()
    from services import face_service
    if face_service.syncer_instance is not None:
        threading.Thread(target=face_service.syncer_instance.push_delete, args=(name,), daemon=True).start()

    return jsonify({"success": True})

@attendance_bp.route("/api/attendance/by_date")
def api_attendance_by_date():
    target_date = request.args.get("date")
    try:
        page, limit = int(request.args.get("page", 1)), int(request.args.get("limit", 10))
    except ValueError:
        page, limit = 1, 10
    if not target_date:
        return jsonify({"error": "Vui lòng cung cấp tham số ngày (YYYY-MM-DD)"}), 400
    rows, total = Repository.get_attendance_by_date(target_date, limit=limit, offset=(page-1)*limit)
    records = []
    for r in rows:
        name, check_in, check_out = r[0], r[1], r[2]
        if check_in == check_out: check_out = None
        records.append({"name": name, "check_in": check_in, "check_out": check_out})
    return jsonify({
        "records": records, 
        "pagination": {
            "total_records": total, 
            "total_pages": (total + limit - 1) // limit, 
            "current_page": page, 
            "limit": limit
        }
    })

@attendance_bp.route("/api/attendance/search")
def api_attendance_search():
    target_date = request.args.get("date", "").strip()
    target_name = request.args.get("name", "").strip()
    try:
        page, limit = int(request.args.get("page", 1)), int(request.args.get("limit", 10))
    except ValueError:
        page, limit = 1, 10
    
    if not target_date and not target_name:
        return jsonify({"error": "Vui lòng cung cấp ngày hoặc tên để tìm kiếm"}), 400
    rows, total = Repository.search_attendance(name=target_name, date=target_date, limit=limit, offset=(page-1)*limit)
    records = []
    for r in rows:
        name, check_in, check_out = r[0], r[1], r[2]
        if check_in == check_out: check_out = None
        records.append({"name": name, "check_in": check_in, "check_out": check_out})
    return jsonify({
        "records": records, 
        "pagination": {
            "total_records": total, 
            "total_pages": (total + limit - 1) // limit, 
            "current_page": page, 
            "limit": limit
        }
    })
    
@attendance_bp.route("/api/attendance/dashboard-stats")
def api_dashboard_stats():
    # Lấy ngày hiện tại theo chuẩn YYYY-MM-DD
    today = datetime.now().strftime("%Y-%m-%d")
    # Gọi hàm Repository lấy số liệu
    stats = Repository.get_dashboard_stats(today)
    return jsonify(stats)

@attendance_bp.route("/api/attendance/timeline")
def api_attendance_timeline():
    # Lấy ngày hiện tại theo chuẩn YYYY-MM-DD
    today = datetime.now().strftime("%Y-%m-%d")
    # Lấy dữ liệu biểu đồ
    timeline_data = Repository.get_today_timeline(today)
    # Nếu chưa có dữ liệu nào trong ngày, trả về mảng rỗng để FE tự vẽ form trống
    return jsonify(timeline_data)

@attendance_bp.route("/api/attendance/user-summary")
def api_user_summary():
    # Lấy ngày hiện tại
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Gọi qua Repository (đã có sẵn thư viện sqlite3 bên đó)
    summary = Repository.get_user_summary(today)
    
    return jsonify(summary)