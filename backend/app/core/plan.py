"""Модель плана: задачи, предшественники, схема.

Чистая модель данных без бизнес-логики расписания (она в scheduler.py).
Используется REST-слоем, MCP-инструментами и LLM-контекстом.
"""
from __future__ import annotations

import copy
import re
import uuid
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator

# Канонический порядок колонок Excel (US-5 / FR-4). Строго фиксирован.
COLUMNS: List[str] = ["задача", "описание", "исполнитель", "длительность", "предшественники"]

# Псевдонимы колонок при импорте (сопоставление синонимов).
COLUMN_ALIASES: dict[str, str] = {
    "задача": "задача",
    "task": "задача",
    "name": "задача",
    "название": "задача",
    "task name": "задача",
    "описание": "описание",
    "description": "описание",
    "desc": "описание",
    "исполнитель": "исполнитель",
    "assignee": "исполнитель",
    "owner": "исполнитель",
    "исполнители": "исполнитель",
    "длительность": "длительность",
    "duration": "длительность",
    "duration_days": "длительность",
    "дней": "длительность",
    "дни": "длительность",
    "предшественники": "предшественники",
    "predecessors": "предшественники",
    "predecessor": "предшественники",
    "зависимости": "предшественники",
    "dependencies": "предшественники",
}

# Поля задачи, редактируемые через update_field (FR-10).
EDITABLE_FIELDS: List[str] = ["name", "description", "assignee", "duration_days"]


class Task(BaseModel):
    """Задача плана. Вычисляемые scheduler'ом поля по умолчанию пусты (None)."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    description: str = ""
    assignee: str = ""
    duration_days: int = 1
    predecessors: List[str] = Field(default_factory=list)
    # Вычислено scheduler (проектный день 1-based).
    start_day: Optional[int] = None
    end_day: Optional[int] = None
    critical: bool = False
    # Мета-информация импорта (не сериализуется наружу).
    original_row: Optional[int] = None

    @field_validator("duration_days")
    @classmethod
    def _check_duration(cls, v: int) -> int:
        if v is None or v <= 0:
            return 1
        return int(v)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("имя задачи не может быть пустым")
        return v

    def detail_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "assignee": self.assignee,
            "duration_days": self.duration_days,
            "predecessors": list(self.predecessors),
            "start_day": self.start_day,
            "end_day": self.end_day,
            "critical": self.critical,
        }


class PlanSchema(BaseModel):
    """Схема плана: описание структуры для «словаря языка» LLM и UI."""

    columns: List[str] = COLUMNS
    n_tasks: int = 0
    total_days: int = 0
    critical_path: List[str] = Field(default_factory=list)
    source_filename: str = ""
    header_row: int = 1


class Diff(BaseModel):
    """Машинночитаемое описание изменения — идёт в SSE `update`."""

    applied: bool = False
    affected: List[str] = Field(default_factory=list)
    description: str = ""
    changed: Optional[dict[str, Any]] = None


def new_task_id() -> str:
    return uuid.uuid4().hex[:12]


def canonical_predecessor_name(raw: Optional[str]) -> List[str]:
    """Парсит строку/список предшественников в список имён задач.

    Поддерживает разделители `;`, `,`, `|`, перенос строки, а также
    индексы строк (1-based), если задано mapping index -> имя.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        values = raw
    else:
        values = [str(raw)]
    result: List[str] = []
    for chunk in values:
        for part in re.split(r"[;,|/\n]+", str(chunk)):
            part = part.strip()
            if not part:
                continue
            result.append(part)
    return result


def deep_copy_tasks(tasks: list[Task]) -> list[Task]:
    """Глубокая копия списка задач (для снапшотов версий)."""
    return [Task.model_validate(t.model_dump()) for t in tasks]


def clone_task(task: Task) -> Task:
    t = task.model_copy(deep=True)
    t.id = uuid.uuid4().hex[:12]
    return t