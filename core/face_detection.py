import cv2
import numpy as np
import os
import urllib.request
from config.settings import DATA_DIR

YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
    "face_detection_yunet_2023mar.onnx"
)

class FaceDetector:
    """YuNet-based face detector with quality checks."""

    def __init__(self, input_size=(320, 320)):
        model_dir = os.path.join(DATA_DIR, "models")
        os.makedirs(model_dir, exist_ok=True)

        self.model_path = os.path.join(model_dir, "yunet.onnx")
        self._download_if_missing(self.model_path, YUNET_URL, "YuNet ONNX")

        self._input_size = input_size  # (w, h)
        self.detector = cv2.FaceDetectorYN.create(
            model=self.model_path,
            config="",
            input_size=input_size,
            score_threshold=0.6,
            nms_threshold=0.3,
            top_k=5,
        )

        # Quality thresholds
        self.MIN_FACE_RATIO   = 0.15
        self.MAX_FACE_RATIO   = 0.85
        self.BRIGHTNESS_LOW   = 70
        self.BRIGHTNESS_HIGH  = 180
        self.BLUR_THRESHOLD   = 20
        self.CENTER_THRESHOLD = 0.20

    def _download_if_missing(self, filepath, url, label, timeout=15):
        if os.path.exists(filepath):
            return
        print(f"Downloading {label} ...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp, \
                 open(filepath, "wb") as f:
                f.write(resp.read())
            print(f"  [OK] {label} saved to {filepath}")
        except Exception as e:
            print(f"  [FAIL] Could not download {label}: {e}")
            raise RuntimeError(f"Required model '{label}' not found.") from e

    def detect(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        if (w, h) != self._input_size:
            self._input_size = (w, h)
            self.detector.setInputSize((w, h))

        _, raw = self.detector.detect(frame_bgr)
        faces = []
        if raw is None:
            return faces

        for det in raw:
            x, y, fw, fh = int(det[0]), int(det[1]), int(det[2]), int(det[3])
            x, y = max(0, x), max(0, y)
            fw = min(fw, w - x)
            fh = min(fh, h - y)
            if fw <= 0 or fh <= 0: continue

            confidence = float(det[14])
            landmarks = {
                "right_eye":   (int(det[4]),  int(det[5])),
                "left_eye":    (int(det[6]),  int(det[7])),
                "nose":        (int(det[8]),  int(det[9])),
                "right_mouth": (int(det[10]), int(det[11])),
                "left_mouth":  (int(det[12]), int(det[13])),
            }
            faces.append({"x": x, "y": y, "w": fw, "h": fh, "confidence": confidence, "landmarks": landmarks})

        faces.sort(key=lambda f: f["confidence"], reverse=True)
        return faces

    def quality_check(self, frame, face):
        reasons = []
        h, w = frame.shape[:2]
        face_ratio = face["h"] / h
        if face_ratio < self.MIN_FACE_RATIO: reasons.append("Too far")
        if face_ratio > self.MAX_FACE_RATIO: reasons.append("Too close")

        cx = (face["x"] + face["w"] / 2) / w
        cy = (face["y"] + face["h"] / 2) / h
        if abs(cx - 0.5) > self.CENTER_THRESHOLD or abs(cy - 0.5) > self.CENTER_THRESHOLD:
            reasons.append("Move to center")

        lm = face.get("landmarks")
        if lm:
            re, le = lm["right_eye"], lm["left_eye"]
            eye_dx, eye_dy = le[0] - re[0], le[1] - re[1]
            tilt_deg = abs(np.degrees(np.arctan2(eye_dy, eye_dx)))
            if tilt_deg > 20: reasons.append("Tilt head straight")

        fx, fy, fw, fh = face["x"], face["y"], face["w"], face["h"]
        face_crop = frame[fy:fy + fh, fx:fx + fw]
        if face_crop.size > 0:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            brightness = np.mean(gray)
            if brightness < self.BRIGHTNESS_LOW: reasons.append("Too dark")
            elif brightness > self.BRIGHTNESS_HIGH: reasons.append("Too bright")
            lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            if lap_var < self.BLUR_THRESHOLD: reasons.append("Blurry — hold still")
        else:
            reasons.append("Face out of bounds")
        return len(reasons) == 0, reasons

    def crop_face(self, frame, face, padding=0.2):
        h, w = frame.shape[:2]
        fx, fy, fw, fh = face["x"], face["y"], face["w"], face["h"]
        pad_w, pad_h = int(fw * padding), int(fh * padding)
        x1, y1 = max(0, fx - pad_w), max(0, fy - pad_h)
        x2, y2 = min(w, fx + fw + pad_w), min(h, fy + fh + pad_h)
        return frame[y1:y2, x1:x2]
