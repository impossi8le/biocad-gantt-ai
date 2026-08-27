"""Версии-снапшоты плана для undo (US-10, §4.2).

Стек версий ограничен cap (по умолчанию 20), старые срезаются.
Снапшот — глубокая копия задач; правится заново scheduler'ом после restore.
"""
from __future__ import annotations

import time
from typing import List, Optional

from pydantic import BaseModel, Field

from .plan import Task, deep_copy_tasks


class Version(BaseModel):
    id: int
    label: str = ""
    created_at: float = Field(default_factory=time.time)
    tasks_snapshot: List[Task] = Field(default_factory=list)


class VersionStack:
    """Потокобезопасный стек снапшотов (cap=N)."""

    def __init__(self, cap: int = 20):
        self.cap = cap
        self._versions: List[Version] = []

    def push(self, tasks: List[Task], label: str = "") -> Version:
        v = Version(id=self._next_id(), label=label, tasks_snapshot=deep_copy_tasks(tasks))
        self._versions.append(v)
        if len(self._versions) > self.cap:
            self._versions = self._versions[-self.cap:]
        return v

    def _next_id(self) -> int:
        return self._versions[-1].id + 1 if self._versions else 0

    @property
    def head(self) -> int:
        return self._versions[-1].id if self._versions else -1

    def pop(self) -> Optional[Version]:
        if not self._versions:
            return None
        return self._versions.pop()

    def latest(self) -> Optional[Version]:
        return self._versions[-1] if self._versions else None

    def list(self) -> List[dict]:
        return [
            {"id": v.id, "label": v.label, "created_at": v.created_at, "n_tasks": len(v.tasks_snapshot)}
            for v in self._versions
        ]

    def clear(self) -> None:
        self._versions = []