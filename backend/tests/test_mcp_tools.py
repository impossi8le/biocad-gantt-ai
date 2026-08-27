"""MCP-инструменты через MCPSessionClient (без сетевого стека)."""
from __future__ import annotations

import asyncio

import pytest

from app.core.plan import deep_copy_tasks
from app.core.sessions import SessionStore
from app.mcp.server import MCPSessionClient


@pytest.fixture
def store() -> SessionStore:
    return SessionStore()


@pytest.fixture
def session_client(store: SessionStore):
    s = asyncio.run(store.create())
    from app.seed import SEED_TASKS

    s.tasks = deep_copy_tasks(SEED_TASKS)
    s.versions.push(s.tasks, label="initial")
    return s, MCPSessionClient(store)


def test_tools_listed(session_client):
    s, client = session_client
    for tool in ("shift_tasks", "remove_tasks", "add_task", "compute", "export", "undo"):
        assert tool in client.list_tools()


def test_unknown_tool(session_client):
    s, client = session_client
    res = client.call_tool("nope", s.id, {})
    assert res.get("error") == "unknown_tool"


def test_shift_add_reassign(session_client):
    s, client = session_client
    r = client.call_tool(
        "shift_tasks",
        s.id,
        {"targets": {"tasks": ["Тестирование"]}, "params": {"mode": "offset", "value": 2}},
    )
    assert r.get("applied") is True
    r = client.call_tool(
        "add_task",
        s.id,
        {"name": "Новая", "duration_days": 2, "assignee": "Ки", "predecessors": ["Анализ"]},
    )
    assert r.get("applied") is True
    assert any(t.name == "Новая" for t in s.tasks)


def test_compute_ok(session_client):
    s, client = session_client
    r = client.call_tool("compute", s.id, {"agg": "sum", "field": "duration_days", "by": "assignee"})
    assert r.get("ok") is True
    assert isinstance(r.get("result"), dict)
    assert any(v > 0 for v in r["result"].values())


def test_export_bytes(session_client):
    s, client = session_client
    r = client.call_tool("export", s.id, {"fmt": "xlsx"})
    assert r.get("ok") is True
    assert r.get("format") == "xlsx"
    assert r.get("bytes", 0) > 0


def test_remove_tool_targets(session_client):
    # политика применяется в agent/session; сам инструмент удаляет по targets
    s, client = session_client
    r = client.call_tool("remove_tasks", s.id, {"targets": {"tasks": ["Релиз"]}})
    assert r.get("removed") == ["Релиз"]