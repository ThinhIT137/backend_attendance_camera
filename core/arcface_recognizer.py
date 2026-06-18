import cv2
import numpy as np
import os
import sqlite3
from datetime import datetime
from config.settings import DATA_DIR, FACES_DB, ATTENDANCE_DB

class ArcFaceRecognizer:
    def __init__(self, model_path=None):
        if model_path is None:
            model_path = os.path.join(DATA_DIR, "models", "arcface.onnx")
        
        if not os.path.exists(model_path):
            # In a real scenario, we might want to download this too, but for now we expect it
            print(f"WARNING: ArcFace model not found at {model_path}")
        
        try:
            self.net = cv2.dnn.readNetFromONNX(model_path)
        except Exception as e:
            print(f"Error loading ArcFace model: {e}")
            self.net = None

        self.known_names = []
        self.known_embeddings = []
        self.threshold = 0.55

    def load_database(self):
        """Load all face embeddings from faces.db into memory."""
        if not os.path.exists(FACES_DB):
            print("No faces.db found yet.")
            return

        conn = sqlite3.connect(FACES_DB)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT person_name, embedding FROM user_embeddings")
            rows = cursor.fetchall()
            self.known_names = []
            self.known_embeddings = []
            for row in rows:
                self.known_names.append(row[0])
                self.known_embeddings.append(np.frombuffer(row[1], dtype=np.float32))
            print(f"Loaded {len(self.known_names)} embeddings into memory.")
        except sqlite3.OperationalError:
            print("Database exists but no user_embeddings table found.")
        finally:
            conn.close()

    @staticmethod
    def pad_to_square(img_bgr):
        h, w = img_bgr.shape[:2]
        if h == w: return img_bgr
        size = max(h, w)
        top, left = (size - h) // 2, (size - w) // 2
        bottom, right = size - h - top, size - w - left
        return cv2.copyMakeBorder(img_bgr, top, bottom, left, right, cv2.BORDER_CONSTANT, value=0)

    def get_embedding(self, cropped_face_bgr):
        if self.net is None: return np.zeros(128, dtype=np.float32)
        square = self.pad_to_square(cropped_face_bgr)
        resized = cv2.resize(square, (112, 112))
        blob = cv2.dnn.blobFromImage(
            resized, scalefactor=1.0/127.5, size=(112, 112), 
            mean=(127.5, 127.5, 127.5), swapRB=True
        )
        self.net.setInput(blob)
        emb = self.net.forward()[0]
        return emb / (np.linalg.norm(emb) + 1e-10)

    def cosine_similarity(self, a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def recognize(self, face_bgr):
        if not self.known_embeddings:
            return "Unknown", 0.0
        query = self.get_embedding(face_bgr)
        best_name, best_sim = "Unknown", -1.0
        for name, emb in zip(self.known_names, self.known_embeddings):
            sim = self.cosine_similarity(query, emb)
            if sim > best_sim:
                best_sim, best_name = sim, name
        if best_sim >= self.threshold:
            return best_name, best_sim
        return "Unknown", best_sim

    def log_attendance(self, name):
        """Log a recognition event to attendance.db."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(ATTENDANCE_DB)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO attendance_logs (person_name, timestamp) VALUES (?, ?)", (name, now))
        conn.commit()
        conn.close()
        print(f"Logged attendance: {name} at {now}")
        return now
