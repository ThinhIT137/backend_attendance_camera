import os
import psutil
import time
import subprocess
import sqlite3
from ruamel.yaml import YAML

# 1. Trỏ đường dẫn tuyệt đối
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_NODE_DIR = os.path.dirname(CURRENT_DIR) 

# Đảm bảo thư mục lưu DB tồn tại (Tránh lỗi sai đường dẫn)
DB_DIR = os.path.join(MASTER_NODE_DIR, "data", "databases")
os.makedirs(DB_DIR, exist_ok=True)

CAMERA_DB = os.path.join(DB_DIR, "camera.db")
YML_FILE = os.path.join(MASTER_NODE_DIR, "MediaMTX", "mediamtx.yml")

print(f"📂 Đang trỏ DB tại: {CAMERA_DB}")
print(f"📂 Đang trỏ YML tại: {YML_FILE}")

def get_yaml_instance():
    yaml = YAML()
    yaml.preserve_quotes = True
    return yaml

# 🔥 THÊM HÀM NÀY ĐỂ BẢO VỆ DATABASE
def init_db_if_not_exists():
    """Tự động tạo bảng cameras nếu file DB mới tinh hoặc chưa có bảng"""
    try:
        with sqlite3.connect(CAMERA_DB) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cameras (
                    cam_id TEXT PRIMARY KEY,
                    name TEXT,
                    rtsp_url TEXT,
                    server_id TEXT,
                    status TEXT DEFAULT 'pending',
                    is_recording BOOLEAN,
                    record_url TEXT
                )
            """)
            conn.commit()
    except Exception as e:
        print(f"❌ Lỗi khi khởi tạo DB: {e}")

def start_mediamtx():
    exe_name = "mediamtx.exe"
    # 1. Kiểm tra xem MediaMTX đã chạy ngầm chưa
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] == exe_name:
            print("✅ MediaMTX đang chạy ngầm rồi. Bỏ qua khởi động!")
            return proc
    print("🚀 Đang khởi động MediaMTX...")
    # 2. Tìm đường dẫn chuẩn (Khi app.py và MediaMTX đứng cạnh nhau)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    mediamtx_dir = os.path.join(current_dir,"..", "MediaMTX")
    mediamtx_path = os.path.join(mediamtx_dir, exe_name)
    if os.path.exists(mediamtx_path):
        flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
        return subprocess.Popen(
            [mediamtx_path], 
            cwd=mediamtx_dir, # Ép nó đọc file cấu hình tại đây
            creationflags=flags
        )
    else:
        print(f"❌ KHÔNG TÌM THẤY {mediamtx_path}!")
        return None

def restart_mediamtx():
    """Hàm khởi động lại: Tiêu diệt tiến trình cũ rồi bật lại tiến trình mới"""
    exe_name = "mediamtx.exe"
    print("🔄 Bắt đầu tiến trình Reset MediaMTX...")
    
    # 1. Quét và Kill toàn bộ tiến trình MediaMTX đang chạy
    killed_any = False
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] == exe_name:
            try:
                print(f"💀 Đang tiêu diệt MediaMTX cũ (PID: {proc.info['pid']})...")
                proc.kill() # Ép chết lập tức để giải phóng port
                killed_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
    # 2. Nếu có tiến trình vừa bị giết, phải ĐỢI một nhịp cho Win nhả Port mạng ra
    if killed_any:
        print("⏳ Đang chờ hệ thống thu hồi các cổng mạng...")
        time.sleep(2) 
        
    # 3. Khởi động lại luồng mới
    print("✨ Bật lại phiên bản MediaMTX mới...")
    return start_mediamtx()

# ==============================================================
# NHÓM 1: CÁC HÀM DÙNG CHO API (GỌI KHI NGƯỜI DÙNG THAO TÁC TRÊN WEB)
# ==============================================================
def add_camera_to_yml(cam_id: str, rtsp_url: str):
    """Thêm 1 camera mới vào thẳng file YML"""
    yaml = get_yaml_instance()
    try:
        with open(YML_FILE, 'r', encoding='utf-8') as f:
            config = yaml.load(f)
            
        if 'paths' not in config:
            config['paths'] = {}
            
        # Nạp cấu hình mới
        config['paths'][cam_id] = {
            'source': rtsp_url,
            'record': 'yes'
        }
        
        with open(YML_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f)
        print(f"✅ [YML] Đã thêm {cam_id} vào file mediamtx.yml")
        return True
    except Exception as e:
        print(f"❌ [YML] Lỗi khi thêm camera: {e}")
        return False

def remove_camera_from_yml(cam_id: str):
    """Xóa 1 camera khỏi file YML"""
    yaml = get_yaml_instance()
    try:
        with open(YML_FILE, 'r', encoding='utf-8') as f:
            config = yaml.load(f)
            
        if 'paths' in config and cam_id in config['paths']:
            del config['paths'][cam_id]
            
            with open(YML_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(config, f)
            print(f"🗑️ [YML] Đã xóa {cam_id} khỏi file mediamtx.yml")
        return True
    except Exception as e:
        print(f"❌ [YML] Lỗi khi xóa camera: {e}")
        return False

# ==============================================================
# NHÓM 2: CÁC HÀM ĐỒNG BỘ TỔNG (DÙNG KHI KHỞI ĐỘNG SERVER MASTER)
# ==============================================================
def sync_yml_to_db():
    init_db_if_not_exists() # Gọi bùa bảo vệ trước khi làm việc
    yaml = get_yaml_instance()
    try:
        with open(YML_FILE, 'r', encoding='utf-8') as f:
            config = yaml.load(f)
            
        paths = config.get('paths', {})
        
        yml_cams = {}
        for cam_id, data in paths.items():
            if cam_id not in ['all_others', 'all', '~'] and isinstance(data, dict) and 'source' in data:
                yml_cams[cam_id] = {
                    'source': data['source'],
                    'is_recording': True if data.get('record') == 'yes' else False
                }

        added_to_db = 0
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT cam_id FROM cameras")
            db_cams = {row[0] for row in cursor.fetchall()}

            for cam_id, data in yml_cams.items():
                if cam_id not in db_cams:
                    name = cam_id.replace("cam_", "")
                    is_rec = 1 if data['is_recording'] else 0
                    rec_url = r"E:\FullStack_developer\projects\camera\Backend\master-node\data\camera" if is_rec else None

                    cursor.execute("""
                        INSERT INTO cameras (cam_id, name, rtsp_url, status, is_recording, record_url) 
                        VALUES (?, ?, ?, 'pending', ?, ?)
                    """, (cam_id, name, data['source'], is_rec, rec_url))
                    
                    added_to_db += 1
                    print(f"➕ [SYNC YML->DB] Đã nạp {cam_id} (Record: {is_rec}) vào Database.")
            conn.commit()
        return added_to_db
    except Exception as e:
        print(f"❌ Lỗi đồng bộ YML -> DB: {e}")
        return 0


def sync_db_to_yml():
    init_db_if_not_exists() # Gọi bùa bảo vệ trước khi làm việc
    yaml = get_yaml_instance()
    try:
        db_cams = {}
        with sqlite3.connect(CAMERA_DB) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT cam_id, rtsp_url, is_recording FROM cameras")
            for row in cursor.fetchall():
                db_cams[row[0]] = {
                    'rtsp_url': row[1],
                    'is_recording': bool(row[2])
                }

        with open(YML_FILE, 'r', encoding='utf-8') as f:
            config = yaml.load(f)
            
        if 'paths' not in config:
            config['paths'] = {}
        paths = config['paths']

        added_to_yml = 0
        for cam_id, data in db_cams.items():
            if cam_id not in paths:
                paths[cam_id] = {'source': data['rtsp_url']}
                if data['is_recording']:
                    paths[cam_id]['record'] = 'yes'
                    
                added_to_yml += 1
                print(f"➕ [SYNC DB->YML] Đã nạp cấu hình {cam_id} vào mediamtx.yml.")

        if added_to_yml > 0:
            with open(YML_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(config, f)
            print("💾 Đã ghi đè file mediamtx.yml thành công.")
            
        return added_to_yml
    except Exception as e:
        print(f"❌ Lỗi đồng bộ DB -> YML: {e}")
        return 0