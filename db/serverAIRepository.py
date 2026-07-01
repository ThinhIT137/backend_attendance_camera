import logging
# Tạo logger cục bộ cho file này (nó sẽ tự thừa kế cấu hình Root ở app.py / main.py)
logger = logging.getLogger(__name__)

import sqlite3
import os
import json
from config.settings import CAMERA_DB

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state.json")
with open(STATE_PATH, encoding="utf-8") as f:
    state = json.load(f)

def _get_servers_by_status(status_value):
    """Hàm lõi: Lấy danh sách server theo trạng thái"""
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_servers WHERE status = ?", (status_value,))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Lỗi lấy server trạng thái {status_value}: {e}")
        
def _set_servers_status(server_ids, new_status):
    """Hàm lõi: Nhận 1 mảng server_id và update hàng loạt sang trạng thái mới"""
    if not server_ids:
        return
    if isinstance(server_ids, str):
        server_ids = [server_ids]
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            # Tạo data map: [('online', 'SV_01'), ('online', 'SV_02')]
            data = [(new_status, sid["id"]) for sid in server_ids]
            cursor.executemany(
                "UPDATE ai_servers SET status = ? WHERE server_id = ?",
                data
            )
            conn.commit()
            logger.info(f"Đã chuyển {len(server_ids)} server sang trạng thái '{new_status}'.")
    except Exception as e:
        logger.error(f"Lỗi chuyển trạng thái mảng server sang {new_status}: {e}")

class ServerAIRepository:

    @staticmethod
    def get_server_online():
        return _get_servers_by_status(state["online"])
    
    @staticmethod
    def get_server_offline():
        return _get_servers_by_status(state['offline'])
    
    @staticmethod
    def get_server_pending():
        return _get_servers_by_status(state['pending'])
    
    @staticmethod
    def get_server_ready():
        return _get_servers_by_status(state['ready'])
    
    @staticmethod
    def get_server_busy(): 
        return _get_servers_by_status(state['busy'])

    # --- Nhóm SET (Truyền vào mảng server_ids) ---
    @staticmethod
    def set_servers_online(server_ids):
        """
        Giao tiếp chuẩn: server_ids có thể là 'SV_001' hoặc ['SV_001', 'SV_002']
        """
        # Nếu là string đơn lẻ, biến nó thành list
        if isinstance(server_ids, str):
            server_ids = [server_ids]
            
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                cursor = conn.cursor()
                # Tạo list các tuple cho executemany: [('online', 'SV_001'), ('online', 'SV_002')]
                data = [(state["online"], sid) for sid in server_ids]
                cursor.executemany("UPDATE ai_servers SET status = ? WHERE server_id = ?", data)
                conn.commit()
                logger.info(f"✅ Đã update {len(server_ids)} server sang trạng thái online.")
        except Exception as e:
            logger.error(f"Lỗi update hàng loạt server sang online: {e}")

    @staticmethod
    def set_servers_offline(server_ids): 
        _set_servers_status(server_ids, state['offline'])

    @staticmethod
    def set_servers_pending(server_ids): 
        _set_servers_status(server_ids, state['pending'])

    @staticmethod
    def set_servers_ready(server_ids): 
        _set_servers_status(server_ids, state['ready'])

    @staticmethod
    def set_servers_busy(server_ids):
        _set_servers_status(server_ids, state['busy'])
    
    @staticmethod
    def set_cam(servers):
        try:
            if not servers:
                return
            with sqlite3.connect(CAMERA_DB) as conn:
                cursor = conn.cursor()
                data = [
                    (s["active"]+len(s["newly_assigned"]), s["id"])
                    for s in servers
                ]
                cursor.executemany(
                    "UPDATE ai_servers SET active_cam = ? WHERE server_id = ?",
                    data
                )
                conn.commit()

        except Exception as e:
            logger.error(f"Lỗi set cam server: {e}")