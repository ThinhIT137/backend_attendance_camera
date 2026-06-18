import os
import time
import glob
import cv2
import sqlite3
import numpy as np
import threading
from flask import Blueprint, request, jsonify

from config.settings import FACES_DIR, FACES_DB, DATA_DIR
from services.face_service import (
    detector, recognizer, reg_sessions, recog_state, 
    decode_base64_image, syncer_instance
)
from core.arcface_recognizer import ArcFaceRecognizer

enrollment_bp = Blueprint('enrollment', __name__)

@enrollment_bp.route("/api/register/start", methods=["POST"])
def api_register_start():
    data = request.get_json()
    name = data.get("name", "").strip().replace(" ", "_")
    if not name:
        return jsonify({"error": "Name is required"}), 400

    person_dir = os.path.join(FACES_DIR, name)
    os.makedirs(person_dir, exist_ok=True)

    sid = f"{name}_{int(time.time())}"
    reg_sessions[sid] = {
        "name":                name,
        "dir":                 person_dir,
        "shots":               0,
        "max_shots":           5,
        "stability":           0,
        "stability_threshold": 6,
        "bursting":            False,
    }
    return jsonify({"session_id": sid, "name": name, "max_shots": 5})

@enrollment_bp.route("/api/register/frame", methods=["POST"])
def api_register_frame():
    data  = request.get_json()
    sid   = data.get("session_id")
    image = data.get("image")

    if not sid or sid not in reg_sessions:
        return jsonify({"error": "Invalid session"}), 400

    reg = reg_sessions[sid]
    if reg["shots"] >= reg["max_shots"]:
        return jsonify({"status": "COMPLETE", "shots": reg["shots"], "max_shots": reg["max_shots"], "progress": 1.0})

    frame = decode_base64_image(image)
    if frame is None:
        return jsonify({"error": "Bad image"}), 400

    faces = detector.detect(frame)
    if not faces:
        reg["stability"] = 0
        reg["bursting"]  = False
        return jsonify({"status": "NO_FACE", "reasons": ["No face detected"], "shots": reg["shots"], "max_shots": reg["max_shots"], "progress": 0})

    face = faces[0]
    passed, reasons = detector.quality_check(frame, face)

    if not passed:
        reg["stability"] = 0
        reg["bursting"]  = False
        return jsonify({"status": "INVALID", "reasons": reasons, "shots": reg["shots"], "max_shots": reg["max_shots"], "progress": 0})

    crop_bgr = ArcFaceRecognizer.pad_to_square(detector.crop_face(frame, face))
    if reg["bursting"]:
        reg["shots"] += 1
        ts   = int(time.time() * 1000)
        path = os.path.join(reg["dir"], f"face_{reg['shots']}_{ts}.jpg")
        cv2.imwrite(path, crop_bgr)
        reg["bursting"]  = False
        reg["stability"] = 0
        status   = "COMPLETE" if reg["shots"] >= reg["max_shots"] else "BURST_CAPTURE"
        progress = 1.0
    else:
        reg["stability"] += 1
        progress = min(reg["stability"] / reg["stability_threshold"], 1.0)
        if reg["stability"] >= reg["stability_threshold"]:
            reg["bursting"] = True
            reg["shots"] += 1
            ts   = int(time.time() * 1000)
            path = os.path.join(reg["dir"], f"face_{reg['shots']}_{ts}.jpg")
            cv2.imwrite(path, crop_bgr)
            status = "COMPLETE" if reg["shots"] >= reg["max_shots"] else "BURST_CAPTURE"
        else:
            status = "STABILIZING"

    return jsonify({"status": status, "shots": reg["shots"], "max_shots": reg["max_shots"], "progress": progress})

@enrollment_bp.route("/api/register/finish", methods=["POST"])
def api_register_finish():
    data = request.get_json()
    sid  = data.get("session_id")

    if not sid or sid not in reg_sessions:
        return jsonify({"error": "Invalid session"}), 400

    reg        = reg_sessions[sid]
    name       = reg["name"]
    person_dir = reg["dir"]

    conn   = sqlite3.connect(FACES_DB)
    cursor = conn.cursor()

    images     = glob.glob(os.path.join(person_dir, "*.jpg"))
    embeddings = []
    for img_path in images:
        face = cv2.imread(img_path)
        if face is not None:
            emb = recognizer.get_embedding(face)
            embeddings.append(emb)

    saved      = 0
    chunk_size = 5
    for i in range(0, len(embeddings), chunk_size):
        chunk = embeddings[i: i + chunk_size]
        if chunk:
            avg = np.mean(np.array(chunk), axis=0).astype(np.float32)
            cursor.execute(
                "INSERT INTO user_embeddings (person_name, embedding, device_id, synced) VALUES (?, ?, ?, 0)",
                (name, avg.tobytes(), "device_1_id"),
            )
            saved += 1

    conn.commit()
    conn.close()
    recognizer.load_database()

    from services import face_service
    if face_service.syncer_instance is not None:
        threading.Thread(target=face_service.syncer_instance._push_new_embeddings, daemon=True).start()

    del reg_sessions[sid]
    return jsonify({"success": True, "name": name, "embeddings_saved": saved})

@enrollment_bp.route("/api/recognize/frame", methods=["POST"])
def api_recognize_frame():
    data  = request.get_json()
    image = data.get("image")

    frame = decode_base64_image(image)
    if frame is None:
        return jsonify({"error": "Bad image"}), 400

    faces = detector.detect(frame)
    if not faces:
        recog_state["tracking_name"]      = None
        recog_state["consecutive_matches"] = 0
        return jsonify({"status": "no_face", "name": None, "confidence": 0})

    face = faces[0]
    passed, reasons = detector.quality_check(frame, face)

    if not passed:
        recog_state["tracking_name"]      = None
        recog_state["consecutive_matches"] = 0
        return jsonify({"status": "low_quality", "name": None, "confidence": 0, "reasons": reasons, "logged": False, "consecutive": 0, "required": recog_state["required_matches"]})

    crop_bgr = detector.crop_face(frame, face)
    name, confidence = recognizer.recognize(crop_bgr)

    logged = False
    now    = time.time()

    if name != "Unknown":
        if name == recog_state["tracking_name"]:
            recog_state["consecutive_matches"] += 1
        else:
            recog_state["tracking_name"]      = name
            recog_state["consecutive_matches"] = 1

        if recog_state["consecutive_matches"] >= recog_state["required_matches"]:
            last = recog_state["recently_logged"].get(name, 0)
            if now - last > recog_state["log_cooldown"]:
                recognizer.log_attendance(name)
                recog_state["recently_logged"][name] = now
                logged = True
                
                from services import face_service
                if face_service.syncer_instance is not None:
                    threading.Thread(target=face_service.syncer_instance.signal_track, args=(name,), daemon=True).start()
    else:
        recog_state["tracking_name"]      = None
        recog_state["consecutive_matches"] = 0

    return jsonify({"status": "recognized" if name != "Unknown" else "unknown", "name": name, "confidence": round(confidence, 4), "logged": logged, "consecutive": recog_state["consecutive_matches"], "required": recog_state["required_matches"]})