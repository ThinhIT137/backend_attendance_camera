import requests
from flask import Blueprint, request, jsonify
from datetime import datetime
import sqlite3

# 🌟 Import các hàm nghiệp vụ từ Service
from services.server_yolo_service import update_server_status, mark_server_dead, get_ip_server, delete_server_by_id, add_new_server, update_server_info, update_and_broadcast_master_config
from services.server_yolo_service import set_server_offline_gracefully
from config.settings import CAMERA_DB

# Đổi tên Blueprint cho đúng ngữ cảnh
server_yolo_bp = Blueprint('server_yolo', __name__)

# =======================================================
# API ĐỂ ThEO DÕI NHỊP TIM CỦA SERVER YOLO
# =======================================================
@server_yolo_bp.route('/api/heartbeat', methods=['POST'])
def receive_heartbeat():
    data = request.json
    print(f"{data}")
    if not data or 'server_id' not in data:
        return jsonify({"error": "Thiếu dữ liệu server_id"}), 400
    try:
        # Ném toàn bộ Dictionary JSON (data) sang cho Service xử lý
        update_server_status(data)
        return jsonify({"status": "success", "message": "Master đã ghi nhận!"}), 200
    except Exception as e:
        print(f"❌ [MASTER] Lỗi khi nhận nhịp tim: {e}")
        return jsonify({"error": str(e)}), 500

# =======================================================
# API ĐỂ FRONTEND MÉC MASTER
# =======================================================
@server_yolo_bp.route('/api/report_dead', methods=['POST'])
def report_dead():
    data = request.json
    sv_id = data.get('server_id')
    sv_ip = data.get('ip_address')
    
    if not sv_id or not sv_ip:
        return jsonify({"status": "error", "message": "Thiếu thông tin Server!"}), 400

    # MASTER XÁC MINH CHÉO
    try:
        # Chỉnh timeout nhỏ thôi để không bị treo Master
        res = requests.get(f"http://{sv_ip}:8000/api/ping", timeout=2)
        if res.status_code == 200:
            return jsonify({"status": "alive", "message": "Nó vẫn sống mà, do mạng của mày đó Frontend!"})
    except requests.exceptions.RequestException:
        # 1. Thằng này hẹo thật rồi -> Gọi hàm Service để tắt nó trong DB
        update_server_status(sv_id, 'offline')
        # 2. Gọi hàm Service để nhét nó vào danh sách "Chờ hồi sinh"
        mark_server_dead(sv_id, sv_ip)
        return jsonify({"status": "dead", "message": "Xác nhận đã hẹo, tao đã gạch tên nó!"})

# =======================================================
# [GET] Lấy danh sách 
# =======================================================
@server_yolo_bp.route('/api/servers', methods=['GET'])
def fetch_servers():
    try:
        servers = get_ip_server()
        return jsonify(servers)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# =======================================================
# [POST] Thêm Server mới
# =======================================================
@server_yolo_bp.route('/api/servers', methods=['POST'])
def create_server():
    data = request.json
    # Chỉ cần nhận IP thôi
    ip_address = data.get('ip_address') or data.get('ip')
    if not ip_address:
        return jsonify({"error": "Vui lòng cung cấp ip_address!"}), 400
    try:
        # Gọi hàm tạo, hàm này sẽ trả về ID tự sinh (VD: SV_003)
        new_id = add_new_server(ip_address)
        return jsonify({
            "status": "success", 
            "message": f"Tạo Server tự động thành công với mã: {new_id}!",
            "server_id": new_id
        }), 201
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Lỗi DB: {str(e)}"}), 500
# =======================================================
# [PUT] Cập nhật Server
# =======================================================
@server_yolo_bp.route('/api/servers/<string:server_id>', methods=['PUT'])
def update_server(server_id):
    data = request.json
    # Lấy IP an toàn
    ip_address = data.get('ip_address') or data.get('ip')
    if not ip_address:
        return jsonify({"status": "error", "message": "Vui lòng cung cấp IP mới!"}), 400
    try:
        # Chỉ gọi hàm update IP, giữ nguyên ID gốc (server_id) từ URL
        update_server_info(ip_address, server_id)
        return jsonify({
            "status": "success", 
            "message": f"Cập nhật IP cho {server_id} thành công!"
        }), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Lỗi hệ thống: {str(e)}"}), 500
# =======================================================
# [DELETE] Xóa Server
# =======================================================
@server_yolo_bp.route('/api/servers/<string:server_id>', methods=['DELETE'])
def remove_server(server_id):
    try:
        delete_server_by_id(server_id)
        return jsonify({
            "status": "success", 
            "message": f"Đã tiễn {server_id} về nơi an nghỉ!"
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"Không thể xóa: {str(e)}"}), 500
# =======================================================
# [POST] sửa ip xuống node 
# =======================================================
@server_yolo_bp.route('/api/system/change_master_network', methods=['POST'])
def change_master_network():
    """
    API tiếp nhận IP/Port mới từ giao diện Web, lưu lại và đồng bộ xuống các node con tức thì
    """
    data = request.json
    if not data or 'master_ip' not in data:
        return jsonify({"status": "error", "message": "Thiếu thông tin Master IP!"}), 400
        
    new_ip = data.get('master_ip')
    # Nếu Frontend không truyền port thì mặc định lấy port 5000 đang chạy
    new_port = data.get('master_port', 5000) 
    
    if new_ip == "0.0.0.0":
        return jsonify({"status": "error", "message": "Không được dùng IP 0.0.0.0 để đồng bộ xuống Worker!"}), 400

    # Gọi hàm nghiệp vụ xử lý "Bom B52" xả lệnh xuống các con dưới
    result = update_and_broadcast_master_config(new_ip, new_port)
    
    if result.get("success"):
        return jsonify({
            "status": "success",
            "message": f"Hệ thống đã chuyển nhà thành công sang {result['master_url']}!",
            "details": {
                "updated_workers_count": len(result['synced_workers']),
                "unreachable_workers_count": len(result['failed_workers']),
                "failed_list": result['failed_workers']
            }
        }), 200
    else:
        return jsonify({"status": "error", "message": result.get("message")}), 500

# Lắng nghe lời trăng trối của Worker
@server_yolo_bp.route('/api/servers/offline', methods=['POST'])
def handle_server_offline():
    data = request.json
    server_id = data.get('server_id')
    
    if not server_id:
        return jsonify({"status": "error", "message": "Thiếu server_id"}), 400
        
    try:
        set_server_offline_gracefully(server_id)
        return jsonify({"status": "success", "message": "Master đã nhận tin báo tử!"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500