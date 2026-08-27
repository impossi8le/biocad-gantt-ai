"""Intent: структурированный результат «двухпроходного» LLM-слоя.

Первый проход (не-стриминговый, structured output) преобразует естественный
язык в Intent {action, targets, params, explanation} (pydantic). Второй проход
(стриминг) генерирует русскоязычную наррацию по SSE (см. agent.py).

action — один из whitelist MCP-инструментов; policy.py классифицирует его как
destructive / mass / single, поэтому LLM не имеет «free will» (FR-11).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class Action(str, Enum):
    GET_SCHEMA = "get_schema"
    GET_TASK = "get_task"
    SHIFT_TASKS = "shift_tasks"
    SET_DEPENDENCY = "set_dependency"
    ADD_TASK = "add_task"
    REASSIGN = "reassign"
    UPDATE_FIELD = "update_field"
    REMOVE_TASKS = "remove_tasks"
    COMPUTE = "compute"
    EXPORT = "export"
    UNDO = "undo"
    HELP = "help"


class Intent(BaseModel):
    """Намерение пользователя после первого прохода LLM."""

    action: Action
    targets: Dict[str, Any] = Field(default_factory=dict)
    params: Dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""