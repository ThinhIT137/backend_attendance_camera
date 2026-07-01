from config.logger_utils import setup_global_system_logger
logger = setup_global_system_logger(log_file_prefix="master-node")
logger.info("🎬 [MASTER] Hệ thống Logger toàn cục theo phiên đã kích hoạt!")

import os
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from flask import Flask
from flask_cors import CORS
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware

from config.settings import BASE_DIR, ATTENDANCE_DB, FACES_DB, GATEWAY_URL

# --- ROUTER FLASK ---
from api.router.enrollment import enrollment_bp
from api.router.attendance import attendance_bp
from api.router.host import host_bp
from api.router.server_yolo import server_yolo_bp
from api.router.camera import camera_bp

# --- ROUTER FASTAPI ---
from api.router.websocket_router import ws_router 

# --- SERVICES ---
from services.mediamtx_service import start_mediamtx, sync_yml_to_db, sync_db_to_yml
from services.server_yolo_service import start_server_monitor, start_watchdog, broadcast_my_url_to_all_workers
from services import face_service
from services.network_sync import AttendanceSyncer
from services.websocket_service import zmq_receiver_task
from db.models import setup_databases

# 1. SETUP DATABASE
setup_databases()

# 2. KHỞI TẠO FLASK APP
flask_app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)
CORS(flask_app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Đăng ký Blueprints cho Flask
flask_app.register_blueprint(enrollment_bp)
flask_app.register_blueprint(attendance_bp)
flask_app.register_blueprint(host_bp)
flask_app.register_blueprint(server_yolo_bp)
flask_app.register_blueprint(camera_bp)

# 3. KHỞI TẠO FASTAPI APP
@asynccontextmanager
async def lifespan(app: FastAPI):
    # KHI APP START: Đẩy thằng đệ ra canh cổng ZMQ
    zmq_task = asyncio.create_task(zmq_receiver_task())
    yield
    # KHI APP TẮT: Thu hồi task
    zmq_task.cancel()

fastapi_app = FastAPI(lifespan=lifespan)

# Đăng ký Router WebSocket cho FastAPI
fastapi_app.include_router(ws_router)

# 🔥 DUNG HỢP: Gắn toàn bộ Flask vào trong FastAPI
fastapi_app.mount("/", WSGIMiddleware(flask_app))

def on_startup():
    logger.info("🚀 Đang khởi động hệ thống...")
    start_server_monitor()
    start_watchdog()
    sync_yml_to_db()
    sync_db_to_yml()
    start_mediamtx()

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info(" 🌟 Face Recognition Attendance System (Flask + FastAPI)")
    logger.info("=" * 50)

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

    # Gọi hàm báo mộng
    broadcast_my_url_to_all_workers()

    port = int(os.getenv("MASTER_NODE_PORT", 5000))

    try:
        # 🔥 QUAN TRỌNG: Phải dùng uvicorn để chạy app FastAPI
        logger.info(f" 🚀 Đang chạy Server tại: http://localhost:{port}")
        uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")
    finally:
        face_service.syncer_instance.stop_syncing()