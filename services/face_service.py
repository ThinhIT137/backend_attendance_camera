import cv2
import numpy as np
import base64
from core.face_detection import FaceDetector
from core.arcface_recognizer import ArcFaceRecognizer
from config.settings import DATA_DIR

# ── Initialize Engines ──
detector   = FaceDetector()
recognizer = ArcFaceRecognizer()
recognizer.load_database()

# ── Server-side State ──
reg_sessions = {}

recog_state = {
    "tracking_name":     None,
    "consecutive_matches": 0,
    "required_matches":  3,
    "recently_logged":   {},
    "log_cooldown":      10.0,
}

# Syncer reference để dùng chung giữa các luồng
syncer_instance = None

def decode_base64_image(data_url):
    try:
        if "," in data_url:
            data_url = data_url.split(",", 1)[1]
        img_bytes = base64.b64decode(data_url)
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"Image decode error: {e}")
        return None