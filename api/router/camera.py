import sqlite3
from flask import Blueprint, request, jsonify
from config.settings import CAMERA_DB
# Thay vì import mấy hàm bắn tỉa cũ, ta import hàm Sync Bom B52 mới
from services.server_yolo_service import sync_cameras_to_workers
from services.camera_service import generate_camera_id

camera_bp = Blueprint('camera', __name__)

# [HÀM GET camera]
@camera_bp.route('/api/cameras', methods=['GET'])
def get_all_cameras():
    try:
        # Lấy IP của server hiện tại đang chạy Flask (cắt bỏ phần port 5000)
        host_ip = request.host.split(':')[0]
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            # Sếp lưu ý: Nếu trong DB có sẵn cột ws_port thì sếp thêm vào SELECT nhé.
            # Ví dụ: SELECT cam_id, name, rtsp_url, server_id, status, ws_port FROM cameras
            cursor.execute("SELECT cam_id, name, rtsp_url, server_id, status FROM cameras")
            rows = cursor.fetchall()
            cameras = []
            for r in rows:
                cam_id = r[0] # Lấy cam_id ra để tái sử dụng cho url
                cameras.append({
                    "id": cam_id,                                # Đổi key 'cam_id' thành 'id' chuẩn Frontend
                    "name": r[1],
                    "url": f"http://{host_ip}:8889/{cam_id}/",   # Tự động build WebRTC URL
                    "ws_port": 8000                              # ⚠️ Nhớ thay 8000 bằng logic lấy ws_port của sếp!
                })
        return jsonify(cameras)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# [HÀM ADD] - Dùng Sync
@camera_bp.route('/api/cameras', methods=['POST'])
def add_camera():
    data = request.json
    name = data.get('name')
    rtsp_url = data.get('rtsp_url')
    
    if not name or not rtsp_url:
        return jsonify({"error": "Thiếu thông tin!"}), 400

    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            # 1. Tự sinh ID theo format camera_XX
            new_cam_id = generate_camera_id(conn)
            
            # 2. Insert với ID đã sinh
            cursor = conn.cursor()
            cursor.execute("INSERT INTO cameras (cam_id, name, rtsp_url, status) VALUES (?, ?, ?, 'pending')", 
                           (new_cam_id, name, rtsp_url))
            conn.commit()
        
        # 3. Gọi Bom B52 đồng bộ
        sync_cameras_to_workers()
        
        return jsonify({
            "success": True, 
            "message": "Đã thêm Camera!", 
            "cam_id": new_cam_id
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# [HÀM UPDATE] - Dùng Sync
@camera_bp.route('/api/cameras/<string:cam_id>', methods=['PUT'])
def update_camera(cam_id):
    data = request.json
    new_name, new_rtsp_url = data.get('name'), data.get('rtsp_url')

    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE cameras SET name = ?, rtsp_url = ? WHERE cam_id = ?", (new_name, new_rtsp_url, cam_id))
            conn.commit()
            
        # Ép đồng bộ lại. Nó sẽ tự lấy link mới nhất từ DB
        sync_cameras_to_workers()
        return jsonify({"message": "Cập nhật thành công, đang đồng bộ lại luồng AI!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# [HÀM DELETE] - Dùng Sync
@camera_bp.route('/api/cameras/<string:cam_id>', methods=['DELETE'])
def delete_camera(cam_id):
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cameras WHERE cam_id = ?", (cam_id,))
            conn.commit()
            
        # Ép đồng bộ lại để Worker biết là cam này đã bị loại khỏi lô
        sync_cameras_to_workers()
        return jsonify({"message": "Đã xóa Camera và đồng bộ lại tiến trình AI!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500