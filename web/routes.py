import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, FileResponse

from bot.bot_manager import BotManager
from bot.ai_provider import MODEL_CATALOG
from bot.memory_store import read_messages
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter()
manager: BotManager | None = None
_ws_clients: set[WebSocket] = set()


def init_routes(bot_manager: BotManager):
    global manager
    manager = bot_manager
    manager.set_ws_broadcast(_broadcast)


async def _broadcast(data: dict):
    payload = json.dumps(data)
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


@router.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    return FileResponse("web/static/index.html")


@router.post("/api/start")
async def start_bot(request: Request):
    body = await request.json()
    username = body.get("username", "").strip()
    if not username:
        return {"error": "Username is required"}
    await manager.start(username)
    return {"ok": True}


@router.post("/api/stop")
async def stop_bot():
    await manager.stop()
    return {"ok": True}


@router.post("/api/pause")
async def pause_bot():
    await manager.pause()
    return {"ok": True}


@router.get("/api/status")
async def get_status():
    return manager.get_status()


@router.put("/api/settings")
async def update_settings(request: Request):
    body = await request.json()
    manager.update_settings(
        model_id=body.get("model_id"),
        system_prompt=body.get("system_prompt"),
        tts_voice=body.get("tts_voice"),
        thank_followers=body.get("thank_followers"),
        thank_gifts=body.get("thank_gifts"),
        openai_api_key=body.get("openai_api_key"),
        tavily_api_key=body.get("tavily_api_key"),
    )
    return manager.get_status()


@router.get("/api/models")
async def get_models():
    # The dashboard builds its single "Modello" dropdown from this; the provider
    # behind each model stays hidden from the user.
    return [
        {"id": m["id"], "label": m["label"], "needs_key": m["needs_key"]}
        for m in MODEL_CATALOG
    ]


@router.get("/api/memory")
async def get_memory(limit: int = 200):
    # Read straight from disk so saved memory is visible even when the bot is
    # stopped. Newest first, capped so a huge history can't flood the UI.
    entries = read_messages(settings.memory_dir, limit=limit)
    return {"count": len(entries), "entries": entries}


@router.delete("/api/memory")
async def clear_memory():
    manager.clear_memory()
    return {"ok": True}


@router.get("/api/log")
async def get_log():
    return [
        {
            "username": e.username,
            "message": e.message,
            "response": e.response,
            "timestamp": e.timestamp,
        }
        for e in manager.log[-50:]
    ]


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        # Send current status on connect
        await websocket.send_text(json.dumps({
            "type": "status",
            "state": manager.state.value,
        }))
        while True:
            # Keep connection alive; we don't expect messages from the client
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)
