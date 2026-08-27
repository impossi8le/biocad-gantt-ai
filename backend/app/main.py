"""Точка входа FastAPI-приложения.

Собирает SessionStore, in-process MCP-сервер и REST+SSE маршруты. При старте
запускает фоновый TTL-sweeper (удаляет неактивные сессии, NFR-1).
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import get_settings
from .core.sessions import SessionStore
from .mcp.server import build_server


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = SessionStore()
    app.state.store = store
    # In-process MCP-сервер (SDK 2.0) — регистрируется, но LLM использует
    # погружной MCPSessionClient (см. mcp/server.py).
    app.state.mcp = build_server(store)

    async def sweep_loop():
        while True:
            await asyncio.sleep(get_settings().session_ttl)
            try:
                await store.sweep()
            except Exception:
                pass

    task = asyncio.create_task(sweep_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Gantt AI Plan", version="0.1.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

# Статик-фронт (если собран) — отдаётся с того же сервера в продакшине.
_frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), reload=False)


if __name__ == "__main__":
    main()