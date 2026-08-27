"""REST/SSE e2e через ASGITransport: session, upload, chat, stream, undo, export, pending."""
from __future__ import annotations

import io

import pytest


@pytest.mark.asyncio
async def test_create_session_has_seed(ac):
    r = await ac.post("/api/session")
    assert r.status_code == 200
    j = r.json()
    assert j["session_id"]
    assert j["state"]["schema"]["n_tasks"] == 9
    assert j["state"]["schema"]["total_days"] >= 30


@pytest.mark.asyncio
async def test_chat_fallback_shift_returns_update(ac):
    r = await ac.post("/api/session")
    sid = r.json()["session_id"]
    r = await ac.post(f"/api/chat/{sid}", json={"text": "перенеси задачу Тестирование на 2 дня позже"})
    assert r.status_code == 200
    events = r.json()["events"]
    types = [e.get("type") for e in events]
    assert "intent" in types and "update" in types and "done" in types
    # после сдвига 'Тестирование' должно сдвинуться на +2
    r = await ac.get(f"/api/session/{sid}")
    t = next(x for x in r.json()["state"]["tasks"] if x["name"] == "Тестирование")
    assert t["start_day"] and t["start_day"] >= 1


@pytest.mark.asyncio
async def test_upload_excel_then_state(ac):
    # Соберём .xlsx в памяти из тех же колонок ТЗ.
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["задача", "описание", "исполнитель", "длительность", "предшественники"])
    ws.append(["П1", "описание 1", "Иванов", 2, ""])
    ws.append(["П2", "описание 2", "Петров", 3, "П1"])
    buf = io.BytesIO()
    wb.save(buf)

    r = await ac.post("/api/session")
    sid = r.json()["session_id"]
    r = await ac.post(
        f"/api/session/{sid}/upload",
        files={"file": ("test.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["state"]["schema"]["n_tasks"] == 2
    names = [t["name"] for t in j["state"]["tasks"]]
    assert sorted(names) == ["П1", "П2"]


@pytest.mark.asyncio
async def test_export_xlsx_bytes(ac):
    r = await ac.post("/api/session")
    sid = r.json()["session_id"]
    r = await ac.get(f"/api/export/xlsx", params={"session_id": sid})
    assert r.status_code == 200
    assert r.content[:2] == b"PK"  # xlsx = zip
    assert len(r.content) > 500


@pytest.mark.asyncio
async def test_pending_confirm_for_destructive(ac):
    r = await ac.post("/api/session")
    sid = r.json()["session_id"]
    # undelete — remove_tasks всегда в pending (policy: destructive)
    r = await ac.post(f"/api/chat/{sid}", json={"text": "удали задачу Релиз"})
    events = r.json()["events"]
    assert any(e.get("type") == "pending" for e in events), "remove должен требовать подтверждения"
    r = await ac.post(f"/api/pending/{sid}/confirm")
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["state"]["tasks"]]
    assert "Релиз" not in names


@pytest.mark.asyncio
async def test_pending_cancel_does_nothing(ac):
    from app.seed import SEED_TASKS

    seeded = len(SEED_TASKS)
    r = await ac.post("/api/session")
    sid = r.json()["session_id"]
    r = await ac.post(f"/api/chat/{sid}", json={"text": "удали задачу Релиз"})
    assert any(e.get("type") == "pending" for e in r.json()["events"])
    r = await ac.post(f"/api/pending/{sid}/cancel")
    assert r.status_code == 200
    assert r.json()["state"]["schema"]["n_tasks"] == seeded


@pytest.mark.asyncio
async def test_undo_restores(ac):
    r = await ac.post("/api/session")
    sid = r.json()["session_id"]
    # Сессия стартует с версией 'initial' → первый undo успешен (200).
    r = await ac.post(f"/api/session/{sid}/undo")
    assert r.status_code == 200
    assert r.json()["state"]["schema"]["n_tasks"] == 9
    # После отката версий в стеке нет → второй undo вернёт 400.
    r2 = await ac.post(f"/api/session/{sid}/undo")
    assert r2.status_code == 400