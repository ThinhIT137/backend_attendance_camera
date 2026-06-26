import os
from flask import Flask, render_template
from flask_cors import CORS
from config.settings import BASE_DIR, ATTENDANCE_DB, FACES_DB, GATEWAY_URL
# router
from api.router.enrollment import enrollment_bp
from api.router.attendance import attendance_bp
from api.router.host import host_bp
from api.router.server_yolo import server_yolo_bp
from api.router.camera import camera_bp
# services
from services.mediamtx_service import start_mediamtx, sync_yml_to_db, sync_db_to_yml
from services.server_yolo_service import start_server_monitor, start_watchdog
from services import face_service
from services.network_sync import AttendanceSyncer
from services.server_yolo_service import broadcast_my_url_to_all_workers

from db.models import setup_databases

# Setup DB before starting app
setup_databases()

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

# CORS(app, origins=["http://localhost:3000"])
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ── Đăng ký các Blueprints (Controllers) ──
app.register_blueprint(enrollment_bp)
app.register_blueprint(attendance_bp)
app.register_blueprint(host_bp)
app.register_blueprint(server_yolo_bp)
app.register_blueprint(camera_bp)

def on_startup():
    print("🚀 Đang khởi động hệ thống...")
    start_server_monitor()
    start_watchdog()
    sync_yml_to_db()
    sync_db_to_yml()
    start_mediamtx()

if __name__ == "__main__":
    print("=" * 50)
    print("  Face Recognition Attendance System")
    print("  Open http://localhost:5000 in your browser")
    print("=" * 50)

    on_startup()

    # ── Khởi tạo quá trình Sync mạng ──
    face_service.syncer_instance = AttendanceSyncer(
        db_path       = ATTENDANCE_DB,
        faces_db_path = FACES_DB,
        gateway_url   = GATEWAY_URL,
        sync_interval = 60.0,
        recognizer    = face_service.recognizer,
    )
    face_service.syncer_instance.start_syncing()

    # 👉 1. Gọi hàm báo mộng cho các Worker biết IP của Master
    broadcast_my_url_to_all_workers()

    # 👉 2. Lấy port từ .env (nếu không có thì mặc định 5000)
    port = int(os.getenv("MASTER_NODE_PORT", 5000))

    try:
        app.run(host="0.0.0.0", port=port, debug=False)
    finally:
        face_service.syncer_instance.stop_syncing()