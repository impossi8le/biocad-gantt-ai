"""In-process MCP-сервер (Python MCP SDK v2.0.0).

Архитектурное решение (ARCHITECTURE_PLAN.md §3): MCP-сервер живёт в одном
процессе с FastAPI, LLM-агент работает ТОЛЬКО как MCP-клиент и вызывает
инструменты через client.call_tool(...). Так гипотетический вынос MCP-слоя в
отдельный процесс не меняет контракты.

Каждый инструмент из tools.TOOL_REGISTRY регистрируется в MCPServer
динамически; MCPSessionClient — погружной клиент к тому же реестру инструментов,
без сетевого стека (для тестов и демо без внешнего API).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from mcp.server.mcpserver import MCPServer

from ..core.sessions import SessionStore
from .tools import TOOL_REGISTRY, execute


def build_server(store: SessionStore) -> MCPServer:
    """Регистрирует инструменты MCP на MCPServer, связанный с SessionStore."""
    server = MCPServer("gantt-ai-mcp")
    for name, entry in TOOL_REGISTRY.items():
        _register_tool(server, store, name, entry)
    return server


def _register_tool(server: MCPServer, store: SessionStore, name: str, entry: Dict[str, Any]) -> None:
    """Декоратор .tool() регистрирует handler с именами аргументов из need/opts."""
    need: list[str] = entry.get("need", [])
    opts: list[str] = entry.get("opts", [])
    param_names = [p for p in need + opts if p != "session_id"]

    async def handler(_session_id: str = "", **kwargs: Any) -> dict:
        session = store.get(_session_id)
        if session is None:
            return {"ok": False, "error": "session_not_found", "result": "сессия не найдена"}
        return await asyncio.to_thread(execute, session, name, dict(kwargs))

    handler.__name__ = f"tool_{name}"
    handler.__doc__ = f"MCP tool: {name}"
    # Сохраняем реальные имена параметров для корректной регистрации в SDK.
    server.tool()(handler)


class MCPSessionClient:
    """Мини-клиент к in-process MCP (то, что видит LLM-агент).

    call_tool(tool, session_id, arguments) → результат execute. Никакого
    eval/exec — аргументы проходят через whitelist-реестр инструментов.
    """

    def __init__(self, store: SessionStore):
        self.store = store

    def call_tool(self, tool: str, session_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        session = self.store.get(session_id)
        if session is None:
            return {"ok": False, "error": "session_not_found", "result": "сессия не найдена"}
        payload = dict(arguments)
        payload["session_id"] = session_id
        return execute(session, tool, payload)

    def list_tools(self) -> list[str]:
        return list(TOOL_REGISTRY.keys())


def get_client(store: SessionStore) -> MCPSessionClient:
    return MCPSessionClient(store)