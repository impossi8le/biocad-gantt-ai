"""REST + SSE API (FR-7..FR-12).

Эндпоинты:
- POST /api/session              — создать сессию с закешированным стартовым планом (US-1)
- GET  /api/session/{id}         — состояние плана (FR-2)
- POST /api/upload               — загрузить свой Excel/CSV (UC-2)
- POST /api/export/{fmt}         — выгрузить план в Excel/CSV (UC-4)
- GET  /api/session/{id}/undo    — откат последнего изменения (US-10)
- POST /api/chat/{id}            — чат-запрос: LLM intent → SSP-экспорт (UC-3)
- GET  /api/chat/{id}/stream     — то же, но SSE-поток (intent/update/delta/done)
- POST /api/pending/{id}/confirm — подтвердить отложенную массовую/деструктивную операцию
- POST /api/pending/{id}/cancel  — отменить отложенную
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..core.import_export import ImportError_, export_tasks, parse_tasks
from ..core.sessions import Session, SessionStore, new_session
from ..core.plan import Task
from ..llm.agent import apply_intent_events, intent_from_text
from ..mcp.server import get_client
from ..seed import SEED_TASKS

router = APIRouter()


# --- зависимости ----------------------------------------------------------------

def get_store(request: Request) -> SessionStore:
    store = getattr(request.app.state, "store", None)
    if store is None:
        # Безопасная инициализация при тестах без lifespan (ASGITransport).
        from ..core.sessions import SessionStore

        store = SessionStore()
        request.app.state.store = store
    return store


async def _require_session(store: SessionStore, session_id: str) -> Session:
    s = await store.get_or_none(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="сессия не найдена")
    return s


# --- session --------------------------------------------------------------------

@router.post("/session")
async def create_session(store: SessionStore = Depends(get_store)) -> Dict[str, Any]:
    s = await new_session(store, SEED_TASKS)
    return {"session_id": s.id, "state": s.state()}


@router.get("/session/{session_id}")
async def get_session(session_id: str, store: SessionStore = Depends(get_store)) -> Dict[str, Any]:
    s = await _require_session(store, session_id)
    return {"session_id": s.id, "state": s.state()}


# --- upload / export --------------------------------------------------------------

@router.post("/session/{session_id}/upload")
async def upload(
    session_id: str,
    file: UploadFile = File(...),
    store: SessionStore = Depends(get_store),
) -> Dict[str, Any]:
    s = await _require_session(store, session_id)
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="файл больше 20 МБ")
    try:
        tasks, warnings = parse_tasks(data, file.filename or "")
    except ImportError_ as e:
        raise HTTPException(status_code=400, detail=e.message)
    s.tasks = tasks
    s.source_filename = file.filename or "план"
    s.versions.push(s.tasks, label="upload")
    return {"ok": True, "warnings": warnings, "state": s.state()}


@router.get("/export/{fmt}")
async def export(fmt: str = "xlsx", session_id: str = "", store: SessionStore = Depends(get_store)):
    if not session_id:
        raise HTTPException(status_code=400, detail="parameter session_id обязателен")
    s = await _require_session(store, session_id)
    if fmt not in ("xlsx", "csv"):
        raise HTTPException(status_code=400, detail="формат должен быть xlsx или csv")
    data, filename = export_tasks(s.tasks, fmt=fmt, source=s.source_filename)
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx" else "text/csv"
    # RFC 5987: кириллица в filename не кодируется в latin-1 → percent-encode.
    from urllib.parse import quote

    ascii_fallback = filename.encode("ascii", "ignore").decode() or "plan"
    cd = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(iter([data]), media_type=media, headers={"Content-Disposition": cd})


# --- undo ------------------------------------------------------------------------

@router.post("/session/{session_id}/undo")
async def undo(session_id: str, store: SessionStore = Depends(get_store)) -> Dict[str, Any]:
    s = await _require_session(store, session_id)
    v = s.versions.pop()
    if not v:
        raise HTTPException(status_code=400, detail="нет версий для отката")
    from ..core.plan import Task
    from ..core.scheduler import forward_pass, find_critical_path

    s.tasks = [Task.model_validate(t.model_dump()) for t in v.tasks_snapshot]
    by_name = {t.name: t for t in s.tasks}
    forward_pass(by_name)
    find_critical_path(by_name)
    return {"ok": True, "state": s.state()}


# --- chat (non-stream + SSE-stream) -------------------------------------------------

@router.post("/chat/{session_id}")
async def chat(session_id: str, payload: Dict[str, Any], store: SessionStore = Depends(get_store)) -> Dict[str, Any]:
    s = await _require_session(store, session_id)
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="пустой запрос")
    client = get_client(store)
    intent = await intent_from_text(text, s)
    events = []
    async for ev in apply_intent_events(s, intent, client, stream=False):
        events.append(ev)
    return {"events": events}


@router.get("/chat/{session_id}/stream")
async def chat_stream(session_id: str, text: str = "", store: SessionStore = Depends(get_store)):
    s = await _require_session(store, session_id)
    if not text.strip():
        raise HTTPException(status_code=400, detail="пустой запрос")
    client = get_client(store)

    async def gen():
        intent = await intent_from_text(text, s)
        async for ev in apply_intent_events(s, intent, client):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- pending confirm/cancel --------------------------------------------------------

@router.post("/pending/{session_id}/confirm")
async def confirm_pending(session_id: str, store: SessionStore = Depends(get_store)) -> Dict[str, Any]:
    s = await _require_session(store, session_id)
    if not s.pending:
        raise HTTPException(status_code=400, detail="нет отложенных операций")
    client = get_client(store)
    pid, entry = s.pending.popitem()
    tool = entry["tool"]
    args = dict(entry["arguments"])
    result = client.call_tool(tool, s.id, args)
    return {"ok": result.get("ok", False), "applied": result.get("applied", False),
            "result": result, "state": s.state()}


@router.post("/pending/{session_id}/cancel")
async def cancel_pending(session_id: str, store: SessionStore = Depends(get_store)) -> Dict[str, Any]:
    s = await _require_session(store, session_id)
    if s.pending:
        s.pending.clear()
    return {"ok": True, "state": s.state()}