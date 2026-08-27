"""Фикстуры: сессия с демо-планом + минимальный ASGI-клиент без сети."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Корень backend в sys.path для импорта app.* из tests/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.plan import Task
from app.core.sessions import Session, SessionStore  # noqa: E402
from app.mcp.server import MCPSessionClient  # noqa: E402
from app.seed import SEED_TASKS  # noqa: E402


def _seed() -> list[Task]:
    from app.core.plan import deep_copy_tasks

    return deep_copy_tasks(SEED_TASKS)


@pytest.fixture
def fresh_tasks() -> list[Task]:
    return _seed()


@pytest.fixture
def store() -> SessionStore:
    return SessionStore()


@pytest.fixture
async def session(store: SessionStore) -> Session:
    s = await store.create()
    s.tasks = _seed()
    s.versions.push(s.tasks, label="initial")
    return s


@pytest.fixture
def client(session: Session) -> MCPSessionClient:
    return MCPSessionClient(SessionStore())


@pytest_asyncio.fixture
async def ac():
    """ASGI-клиент к FastAPI app (без внешнего Docker)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        yield c