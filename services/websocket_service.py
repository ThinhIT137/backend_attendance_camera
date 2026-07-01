import logging
import asyncio
import zmq
import zmq.asyncio
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Lưu trữ danh sách client đang hóng theo từng cam_id
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, cam_id: str):
        await websocket.accept()
        if cam_id not in self.active_connections:
            self.active_connections[cam_id] = []
        self.active_connections[cam_id].append(websocket)
        logger.info(f"🟢 Web Client đã kết nối hóng camera: {cam_id}")

    def disconnect(self, websocket: WebSocket, cam_id: str):
        if cam_id in self.active_connections and websocket in self.active_connections[cam_id]:
            self.active_connections[cam_id].remove(websocket)
            logger.info(f"🔴 Web Client đã ngắt kết nối camera: {cam_id}")

    async def broadcast(self, message: dict, cam_id: str):
        if cam_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[cam_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.append(connection)
            
            # Dọn dẹp các kết nối đã chết
            for conn in disconnected:
                self.disconnect(conn, cam_id)

manager = ConnectionManager()

# 🔥 ĐÂY LÀ TRẠM THU THẬP ZMQ TỪ TẤT CẢ CÁC MÁY YOLO
async def zmq_receiver_task():
    context = zmq.asyncio.Context()
    socket = context.socket(zmq.PULL)
    
    # Lắng nghe ở port 5558 trên mọi IP của con Master này
    socket.bind("tcp://0.0.0.0:5558")
    logger.info("🛸 [MASTER] Trạm thu thập AI đã mở tại cổng 5558, chờ Worker ném data tới...")
    
    while True:
        try:
            # Hứng data từ Worker (Tự động chuyển JSON thành dict Python)
            data = await socket.recv_json()
            cam_id = data.get("cam_id")
            
            if cam_id:
                # Có tọa độ phát là bơm thẳng xuống Web (nếu Web đang xem cam này)
                logger.debug(f"{data}")
                await manager.broadcast(data, cam_id)
        except Exception as e:
            logger.error(f"⚠️ Lỗi ZMQ PULL: {e}")

# (Ghi chú: Nhớ dùng asyncio.create_task(zmq_receiver_task()) 
# lúc khởi động app FastAPI Master nhé!)