import os
import sys

# ── Path resolution (supports PyInstaller bundle) ──
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    EXE_DIR  = os.path.dirname(sys.executable)
    DATA_DIR = os.path.join(EXE_DIR, "data")
else:
    # Lùi 2 cấp từ config/settings.py ra master-node/
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, "data")

FACES_DIR     = os.path.join(DATA_DIR, "registered_faces")
FACES_DB      = os.path.join(DATA_DIR, "databases", "faces.db")
ATTENDANCE_DB = os.path.join(DATA_DIR, "databases", "attendance.db")

HOST_TOKEN = os.environ.get("HOST_TOKEN", "host_token_123")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://10.40.91.141:5100")
DEVICE_ID = os.environ.get("DEVICE_ID", "device_1_id")

# Đảm bảo các thư mục tồn tại
os.makedirs(FACES_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "databases"), exist_ok=True)