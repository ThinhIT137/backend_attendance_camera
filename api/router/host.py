from flask import Blueprint, request, jsonify, render_template_string
import sqlite3
import base64
import os
from config.settings import FACES_DB, ATTENDANCE_DB, HOST_TOKEN

host_bp = Blueprint('host', __name__)

def check_token(req):
    return req.headers.get("X-Sync-Token") == HOST_TOKEN

def get_version():
    with sqlite3.connect(FACES_DB) as conn:
        row = conn.execute("SELECT version, updated_at FROM faces_version WHERE id = 1").fetchone()
    return row

@host_bp.route('/sync', methods=['POST'])
def sync_data():
    if not check_token(request):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    if not data or 'records' not in data:
        return jsonify({'status': 'error', 'message': 'No data provided'}), 400

    device_id = data.get("device_id") or request.headers.get("X-Device-ID", "unknown")

    try:
        with sqlite3.connect(ATTENDANCE_DB) as conn:
            new_count = 0
            for record in data['records']:
                conn.execute('''
                    INSERT OR IGNORE INTO attendance_logs (person_name, timestamp, device_id)
                    VALUES (?, ?, ?)
                ''', (record['person_name'], record['timestamp'], device_id))
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    new_count += 1
            conn.commit()
        return jsonify({'status': 'success', 'synced_count': new_count})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@host_bp.route('/faces/version', methods=['GET'])
def faces_version():
    if not check_token(request): return jsonify({"error": "Unauthorized"}), 401
    try:
        version, updated_at = get_version()
        return jsonify({"version": version, "updated_at": updated_at})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@host_bp.route('/faces/download', methods=['GET'])
def faces_download():
    if not check_token(request): return jsonify({"error": "Unauthorized"}), 401
    try:
        with sqlite3.connect(FACES_DB) as conn:
            rows = conn.execute('SELECT person_name, embedding, device_id, registered_at FROM user_embeddings').fetchall()
            version, updated_at = get_version()

        embeddings = [
            {
                "person_name":   row[0],
                "embedding":     base64.b64encode(row[1]).decode(),
                "device_id":     row[2],
                "registered_at": row[3],
            }
            for row in rows
        ]
        return jsonify({"version": version, "updated_at": updated_at, "count": len(embeddings), "embeddings": embeddings})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@host_bp.route('/faces/upload', methods=['POST'])
def faces_upload():
    if not check_token(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    if not data or "embeddings" not in data: return jsonify({"error": "Missing embeddings"}), 400

    device_id, embeddings = data.get("device_id", "unknown"), data["embeddings"]
    try:
        with sqlite3.connect(FACES_DB) as conn:
            inserted = 0
            for emb in embeddings:
                name, embedding = emb.get("person_name"), emb.get("embedding")
                if not name or not embedding: continue
                conn.execute('INSERT INTO user_embeddings (person_name, embedding, device_id, synced) VALUES (?, ?, ?, 1)',
                             (name, base64.b64decode(embedding), device_id))
                inserted += 1
            conn.execute('UPDATE faces_version SET version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1')
            conn.commit()
        return jsonify({"status": "success", "inserted": inserted})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
