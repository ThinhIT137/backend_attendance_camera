import os
from flask import Flask, render_template
from flask_cors import CORS

from config.settings import BASE_DIR, ATTENDANCE_DB, FACES_DB, GATEWAY_URL
from api.router.enrollment import enrollment_bp
from api.router.attendance import attendance_bp
from api.router.host import host_bp
from db.models import setup_databases

from services import face_service
from services.network_sync import AttendanceSyncer

# Setup DB before starting app
setup_databases()

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

CORS(app, origins=["http://localhost:3000"])

# ── Đăng ký các Blueprints (Controllers) ──
app.register_blueprint(enrollment_bp)
app.register_blueprint(attendance_bp)
app.register_blueprint(host_bp)

# # ── Page Routes (UI) ──
# @app.route("/")
# def index():
#     return render_template("index.html")

# @app.route("/register")
# def register_page():
#     return render_template("register.html")

# @app.route("/recognize")
# def recognize_page():
#     return render_template("recognize.html")

# @app.route("/users")
# def users_page():
#     return render_template("users.html")

# @app.route("/attendance")
# def attendance_page():
#     return render_template("attendance.html")


if __name__ == "__main__":
    print("=" * 50)
    print("  Face Recognition Attendance System")
    print("  Open http://localhost:5000 in your browser")
    print("=" * 50)

    # ── Khởi tạo quá trình Sync mạng ──
    face_service.syncer_instance = AttendanceSyncer(
        db_path       = ATTENDANCE_DB,
        faces_db_path = FACES_DB,
        gateway_url   = GATEWAY_URL,
        sync_interval = 60.0,
        recognizer    = face_service.recognizer,
    )
    face_service.syncer_instance.start_syncing()

    try:
        app.run(host="127.0.0.1", port=5000, debug=False)
    finally:
        face_service.syncer_instance.stop_syncing()