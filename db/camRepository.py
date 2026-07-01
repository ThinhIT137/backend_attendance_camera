import logging
# Tạo logger cục bộ cho file này (nó sẽ tự thừa kế cấu hình Root ở app.py / main.py)
logger = logging.getLogger(__name__)

import sqlite3
import os
import json
from config.settings import CAMERA_DB

STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state.json")
with open(STATE_PATH, encoding="utf-8") as f:
    state = json.load(f)

class CamRepository:
    @staticmethod
    def set_cam_pending(cams=None, server_id=None):
        """
        Hàm tuỳ biến: 
        1. Không truyền gì: Cập nhật TẤT CẢ cam đang 'fail' -> 'pending'.
        2. Truyền mảng cams: Cập nhật các cam trong mảng -> 'pending' và gỡ server_id.
        """
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                cursor = conn.cursor()
                
                # Trường hợp 1: Không truyền params -> Update toàn bộ 'fail' thành 'pending'
                if cams is None:
                    cursor.execute(
                        "UPDATE cameras SET server_id = NULL, status = ? WHERE status = ?",
                        (state["pending"], state["fail"])
                    )
                    rowcount = cursor.rowcount 
                    conn.commit()
                    logger.info(f"Đã gom {rowcount} camera fail về lại pending để chờ chia.")
                    return
                
                # Trường hợp 2 & 3: Truyền danh sách cams (Rollback)
                if not cams:
                    return
                
                # Trích xuất ID từ mảng (Vì dữ liệu list có thể là Tuple lấy từ DB, hoặc Dict)
                cam_ids = []
                for cam in cams:
                    if isinstance(cam, dict):
                        cam_ids.append(cam.get("id") or cam.get("cam_id"))
                    elif isinstance(cam, (list, tuple)):
                        cam_ids.append(cam[0]) # Giả sử ID nằm ở index 0
                    else:
                        cam_ids.append(cam) # Trường hợp string nguyên bản

                if not cam_ids:
                    return

                # Build câu query an toàn với tham số IN động
                placeholders = ",".join(["?"] * len(cam_ids))
                query = f"UPDATE cameras SET status = ?, server_id = NULL WHERE cam_id IN ({placeholders})"
                
                params = [state["pending"]] + cam_ids
                cursor.execute(query, params)
                conn.commit()
                # logger.info(f"Đã Rollback {len(cam_ids)} camera về trạng thái pending.")
                
        except Exception as e:
            logger.error(f"Lỗi chuyển các camera về pending: {e}")
    
    @staticmethod
    def set_cam_fail(cams):
        """
        Nhận một mảng các camera bị lỗi, đưa tất cả về 'fail' và giải phóng Node.
        """
        if not cams: 
            return 
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                cursor = conn.cursor()
                
                cam_ids = []
                for cam in cams:
                    if isinstance(cam, dict):
                        cam_ids.append(cam.get("cam_id") or cam.get("id"))
                    elif isinstance(cam, (list, tuple)):
                        cam_ids.append(cam[0])
                    else:
                        cam_ids.append(cam)

                if not cam_ids: return

                data = [(state["fail"], c_id) for c_id in cam_ids]
                cursor.executemany("UPDATE cameras SET server_id = NULL, status = ? WHERE cam_id = ?", data)
                conn.commit()
                logger.info(f"Đã chuyển {len(cam_ids)} camera về trạng thái fail.")
                
        except Exception as e:
            logger.error(f"Lỗi đưa danh sách camera về fail: {e}")
            # Xóa đoạn tự động rollback về pending ở đây đi để tránh side-effect ngầm khó debug
    
    @staticmethod
    def set_cam_busy(cams, server_id=None):
        """
        Nhận một mảng camera, khóa tất cả lại sang trạng thái 'busy'.
        """
        if not cams:
            return
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                cursor = conn.cursor()
                
                # BỘ LỌC ID BẤT TỬ: Xử lý mọi loại dữ liệu đầu vào
                cam_ids = []
                for cam in cams:
                    if isinstance(cam, dict):
                        cam_ids.append(cam.get("cam_id") or cam.get("id"))
                    elif isinstance(cam, (list, tuple)):
                        cam_ids.append(cam[0])
                    else:
                        cam_ids.append(cam)
                        
                if not cam_ids:
                    return

                if server_id:
                    data = [(server_id, state["busy"], c_id) for c_id in cam_ids]
                    # Đổi WHERE id thành WHERE cam_id cho chuẩn Schema
                    cursor.executemany("UPDATE cameras SET server_id = ?, status = ? WHERE cam_id = ?", data)
                else:
                    data = [(state["busy"], c_id) for c_id in cam_ids]
                    cursor.executemany("UPDATE cameras SET status = ? WHERE cam_id = ?", data)
                    
                conn.commit()
                logger.info(f"Đã chuyển {len(cam_ids)} camera sang busy (server_id={server_id}).")
        except Exception as e:
            logger.error(f"Lỗi đưa danh sách camera sang trạng thái busy: {e}")
    
    @staticmethod
    def set_cam_online(cams):
        """
        Đưa danh sách camera về trạng thái online sau khi Server nhận chạy thành công.
        """
        if not cams: 
            return 
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                cursor = conn.cursor()
                
                cam_ids = []
                for cam in cams:
                    if isinstance(cam, dict):
                        cam_ids.append(cam.get("cam_id") or cam.get("id"))
                    elif isinstance(cam, (list, tuple)):
                        cam_ids.append(cam[0])
                    else:
                        cam_ids.append(cam)
                        
                if not cam_ids: return

                data = [(state["online"], c_id) for c_id in cam_ids]
                cursor.executemany("UPDATE cameras SET status = ? WHERE cam_id = ?", data)
                conn.commit()
                logger.info(f"Đã chuyển {len(cam_ids)} camera về trạng thái online.")
                
        except Exception as e:
            logger.error(f"Lỗi đưa danh sách camera về online: {e}")
    
    @staticmethod
    def get_cam_pending():
        """
        Quét DB lấy danh sách TẤT CẢ camera đang 'pending' để Master chia việc.
        Trả về: Một danh sách các dictionary chứa thông tin camera.
        """
        logger.debug(f"file {STATE_PATH}")
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                conn.row_factory = sqlite3.Row  # Trả về kết quả dưới dạng Dictionary
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM cameras WHERE status = ?", (state["pending"],))
                rows = cursor.fetchall()
                cam_list = [dict(row) for row in rows]
                logger.info(f"Đã lấy được {len(cam_list)} camera đang pending.")
                return cam_list
                
        except Exception as e:
            logger.error(f"Lỗi khi query danh sách camera pending: {e}")
            return []  # Lỗi thì trả về mảng rỗng để Master lặp qua không bị crash
    
    @staticmethod
    def get_cam_fail():
        """
        Lấy danh sách các camera đang 'fail' (chết link, rớt mạng, v.v.).
        Dùng để Master hiển thị lên log hoặc Admin CMS xử lý.
        """
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM cameras WHERE status = ?", (state["fail"],))
                rows = cursor.fetchall()
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Lỗi khi query danh sách camera fail: {e}")
            return []
    
    @staticmethod
    def get_cam_busy(server_id=None):
        """
        Lấy danh sách các camera đang 'busy'.
        Nếu truyền server_id: Chỉ lấy của server đó.
        Nếu không truyền: Lấy toàn bộ.
        """
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                if server_id is None:
                    cursor.execute("SELECT * FROM cameras WHERE status = ?", (state["busy"],))
                else:
                    cursor.execute("SELECT * FROM cameras WHERE status = ? AND server_id = ?", (state["busy"], server_id))
                    
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Lỗi khi query danh sách camera busy: {e}")
            return []

    @staticmethod
    def get_cam_busy(server_id):
        """
        Lấy danh sách các camera đang 'busy' (đã được giao cho Node nhưng chưa xác nhận hoặc đang chạy).
        """
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM cameras WHERE status = ? and server_id = ?", (state["busy"], server_id))
                rows = cursor.fetchall()
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Lỗi khi query danh sách camera busy: {e}")
            return []      