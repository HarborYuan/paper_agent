from fastapi import WebSocket
from typing import List


class LogManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast_log(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # If sending fails, we might want to remove the connection, 
                # but typically disconnect handles it upon exception in the route.
                pass

    async def log(self, message: str):
        # Print to console as usual
        print(message)
        # Broadcast to websockets
        await self.broadcast_log(message)

# Global instance
logger = LogManager()
