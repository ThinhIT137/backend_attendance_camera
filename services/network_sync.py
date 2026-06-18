import os
import sqlite3
import json
import threading
import time
import base64
import requests
import urllib3
import numpy as np
from requests.exceptions import SSLError

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from config.settings import DATA_DIR, ATTENDANCE_DB, FACES_DB

DEVICE_ID = "device_1_id" # Should be in config
FACES_SYNC_INTERVAL = 5

class AttendanceSyncer:
    def __init__(self, db_path, gateway_url, faces_db_path, sync_interval=60.0, recognizer=None):
        self.db_path = db_path
        self.faces_db_path = faces_db_path
        self.sync_interval = sync_interval
        self.recognizer = recognizer
        self.syncing = False
        self.running = False
        self.thread = None
        self.faces_thread = None
        
        self.gateway_url = gateway_url.rstrip("/")
        self.attendance_url = f"{self.gateway_url}/sync"
        self.faces_version_url = f"{self.gateway_url}/faces/version"
        self.faces_download_url = f"{self.gateway_url}/faces/download"
        self.faces_upload_url = f"{self.gateway_url}/faces/upload"
        self.faces_delete_url = f"{self.gateway_url}/faces/delete"
        self.verify = False # For now

    def start_syncing(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._attendance_loop, daemon=True)
        self.thread.start()
        self.faces_thread = threading.Thread(target=self._faces_loop, daemon=True)
        self.faces_thread.start()

    def stop_syncing(self):
        self.running = False
        if self.thread: self.thread.join(timeout=2.0)
        if self.faces_thread: self.faces_thread.join(timeout=2.0)

    def _attendance_loop(self):
        while self.running:
            self._sync_attendance()
            time.sleep(self.sync_interval)

    def _faces_loop(self):
        while self.running:
            self._push_new_embeddings()
            self._pull_faces_if_outdated()
            time.sleep(FACES_SYNC_INTERVAL)

    def _sync_attendance(self):
        if not os.path.exists(self.db_path) or self.syncing:
            return

        self.syncing = True
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT rowid, person_name, timestamp FROM attendance_logs WHERE synced = 0"
                ).fetchall()

            if not rows: return

            payload = {
                "records": [{"person_name": row[1], "timestamp": row[2]} for row in rows],
                "device_id": DEVICE_ID
            }

            response = requests.post(self.attendance_url, json=payload, timeout=10)

            if response.status_code == 200:
                self._mark_attendance_synced([row[0] for row in rows])
        except Exception as e:
            print(f"Attendance Sync Error: {e}")
        finally:
            self.syncing = False

    def _mark_attendance_synced(self, pending_ids):
        with sqlite3.connect(self.db_path) as conn:
            placeholders = ','.join(['?'] * len(pending_ids))
            conn.execute(f"UPDATE attendance_logs SET synced = 1 WHERE rowid IN ({placeholders})", pending_ids)
            conn.commit()

    def _push_new_embeddings(self):
        if not os.path.exists(self.faces_db_path): return
        try:
            with sqlite3.connect(self.faces_db_path) as conn:
                rows = conn.execute("SELECT rowid, person_name, embedding FROM user_embeddings WHERE synced = 0").fetchall()
            
            if not rows: return
            
            payload = {
                "device_id": DEVICE_ID,
                "embeddings": [{"person_name": r[1], "embedding": base64.b64encode(r[2]).decode()} for r in rows]
            }
            response = requests.post(self.faces_upload_url, json=payload, timeout=10)
            if response.status_code == 200:
                with sqlite3.connect(self.faces_db_path) as conn:
                    ids = [r[0] for r in rows]
                    conn.execute(f"UPDATE user_embeddings SET synced = 1 WHERE rowid IN ({','.join(['?']*len(ids))})", ids)
                    conn.commit()
        except Exception as e:
            print(f"Faces Push Error: {e}")

    def _pull_faces_if_outdated(self):
        try:
            response = requests.get(self.faces_version_url, timeout=10)
            if response.status_code != 200: return
            host_version = response.json().get("version", 0)
            
            local_version = 0
            if os.path.exists(self.faces_db_path):
                with sqlite3.connect(self.faces_db_path) as conn:
                    row = conn.execute("SELECT version FROM faces_version WHERE id = 1").fetchone()
                    local_version = row[0] if row else 0
            
            if host_version <= local_version: return

            response = requests.get(self.faces_download_url, timeout=10)
            if response.status_code != 200: return
            embeddings = response.json().get("embeddings", [])

            with sqlite3.connect(self.faces_db_path) as conn:
                conn.execute("DELETE FROM user_embeddings WHERE synced = 1")
                for emb in embeddings:
                    conn.execute("INSERT INTO user_embeddings (person_name, embedding, device_id, synced) VALUES (?, ?, ?, 1)",
                                 (emb["person_name"], base64.b64decode(emb["embedding"]), emb.get("device_id")))
                conn.execute("UPDATE faces_version SET version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1", (host_version,))
                conn.commit()
            
            if self.recognizer: self.recognizer.load_database()
        except Exception as e:
            print(f"Faces Pull Error: {e}")

    def push_delete(self, person_name):
        payload = {"device_id": DEVICE_ID, "person_name": person_name}
        try:
            requests.post(self.faces_delete_url, json=payload, timeout=10)
        except: pass

    def signal_track(self, person_name):
        payload = {"name": person_name}
        try:
            requests.post(f"{self.gateway_url}/camera/track", json=payload, timeout=5)
        except: pass
