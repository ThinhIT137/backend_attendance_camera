from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.websocket_service import manager # Lấy cái manager từ service của bro sang

ws_router = APIRouter()

@ws_router.websocket("/ws/tracking/{cam_id}")
async def websocket_endpoint(websocket: WebSocket, cam_id: str):
    await manager.connect(websocket, cam_id)
    try:
        while True:
            await websocket.receive_text() # Giữ kết nối mở
    except Exception:
        manager.disconnect(websocket, cam_id)