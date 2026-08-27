"""SessionStore — in-memory хранилище сессий.

Требования (§4.2, NFR-1): TTL 30 мин, max 200 (LRU-evict старейших),
per-session asyncio.Lock для консистентности на запись, фоновый TTL-sweep.
БД нет — осознанный техдолг (в ROADMAP_TO_PRODUCTION).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Dict, List, Optional

from .plan import PlanSchema, Task, deep_copy_tasks
from .scheduler import find_critical_path, forward_pass, total_days
from .versions import VersionStack

TTL_SECONDS = 30 * 60  # FR: сессия живёт 30 минут без активности
MAX_SESSIONS = 200


class Session:
    """Живое состояние одной сессии."""

    def __init__(self, session_id: str):
        self.id = session_id
        self.tasks: List[Task] = []
        self.versions = VersionStack(cap=20)
        self.pending: Dict[str, dict] = {}  # pending_id -> {tool, arguments, diff, preview}
        self._lock = asyncio.Lock()
        self.last_seen = time.time()
        self.created_at = time.time()
        self.source_filename = ""

    def touch(self) -> None:
        self.last_seen = time.time()

    def state(self) -> dict:
        """Полное состояние для REST (FR-2)."""
        forward_pass({t.name: t for t in self.tasks})  # гарантия актуальных дат
        ends = [t.end_day for t in self.tasks if t.end_day is not None]
        plan = {
            "total_days": max(ends) if ends else 0,
            "critical_path": [],
            "columns": ["задача", "описание", "исполнитель", "длительность", "предшественники"],
            "n_tasks": len(self.tasks),
            "source_filename": self.source_filename,
        }
        # критический путь пересчитываем (мог измениться)
        by_name = {t.name: t for t in self.tasks}
        if by_name:
            plan["critical_path"] = find_critical_path(by_name)
        return {
            "schema": plan,
            "tasks": [t.detail_dict() for t in self.tasks],
            "pending": list(self.pending.values()),
            "version_head": self.versions.head,
        }


class SessionStore:
    """Хранилище всех сессий с TTL/LRU-политикой."""

    def __init__(self, ttl: int = TTL_SECONDS, max_sessions: int = MAX_SESSIONS):
        self._ttl = ttl
        self._max = max_sessions
        self._sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create(self) -> Session:
        async with self._lock:
            self._evict_if_needed()
            sid = uuid.uuid4().hex
            s = Session(sid)
            self._sessions[sid] = s
            return s

    def get(self, session_id: str) -> Optional[Session]:
        s = self._sessions.get(session_id)
        if s:
            s.touch()
        return s

    async def get_or_none(self, session_id: str) -> Optional[Session]:
        return self.get(session_id)

    def _evict_if_needed(self) -> None:
        while len(self._sessions) >= self._max:
            oldest = min(self._sessions.values(), key=lambda x: x.last_seen)
            self._sessions.pop(oldest.id, None)

    async def sweep(self) -> int:
        """Удаляет сессии, не активные дольше TTL. Возвращает число удалённых."""
        now = time.time()
        stale = [sid for sid, s in self._sessions.items() if now - s.last_seen > self._ttl]
        async with self._lock:
            for sid in stale:
                self._sessions.pop(sid, None)
        return len(stale)

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    @property
    def count(self) -> int:
        return len(self._sessions)


async def new_session(store: SessionStore, seed_tasks: List[Task]) -> Session:
    """Создаёт сессию и заваливает тестовые данные (US-1, FR-1)."""
    s = await store.create()
    s.tasks = deep_copy_tasks(seed_tasks)
    s.versions.push(seed_tasks, label="initial")
    s.source_filename = "тестовый-план.xlsx"
    return s