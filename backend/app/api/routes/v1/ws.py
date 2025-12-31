"""WebSocket routes."""

from fastapi import APIRouter, WebSocket

router = APIRouter()


class ConnectionManager:
    """WebSocket connection manager."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and store a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket) -> None:
        """Send a message to a specific WebSocket."""
        await websocket.send_text(message)

    async def broadcast(self, message: str) -> None:
        """Broadcast a message to all connected WebSockets."""
        for connection in self.active_connections:
            await connection.send_text(message)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time communication."""
    await manager.connect(websocket)
    async for data in websocket.iter_text():
        await manager.broadcast(f"Message: {data}")
    manager.disconnect(websocket)
