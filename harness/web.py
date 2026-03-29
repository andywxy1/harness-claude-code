"""Web server for real-time UI — FastAPI + WebSocket."""

import asyncio
import json
import threading
from pathlib import Path

from harness.events import bus

# Lazy imports to keep startup fast when web is disabled
_app = None
_clients: set = set()
_loop: asyncio.AbstractEventLoop | None = None


def _get_app():
    global _app
    if _app is not None:
        return _app

    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse

    _app = FastAPI(title="Harness Claude")

    @_app.get("/")
    async def index():
        html_path = Path(__file__).parent / "static" / "index.html"
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @_app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        _clients.add(ws)
        try:
            # Send current state snapshot + history on connect
            await ws.send_json({
                "type": "state_snapshot",
                "state": bus.state,
                "history": bus.history[-200:],  # last 200 events
            })
            # Keep connection alive, listen for client messages
            while True:
                data = await ws.receive_text()
                # Future: handle intervention commands from UI
                if data == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            _clients.discard(ws)

    return _app


def _on_event(event: dict):
    """Bridge sync event → async WebSocket broadcast."""
    if _loop is None or not _clients:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(event), _loop)


async def _broadcast(event: dict):
    """Send event to all connected WebSocket clients."""
    dead = set()
    for ws in _clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


def start_web_server(port: int = 8420):
    """Start uvicorn in a daemon thread. Returns immediately."""
    global _loop

    import uvicorn

    app = _get_app()
    bus.subscribe(_on_event)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    def _run():
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(server.serve())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    bus.emit("log", source="Web", message=f"UI available at http://localhost:{port}")
