"""policy.py — правило бэкенда подтверждения деструктивных/массовых операций.

Классификация происходит ДО выполнения, поэтому MCP-инструменты применяются
через два пути:
- в очередь pending (confirm/cancel) для деструктивных и массовых,
- напрямую для единичных правок.

LLM не обладает "free will" — любое действие проходит через политику (FR-11).
"""
from __future__ import annotations

from typing import Any, Dict, List

# Инструменты, которые НИКОГДА не попадают в pending (только чтение/безопасные).
ALWAYS_IMMEDIATE = {"get_schema", "get_task", "compute", "export", "help"}

# Инструменты, которые ВСЕГДА требуют подтверждения (деструктивные).
ALWAYS_PENDING = {"remove_tasks"}

# Инструменты, где решение зависит от масштаба (targets.all / много задач).
SCALE_GATE = {"shift_tasks", "reassign", "update_field"}


def _affected_count(targets: Dict[str, Any], plan_size: int) -> int:
    tasks = targets.get("tasks", [])
    if tasks == "all":
        return plan_size
    if isinstance(tasks, list):
        return len(tasks)
    return 1 if tasks else 0


def policy_decision(action: str, targets: Dict[str, Any], plan_size: int) -> Dict[str, Any]:
    """Решение политики для одного намерения/инструмента.

    targets: {"tasks": "all" | [names] | "current" | ...}.
    plan_size: общее число задач (для подсчёта при targets='all').

    Returns: {"need_confirmation": bool, "reason": str, "affected_count": int}.
    """
    if action in ALWAYS_IMMEDIATE:
        return {"need_confirmation": False, "reason": "readonly_or_safe", "affected_count": 0}

    if action in ALWAYS_PENDING:
        return {
            "need_confirmation": True,
            "reason": "destructive",
            "affected_count": _affected_count(targets, plan_size),
        }

    tasks = targets.get("tasks", [])
    if action in SCALE_GATE:
        if tasks == "all":
            return {"need_confirmation": True, "reason": "mass_operation", "affected_count": plan_size}
        if isinstance(tasks, list) and len(tasks) > 1:
            return {"need_confirmation": True, "reason": "mass_operation", "affected_count": len(tasks)}
        return {
            "need_confirmation": False,
            "reason": "single_edit",
            "affected_count": _affected_count(targets, plan_size),
        }

    # Прочие (add_task, set_dependency) — применяются сразу.
    return {
        "need_confirmation": False,
        "reason": "non_destructive",
        "affected_count": _affected_count(targets, plan_size),
    }


def needs_confirmation(action: str, targets: Dict[str, Any], plan_size: int = 0) -> bool:
    return policy_decision(action, targets, plan_size)["need_confirmation"]


def describe(tasks: List[str]) -> str:
    """Краткое описание списка затронутых задач для diff/pending."""
    if not tasks:
        return "нет затронутых задач"
    if len(tasks) <= 5:
        return ", ".join(tasks)
    return ", ".join(tasks[:5]) + f" и ещё {len(tasks) - 5}"