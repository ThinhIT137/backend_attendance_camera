import logging
# Tạo logger cục bộ cho file này (nó sẽ tự thừa kế cấu hình Root ở app.py / main.py)
logger = logging.getLogger(__name__)
import threading
import os
import time
from collections import deque
from datetime import datetime
import sqlite3
import requests
import json
from dotenv import load_dotenv, set_key

from config.settings import CAMERA_DB
from db.camRepository import CamRepository
from db.serverAIRepository import ServerAIRepository

load_dotenv()
DEAD_SERVERS = {} 
MASTER_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state.json")
with open(STATE_PATH, encoding="utf-8") as f:
    state = json.load(f)
# =======================================================
# 1. QUẢN LÝ TRẠNG THÁI SERVER
# =======================================================
def update_server_status(data):
    """Ghi nhận nhịp tim và toàn bộ thông số phần cứng từ Worker gửi lên"""
    logger.debug(f"{data}")
    server_id = data.get('server_id')
    
    # Lấy dữ liệu phần cứng (có fallback mặc định nếu Worker gửi thiếu)
    cpu_usage = data.get('cpu_usage', 0.0)
    has_gpu = 1 if data.get('has_gpu') else 0  # SQLite chuộng 1/0 thay vì True/False
    vram_free_gb = data.get('vram_free_gb', 0.0)
    max_cam = data.get('max_cam', 0.0)
    
    last_heartbeat = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(CAMERA_DB) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM cameras WHERE server_id = ?", (server_id,))
        real_active_cam = cursor.fetchone()[0]
        # UPDATE toàn tập: Từ trạng thái, thời gian cho đến thông số CPU/GPU
        cursor.execute("""
            UPDATE ai_servers 
            SET status = CASE 
                            WHEN ? < ? THEN 'pending' 
                            ELSE 'online' 
                         END, 
                active_cam = ?,
                last_heartbeat = ?,
                cpu_usage = ?,
                has_gpu = ?,
                vram_free_gb = ?,
                max_cam = ?
            WHERE server_id = ?
        """, (real_active_cam, max_cam, real_active_cam, last_heartbeat, cpu_usage, has_gpu, vram_free_gb, max_cam, server_id))
        
        # Báo log ra Terminal nếu có một thằng Worker lạ hoắc không có trong DB mà cứ gửi nhịp tim
        if cursor.rowcount == 0:
            print(f"⚠️ [MASTER CẢNH BÁO] Có nhịp tim từ Server lạ (ID: {server_id}). Hãy thêm nó vào giao diện Admin!")
            
        conn.commit()

def mark_server_dead(sv_id, sv_ip):
    if sv_id not in DEAD_SERVERS:
        DEAD_SERVERS[sv_id] = sv_ip
        print(f"⚠️ {sv_id} đã bị đưa vào Sổ Tử!")

def check_dead_servers():
    while True:
        for sv_id, sv_ip in list(DEAD_SERVERS.items()):
            try:
                res = requests.get(f"http://{sv_ip}/api/ping", timeout=2)
                if res.status_code == 200:
                    print(f"🎉 {sv_id} đã sống lại!")
                    update_server_status(sv_id, 'online')
                    del DEAD_SERVERS[sv_id] 
            except requests.exceptions.RequestException:
                pass 
        time.sleep(5)

def detect_dead_servers():
    """Tử thần đi tuần: Quét các server đang online, nếu mất tim sẽ ném vào Sổ Tử"""
    print("💀 [TỬ THẦN] Đã bắt đầu đi tuần tra nhịp tim Server...")
    while True:
        try:
            with sqlite3.connect(CAMERA_DB) as conn:
                cursor = conn.cursor()
                # Chỉ soi mấy thằng đang mang tiếng là còn sống (online hoặc pending)
                cursor.execute("""
                    SELECT server_id, ip_address, last_heartbeat 
                    FROM ai_servers 
                    WHERE status IN ('online', 'pending')
                """)
                servers = cursor.fetchall()
                current_time = datetime.now()
                for sv_id, sv_ip, last_hb_str in servers:
                    if not last_hb_str:
                        continue
                    # Chuyển giờ trong DB thành đối tượng datetime để tính toán
                    # (Lưu ý: Format này phải khớp với format lúc sếp lưu ở hàm receive_heartbeat nhé)
                    last_hb = datetime.strptime(last_hb_str, "%Y-%m-%d %H:%M:%S")
                    diff_seconds = (current_time - last_hb).total_seconds()
                    # Nếu tim ngừng đập quá 15 giây
                    if diff_seconds > 15:
                        print(f"💀 [BÁO TỬ] Server {sv_id} đã mất tích ({int(diff_seconds)}s không phản hồi)!")
                        # 1. Update DB thành offline, giải phóng tài nguyên ngay lập tức
                        cursor.execute("UPDATE ai_servers SET status = 'offline', active_cam = 0 WHERE server_id = ?", (sv_id,))
                        cursor.execute("UPDATE cameras SET server_id = NULL, status = 'pending' WHERE server_id = ?", (sv_id,))    
                        conn.commit()
                        # 2. Ghi tên vào Sổ Tử cho bác sĩ đi chích điện cấp cứu!
                        mark_server_dead(sv_id, sv_ip)
        except Exception as e:
            conn.rollback()
            print(f"⚠️ Lỗi khi Tử Thần đi tuần: {e}")
        time.sleep(10) # 10 giây đi lùa 1 lần cho nhẹ máy

def start_server_monitor():
    threading.Thread(target=detect_dead_servers, daemon=True).start()
    threading.Thread(target=check_dead_servers, daemon=True).start()
    print("🔍 Đã bật luồng tuần tra Server YOLO!")

# =======================================================
# 2. KHỞI ĐỘNG APP: PHÂN PHÁT TÀI NGUYÊN (CHỈ CHẠY 1 LẦN)
# =======================================================
def no_pending_is_fail_cams():
    fail_Cams = CamRepository.get_cam_fail()
    if not fail_Cams:
        return []
    # có cam fail thì lấy cam fail check tiếp nhỡ nó sống lại
    CamRepository.set_cam_pending(fail_Cams)
    return CamRepository.get_cam_pending()

def auto_rebalance_cameras():
    """Hàm tuần tra bằng DEQUE (O(1)): Chia bài tốc độ bàn thờ"""
    try:
        # 1. LẤY CAMERA CẦN CHIA
        pending_cams = list(CamRepository.get_cam_pending())
        cams_queue = deque(pending_cams)
        if not pending_cams:
            pending_cams = list(no_pending_is_fail_cams())
            
        if not pending_cams:
            return  
            
        logger.debug(f"[🔄] Phát hiện {len(pending_cams)} Camera bơ vơ. Bắt đầu chia lại bài...")

        # 2. LẤY SERVER & LỌC NHỮNG THẰNG CÒN SLOT
        pending_servers = ServerAIRepository.get_server_pending()
        if not pending_servers:
            logger.info("[❌] Không có server nào đang rảnh để chia...")
            return
            
        server_list = []
        for s in pending_servers:
            # 🛠️ FIX BOM SỐ 3: Bóc data từ sqlite3.Row bằng Key chuẩn để không lộn cột
            try:
                max_c = s["max_cam"]
                act_c = s["active_cam"]
                sv_id = s["server_id"]
                sv_ip = s["ip_address"]
            except Exception:
                # Dự phòng nếu s là Tuple thuần
                max_c = s[6]
                act_c = s[5]
                sv_id = s[0]
                sv_ip = s[1]
                
            cam_size = max_c - act_c
            if cam_size > 0:
                server_list.append({
                    "id": sv_id,
                    "ip": sv_ip,
                    "newly_assigned": [],
                    "cam_size": cam_size,
                    "is_changed": False
                })

        servers_queue = deque(server_list)
        camera_rollback_fail = []
        
        # 3. CHIA BÀI BẰNG HÀNG ĐỢI (O(1))
        while cams_queue:
            if not servers_queue:
                logger.warning(f"[⚠️] Hết chỗ! Dư {len(cams_queue)} camera không có ai nhận.")
                break
                
            sv = servers_queue.popleft()
            sv["newly_assigned"].append(cams_queue.popleft())
            sv["is_changed"] = True
            sv["cam_size"] -= 1  
            
            if sv["cam_size"] > 0:
                servers_queue.append(sv)

        server_ready = [sv for sv in server_list if sv["is_changed"]]
        
        # 4. GIAO VIỆC VÀ CHỐT SỔ
        try:
            servers_to_online = []
            for sv in server_ready:
                CamRepository.set_cam_busy(sv["newly_assigned"], sv["id"])
                
            for sv in server_ready:
                # 🛠️ FIX BOM SỐ 1: Bóc bằng Key get() chứ không dùng index row[0]
                cam_payload = []
                for row in sv["newly_assigned"]:
                    cam_id = row.get("cam_id") or row.get("id")
                    cam_url = row.get("rtsp_url") or row.get("url")
                    cam_payload.append({"id": cam_id, "url": cam_url})
                
                # 🛠️ FIX BOM SỐ 2: Xử lý vụ URL bị lặp http://
                base_url = sv['ip']
                if not base_url.startswith("http"):
                    base_url = f"http://{base_url}"
                    
                res = requests.post(f"{base_url}/api/sync_cameras", json={"cameras": cam_payload}, timeout=60)
                if res.status_code == 200:
                    data = res.json()
                    accepted = data.get("accepted", [])
                    rejected = data.get("rejected", [])

                    print(f"✅ Server {sv['id']} báo cáo: Nhận {len(accepted)} cam, Trả {len(rejected)} cam.")
                    
                    if accepted:
                        CamRepository.set_cam_online(accepted)
                        # Đã bọc mảng [] để chống vụ bị xé string
                        servers_to_online.append(sv["id"])
                    
                    if rejected:
                        CamRepository.set_cam_fail(rejected)
            if servers_to_online:
                ServerAIRepository.set_servers_online(servers_to_online)

        except Exception as e:
            # 💡 Bắt tận tay loại Lỗi: e.__class__.__name__ (Sẽ hiện KeyError/ConnectionError thay vì số 0 vô tri)
            logger.error(f"[⚠️] Lỗi mạng khi bắn API tới Worker: {e.__class__.__name__} - {e}. Tiến hành Rollback!")
            for sv in server_ready:
                CamRepository.set_cam_pending(sv["newly_assigned"], sv["id"])
            if camera_rollback_fail:
                CamRepository.set_cam_fail(camera_rollback_fail)
                
        if camera_rollback_fail:
            CamRepository.set_cam_fail(camera_rollback_fail)

    except Exception as e:
        logger.error(f"❌ Lỗi ở bộ điều phối trung tâm: {e}")

# HÀM KHỞI ĐỘNG VÒNG LẶP CHẠY NGẦM VĨNH VIỄN
def start_watchdog():
    def loop():
        while True:
            auto_rebalance_cameras()
            time.sleep(10) # 10 giây đi quét 1 lần

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print("🚁 [WATCHDOG] Cảnh sát trưởng đã vào ca trực! Tự động chia bài mỗi 10 giây...")
# =======================================================
# 3. CÁC HÀM BẮN TỈA: THÊM 1 / SỬA 1 / XÓA 1
# =======================================================
def add_single_camera(cam_id, rtsp_url):
    """(THÊM CAMERA): Tìm Server rảnh nhất, nhét nó vào DB, rồi ép Server đó Sync lại"""
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            # 1. Tìm thằng rảnh nhất
            cursor.execute("""
                SELECT server_id, ip_address FROM ai_servers 
                WHERE status = 'online' 
                ORDER BY (vram_free_gb) DESC, cpu_usage ASC LIMIT 1
            """)
            server = cursor.fetchone()
            
            if not server:
                return {"success": False, "message": "Hết Server rảnh! Camera bị Pending."}
            
            sv_id, sv_ip = server[0], server[1]
            
            # 2. Cập nhật DB: Chốt giao Camera này cho Server đó
            cursor.execute("UPDATE cameras SET server_id = ?, rtsp_url = ?, status = 'running' WHERE cam_id = ?", (sv_id, rtsp_url, cam_id))
            conn.commit()
            
            # 3. Kích hoạt Sync Cục Bộ (Chỉ thằng này bị Restart YOLO)
            if _sync_single_worker(sv_id, sv_ip):
                return {"success": True, "message": f"Đã nhét Cam vào {sv_id} thành công!"}
            return {"success": False, "message": "Lỗi kết nối xuống Worker."}
    except Exception as e:
        return {"success": False, "message": str(e)}

def update_single_camera(cam_id, new_rtsp_url):
    """(SỬA IP CAMERA): Tìm xem nó đang ở Server nào, update DB, rồi ép Server đó Sync lại"""
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            # 1. Cập nhật IP mới vào DB và lấy thông tin Server đang gánh nó
            cursor.execute("UPDATE cameras SET rtsp_url = ? WHERE cam_id = ?", (new_rtsp_url, cam_id))
            
            cursor.execute("""
                SELECT a.server_id, a.ip_address 
                FROM cameras c JOIN ai_servers a ON c.server_id = a.server_id 
                WHERE c.cam_id = ?
            """, (cam_id,))
            row = cursor.fetchone()
            conn.commit()
            
            if not row:
                return {"success": True, "message": "Đã sửa DB. Nhưng cam này đang Pending chưa chạy."}
                
            sv_id, sv_ip = row[0], row[1]
            
            # 2. Ép đúng con Server đó Sync lại để nhận Link RTSP mới
            _sync_single_worker(sv_id, sv_ip)
            return {"success": True, "message": "Đã đổi IP và khởi động lại luồng AI!"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def delete_single_camera(cam_id):
    """(XÓA CAMERA): Gạch tên khỏi DB, rồi ép con Server đang gánh nó Sync lại (Đá cam ra khỏi lô)"""
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            # 1. Lấy thông tin Server đang gánh
            cursor.execute("""
                SELECT a.server_id, a.ip_address 
                FROM cameras c JOIN ai_servers a ON c.server_id = a.server_id 
                WHERE c.cam_id = ?
            """, (cam_id,))
            row = cursor.fetchone()
            
            # 2. Xóa khỏi DB (Hoặc chuyển status thành 'disabled')
            cursor.execute("DELETE FROM cameras WHERE cam_id = ?", (cam_id,))
            conn.commit()
            
            # 3. Nếu nó đang chạy trên 1 server, bắt server đó Sync lại để vứt luồng cũ đi
            if row:
                sv_id, sv_ip = row[0], row[1]
                _sync_single_worker(sv_id, sv_ip)
                
            return {"success": True, "message": "Đã xóa Camera."}
    except Exception as e:
        return {"success": False, "message": str(e)}

# =======================================================
# 4. CÁC HÀM CRUD QUẢN LÝ SERVER YOLO (Cho Frontend)
# =======================================================
def get_ip_server():
    """Lấy danh sách toàn bộ Server YOLO"""
    with sqlite3.connect(CAMERA_DB) as conn:
        cursor = conn.cursor()
        # Bỏ max_cam đi vì DB không còn cột này nữa
        cursor.execute("""
            SELECT server_id, ip_address, status, active_cam 
            FROM ai_servers
        """)
        rows = cursor.fetchall()
        
        servers = []
        for row in rows:
            servers.append({
                "id": row[0],
                "ip": row[1],
                "status": row[2],
                "activeCam": row[3]
            })
        return servers

def add_new_server(ip_address):
    with sqlite3.connect(CAMERA_DB) as conn:
        cursor = conn.cursor()
        
        # 1. Tùy chọn: Chống trùng IP (1 IP không thể tạo 2 Server)
        cursor.execute("SELECT server_id FROM ai_servers WHERE ip_address = ?", (ip_address,))
        if cursor.fetchone():
            raise ValueError(f"Đường dẫn IP '{ip_address}' đã được cấp cho một Server khác rồi!")

        # 2. Quét toàn bộ DB để tìm số thứ tự lớn nhất
        cursor.execute("SELECT server_id FROM ai_servers")
        rows = cursor.fetchall()
        
        max_num = 0
        for row in rows:
            sv_id = row[0] # Lấy ra dạng 'SV_001', 'SV_011'
            if sv_id.startswith("SV_"):
                try:
                    # Cắt chuỗi lấy phần số ở sau chữ "SV_"
                    num = int(sv_id.split("_")[1])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        
        # 3. Tự động sinh ID mới (Cộng thêm 1 và đệm đủ 3 số 0)
        # 1 -> SV_001, 11 -> SV_011, 111 -> SV_111
        new_server_id = f"SV_{max_num + 1:03d}"
        
        # 4. Insert thẳng vào DB
        cursor.execute("""
            INSERT INTO ai_servers (server_id, ip_address, status)
            VALUES (?, ?, 'pending')
        """, (new_server_id, ip_address))
        
        conn.commit()
        
        # Trả về cái tên vừa tạo để thông báo
        return new_server_id

def update_server_info(ip_address, server_id):
    """Cập nhật thông tin Server (Chỉ cho phép đổi IP)"""
    with sqlite3.connect(CAMERA_DB) as conn:
        cursor = conn.cursor()
        # Kiểm tra chống trùng IP với máy khác (Trừ chính nó)
        cursor.execute("SELECT server_id FROM ai_servers WHERE ip_address = ? AND server_id != ?", (ip_address, server_id))
        if cursor.fetchone():
            raise ValueError(f"IP '{ip_address}' đã bị trùng với một Server khác!")

        cursor.execute("""
            UPDATE ai_servers 
            SET ip_address = ? 
            WHERE server_id = ?
        """, (ip_address, server_id))
        conn.commit()

def delete_server_by_id(server_id):
    """Xóa Server khỏi hệ thống"""
    with sqlite3.connect(CAMERA_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ai_servers WHERE server_id = ?", (server_id,))
        # Giải phóng các camera đang cắm vào server bị xóa
        cursor.execute("UPDATE cameras SET server_id = NULL, status = 'pending' WHERE server_id = ?", (server_id,))
        conn.commit()
# =======================================================
# 5. HÀM KHỞI ĐỘNG THÊM SỬA XÓA CAMERA ĐƯA XUỐNG SERVER YOLO
# =======================================================
def sync_cameras_to_workers():
    """Hàm này sẽ được Master gọi khi: Khởi động app, hoặc khi sếp Thêm/Xóa Camera trên Web"""
    print("🚀 [MASTER] Bắt đầu chia bài cho các Server YOLO...")
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            
            # 1. Lấy list Server đang sống
            cursor.execute("""
                SELECT server_id, ip_address, has_gpu, vram_free_gb, cpu_usage 
                FROM ai_servers 
                WHERE status = 'online'
            """)
            alive_servers = cursor.fetchall()

            if not alive_servers:
                print("⚠️ [MASTER] Bỏ qua: Không có Server YOLO nào online.")
                return

            # Chuyển thành list dict để Master dễ tính toán Trừ Ảo
            servers = [
                {
                    "id": s[0], 
                    "ip": s[1], # Ví dụ: "127.0.0.1" hoặc "10.40.90.1"
                    "has_gpu": bool(s[2]), 
                    "vram": s[3], 
                    "cpu": s[4], 
                    "assigned_cams": [] # Rổ chứa camera được giao
                } 
                for s in alive_servers
            ]

            # 2. Lấy toàn bộ camera đang cần chạy
            cursor.execute("SELECT cam_id, rtsp_url FROM cameras") # Tùy logic DB sếp thêm điều kiện status nhé
            cameras = cursor.fetchall()

            # 3. THUẬT TOÁN CHIA BÀI VÀ TRỪ ẢO CHO MASTER
            for cam in cameras:
                cam_id, rtsp_url = cam[0], cam[1]
                
                # Sắp xếp Server: Ưu tiên có GPU -> Nhiều VRAM trống nhất -> Ít CPU nhất
                servers.sort(key=lambda x: (not x["has_gpu"], -x["vram"], x["cpu"]))
                best_server = servers[0] # Chọn thằng đứng đầu tiên (Khỏe nhất)
                
                # Bỏ camera vào rổ của server đó
                best_server["assigned_cams"].append({"id": cam_id, "url": rtsp_url})
                
                # Trừ ảo tài nguyên trong não Master để chia đều cho thằng khác
                if best_server["has_gpu"]:
                    best_server["vram"] -= 0.4 # Trừ ảo 400MB VRAM
                else:
                    best_server["cpu"] += 20.0 # Trừ ảo 20% CPU

            # 4. BẮN LỆNH (CÁC RỔ CAMERA) XUỐNG TỪNG CON WORKER NODE
            for sv in servers:
                sv_id = sv["id"]
                sv_ip = sv["ip"]
                cams = sv["assigned_cams"] # Rổ camera của thằng này
                
                try:
                    # Gọi API của con Worker (Worker chạy FastAPI port 8000)
                    print(f"🎯 [MASTER] Đang gửi {len(cams)} Camera xuống Server {sv_id} ({sv_ip})")
                    
                    # Gọi trúng cái API /api/sync_cameras sếp vừa viết bên Worker đó!
                    res = requests.post(f"http://{sv_ip}/api/sync_cameras", json={"cameras": cams}, timeout=45)
                    
                    if res.status_code == 200:
                        print(f"✅ [MASTER] Giao việc thành công cho {sv_id}!")
                        # Tiện tay cập nhật DB luôn: Ghi nhận các cam này đang chạy trên server nào
                        for c in cams:
                            cursor.execute("UPDATE cameras SET server_id = ?, status = 'running' WHERE cam_id = ?", (sv_id, c["id"]))
                    else:
                        print(f"❌ [MASTER] Server {sv_id} từ chối lệnh.")
                except Exception:
                    print(f"❌ [MASTER] Chết kết nối tới Server {sv_id} lúc chia bài.")

            conn.commit()
    except Exception as e:
        print(f"❌ [MASTER] Lỗi logic chia bài: {e}")

def _sync_single_worker(server_id, sv_ip):
    """HÀM NỘI BỘ: Chỉ gom các camera của RIÊNG 1 server và ép nó khởi động lại"""
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            # Lấy đúng những cam đang được giao cho Server này
            cursor.execute("SELECT cam_id, rtsp_url FROM cameras WHERE server_id = ? AND status != 'disabled'", (server_id,))
            cams = cursor.fetchall()
            
            payload = {"cameras": [{"id": c[0], "url": c[1]} for c in cams]}
            
            print(f"🎯 [MASTER] Đang Sync cục bộ {len(cams)} Cam cho Server {server_id}...")
            res = requests.post(f"http://{sv_ip}/api/sync_cameras", json=payload, timeout=45)
            
            if res.status_code == 200:
                print(f"✅ [MASTER] Server {server_id} đã Sync cục bộ thành công!")
                return True
            return False
    except Exception as e:
        print(f"❌ [MASTER ERROR] Lỗi Sync cục bộ Server {server_id}: {e}")
        return False
# =======================================================
# 6. HÀM ĐƯA IP CỦA MASTER_NODE XUỐNG CHO SERVER_NODE
# =======================================================
def broadcast_my_url_to_all_workers():
    """Lấy IP và Port từ .env, ráp lại và báo cho đàn em"""
    ip = os.getenv("MASTER_NODE_IP")
    port = os.getenv("MASTER_NODE_PORT", "5000") # Mặc định 5000 nếu không ghi
    
    if not ip or ip == "0.0.0.0":
        print("⚠️ [MASTER] Đang dùng IP 0.0.0.0 hoặc chưa có IP. Worker sẽ không tìm được đường về! Vui lòng set IP thật trong .env")
        return

    # Ráp thành URL hoàn chỉnh
    my_master_url = f"http://{ip}:{port}"
    print(f"📢 [MASTER] Bắt đầu thông báo IP mới ({my_master_url}) cho các Worker...")
    
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT server_id, ip_address FROM ai_servers")
            workers = cursor.fetchall()
            
        for sv_id, sv_ip in workers:
            try:
                # Bắn URL hoàn chỉnh xuống Worker
                requests.post(f"http://{sv_ip}/api/update_master_url", 
                              json={
                                  "new_master_url": my_master_url,
                                  "server_id": sv_id   
                              }, 
                              timeout=3)
                print(f"✅ [MASTER] Đã cập nhật IP Master cho Worker {sv_id}")
            except requests.exceptions.RequestException:
                print(f"❌ [MASTER] Không gọi được Worker {sv_id} ({sv_ip})")
    except Exception as e:
        print(f"❌ Lỗi khi broadcast: {e}")

def update_and_broadcast_master_config(new_ip, new_port):
    """
    Hàm lõi: Vừa lưu IP/Port mới của Master vào .env, vừa ép dàn em dưới nhận lệnh đổi IP
    """
    # 1. Ghi đè vào file .env của con Master để lần sau khởi động không bị mất
    set_key(MASTER_ENV_PATH, "MASTER_NODE_IP", str(new_ip))
    set_key(MASTER_ENV_PATH, "MASTER_NODE_PORT", str(new_port))
    
    # Đồng thời cập nhật luôn vào môi trường RAM hiện tại của Master
    os.environ["MASTER_NODE_IP"] = str(new_ip)
    os.environ["MASTER_NODE_PORT"] = str(new_port)
    
    my_new_url = f"http://{new_ip}:{new_port}"
    print(f"📢 [MASTER CONFIG CHANGED] Đã lưu IP mới: {my_new_url}. Tiến hành phát sóng...")

    # 2. Móc từ DB ra toàn bộ dàn Worker Node đang chạy
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT server_id, ip_address FROM ai_servers")
            workers = cursor.fetchall()
    except Exception as e:
        print(f"❌ Lỗi truy vấn danh sách AI Server: {e}")
        return {"success": False, "message": f"Lỗi DB: {str(e)}"}

    success_nodes = []
    failed_nodes = []

    # 3. Duyệt danh sách và ép các con Worker Node chuyển hướng nhịp tim
    for sv_id, sv_ip in workers:
        try:
            # Gọi đến API của Worker (Port 8000 của FastAPI)
            res = requests.post(
                f"http://{sv_ip}/api/update_master_url", 
                json={"new_master_url": my_new_url}, 
                timeout=3
            )
            if res.status_code == 200:
                success_nodes.append(sv_id)
            else:
                failed_nodes.append(sv_id)
        except requests.exceptions.RequestException:
            failed_nodes.append(sv_id)

    return {
        "success": True,
        "master_url": my_new_url,
        "synced_workers": success_nodes,
        "failed_workers": failed_nodes
    }

def set_server_offline_gracefully(server_id):
    """Hàm xử lý khi Worker chủ động báo tắt máy"""
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            # 1. Đánh dấu Server này sập nguồn
            cursor.execute("UPDATE ai_servers SET status = 'offline', active_cam = 0 WHERE server_id = ?", (server_id,))
            
            # 2. Xả toàn bộ Camera nó đang gánh về trạng thái pending
            cursor.execute("UPDATE cameras SET server_id = NULL, status = 'pending' WHERE server_id = ?", (server_id,))
            
            conn.commit()
            print(f"🛑 [MASTER] Nhận tin báo tử từ {server_id}. Đã gỡ toàn bộ Camera để Watchdog chia lại!")
    except Exception as e:
        print(f"❌ Lỗi khi xử lý server offline: {e}")