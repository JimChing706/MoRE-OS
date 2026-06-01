"""Minesweeper game FastAPI Web service - providing REST API and Web interface"""

from __future__ import annotations

import json
import os
from typing import Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .state_manager import GameSessionManager, DIFFICULTY_PRESETS, validate_custom_config, get_difficulty_info


# —— Pydantic Request/Response Models ——

class NewGameRequest(BaseModel):
    difficulty: str = "beginner"
    custom_config: Optional[Dict[str, int]] = None
    first_click_safe: bool = True


class MoveRequest(BaseModel):
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    action: str = Field(..., pattern="^(reveal|flag|chord)$")  # reveal | flag | chord


class GameStateResponse(BaseModel):
    game_id: str
    state: Dict[str, Any]
    timestamp: str


# Global session manager
session_mgr = GameSessionManager()


# —— FastAPI Application Factory ——

def create_minesweeper_app() -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await session_mgr.start()
        try:
            yield
        finally:
            await session_mgr.stop()

    app = FastAPI(title="Minesweeper Game API", version="0.1.0", lifespan=lifespan)

    # Mount static files
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index():
        """Home page - returns enhanced cross-platform interface"""
        html_path = os.path.join(os.path.dirname(__file__), "static", "minesweeper_enhanced.html")
        if os.path.exists(html_path):
            with open(html_path, encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
        with open(index_path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    @app.get("/enhanced")
    async def enhanced():
        """Enhanced interface"""
        html_path = os.path.join(os.path.dirname(__file__), "static", "minesweeper_enhanced.html")
        with open(html_path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    @app.get("/mobile")
    async def mobile():
        """Mobile-optimized interface"""
        html_path = os.path.join(os.path.dirname(__file__), "static", "minesweeper_enhanced.html")
        with open(html_path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    @app.get("/platform-info")
    async def platform_info():
        """Get platform info"""
        # Use default values as simulation
        from fastapi import Request
        return {
            "platform": "desktop",
            "user_agent": "minesweeper-bot",
            "features": {
                "touch": False,
                "pwa": True,
                "webgl": False,
                "web_audio": False
            },
            "recommended": {
                "interface": "mouse",
                "cell_size": "normal"
            }
        }

    # —— API Endpoints ——

    @app.post("/api/v1/minesweeper/new")
    async def new_game(req: NewGameRequest):
        """Create new game"""
        try:
            # Validate custom config
            if req.difficulty == "custom":
                if not req.custom_config:
                    raise HTTPException(status_code=400, detail="Custom config required for custom difficulty")
                valid, message = validate_custom_config(req.custom_config)
                if not valid:
                    raise HTTPException(status_code=400, detail=message)
            
            game_id = await session_mgr.create_session(
                difficulty=req.difficulty,
                custom_config=req.custom_config,
                first_click_safe=req.first_click_safe,
            )
            session = await session_mgr.get_session(game_id)
            state = await session.get_state()
            return {
                "game_id": game_id,
                "state": state,
                "message": "Game created"
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/v1/minesweeper/validate-config")
    async def validate_config(config: Dict[str, int]):
        """Validate custom config"""
        valid, message = validate_custom_config(config)
        return {"valid": valid, "message": message}

    @app.get("/api/v1/minesweeper/difficulties")
    async def get_difficulties():
        """Get all difficulty configs"""
        difficulties = {}
        for name in DIFFICULTY_PRESETS.keys():
            try:
                difficulties[name] = get_difficulty_info(name)
            except ValueError:
                pass
        return {"difficulties": difficulties}

    @app.get("/api/v1/minesweeper/difficulty/{name}")
    async def get_difficulty(name: str):
        """Get specific difficulty config"""
        return get_difficulty_info(name)

    @app.post("/api/v1/minesweeper/{game_id}/end")
    async def end_game(game_id: str):
        """End game"""
        await session_mgr.remove_session(game_id)
        return {"game_id": game_id, "status": "ended"}

    @app.get("/api/v1/minesweeper/sessions")
    async def list_sessions():
        """List all active games"""
        return await session_mgr.list_sessions()

    @app.get("/api/v1/health")
    async def health_check():
        """Health check"""
        return {
            "status": "healthy",
            "service": "minesweeper",
            "version": "0.1.0",
            "features": {
                "multi_platform": True,
                "touch_support": True,
                "pwa": True,
                "ai_autoplay": True
            }
        }

    @app.websocket("/ws/minesweeper/{game_id}")
    async def websocket_endpoint(websocket: WebSocket, game_id: str):
        """WebSocket real-time game interface"""
        await websocket.accept()
        session = await session_mgr.get_session(game_id)
        if not session:
            await websocket.close(code=4004)
            return

        try:
            while True:
                data = await websocket.receive_json()
                x = data.get("x")
                y = data.get("y")
                action = data.get("action", "reveal")

                state = await session.execute_move(x, y, action)
                await websocket.send_json({
                    "type": "state_update",
                    "state": state,
                    "game_over": session.game.is_game_over(),
                })

                if session.game.is_game_over():
                    break
        except WebSocketDisconnect:
            pass
        finally:
            if session and session.game.is_game_over():
                await session_mgr.remove_session(game_id)

    return app


app = create_minesweeper_app()