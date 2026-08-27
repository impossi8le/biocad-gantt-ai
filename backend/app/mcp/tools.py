"""MCP-инструменты (11) — единственный реальный интерфейс к плану.

MCP-слой НЕ знает про FastAPI/REST (FR-17/FR-18): работает только через
SessionStore + scheduler. Выносится в отдельный процесс без смены контрактов.

Безопасность: whitelist-инструменты, compute — фикс. pandas-агрегации,
никакого eval/exec (NFR-4).
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from ..core.plan import Task, deep_copy_tasks
from ..core.scheduler import CycleError, _topo, forward_pass, find_critical_path, total_days
from ..core.sessions import Session


# --- чтение состояния -------------------------------------------------------

def build_state(session: Session) -> dict:
    """Полное состояние для SSE update / ответов."""
    by_name = {t.name: t for t in session.tasks}
    ends = [t.end_day for t in session.tasks if t.end_day is not None]
    plan = {
        "total_days": max(ends) if ends else 0,
        "critical_path": [],
        "columns": ["задача", "описание", "исполнитель", "длительность", "предшественники"],
        "n_tasks": len(session.tasks),
    }
    if by_name:
        plan["critical_path"] = find_critical_path(by_name)
    return {
        "plan": plan,
        "tasks": [t.detail_dict() for t in session.tasks],
        "version_head": session.versions.head,
    }


def recalc(session: Session) -> None:
    """Пересчёт дат + критический путь после мутации."""
    by_name = {t.name: t for t in session.tasks}
    forward_pass(by_name)
    find_critical_path(by_name)


def _commit(session: Session, label: str) -> dict:
    """Снапшот в versions → пересчёт → возврат состояния."""
    session.versions.push(session.tasks, label=label)
    recalc(session)
    return build_state(session)


def _by_name(session: Session) -> Dict[str, str]:
    return {t.name: t.id for t in session.tasks}


def _resolve_names(session: Session, targets: Any) -> List[str]:
    if targets == "all":
        return [t.name for t in session.tasks]
    if isinstance(targets, list):
        return [str(n) for n in targets if str(n).strip()]
    return []


def _resolve_from_targets(session: Session, targets: Dict[str, Any]) -> List[str]:
    return _resolve_names(session, targets.get("tasks", []))


# --- read tools -------------------------------------------------------------

def mcp_get_schema(session: Session) -> dict:
    by_name = {t.name: t for t in session.tasks}
    critical = find_critical_path(by_name) if by_name else []
    return {
        "ok": True,
        "schema": {
            "n_tasks": len(session.tasks),
            "total_days": total_days(session.tasks),
            "critical_path": critical,
            "columns": ["задача", "описание", "исполнитель", "длительность", "предшественники"],
            "header_row": 1,
        },
        "names": [t.name for t in session.tasks],
    }


def mcp_get_task(session: Session, task: str, detail: str = "compact") -> dict:
    t = next((x for x in session.tasks if x.name == task), None)
    if not t:
        return {"ok": False, "error": "not_found", "result": f"задача «{task}» не найдена"}
    d = t.detail_dict()
    if detail == "full":
        d["description"] = t.description
        d["predecessors"] = list(t.predecessors)
    return {"ok": True, "task": d}


def mcp_compute(
    session: Session, agg: str = "sum", field: str = "duration_days", by: str = "assignee"
) -> dict:
    from ..core.scheduler import aggregate_by

    try:
        result = aggregate_by(session.tasks, agg=agg, field=field, by=by)
        return {"ok": True, "agg": agg, "field": field, "by": by, "result": result}
    except ValueError as e:
        return {"ok": False, "result": str(e)}


def mcp_export(session: Session, fmt: str = "xlsx") -> dict:
    from ..core.import_export import export_tasks

    try:
        data, filename = export_tasks(session.tasks, fmt=fmt, source=session.source_filename or "план")
        return {"ok": True, "format": fmt, "filename": filename, "bytes": len(data)}
    except ValueError as e:
        return {"ok": False, "result": str(e)}


# --- мутации ----------------------------------------------------------------

def mcp_shift_tasks(session: Session, targets: Dict[str, Any], params: Dict[str, Any]) -> dict:
    names = _resolve_from_targets(session, targets)
    if not names:
        return {"ok": False, "result": "не указаны задачи для сдвига"}
    mode = params.get("mode", "offset")
    value = params.get("value", 0)
    offset = _parse_offset(value)
    affected: List[str] = []

    for t in session.tasks:
        if t.name not in names:
            continue
        if mode == "offset":
            if offset is None:
                return {"ok": False, "result": f"некорректный offset: {value}"}
            delta = offset
        elif mode == "to_date":
            target = _parse_day(value)
            if target is None:
                return {"ok": False, "result": f"некорректная дата: {value}"}
            delta = target - (t.start_day or 1)
        else:
            return {"ok": False, "result": f"неизвестный mode сдвига: {mode}"}
        if t.start_day is not None:
            # Копим в start_override (удерживается scheduler'ом через forward_pass),
            # а не только в start_day, который иначе пересчитывается из предшественников.
            base = max(t.start_day, t.start_override or t.start_day)
            t.start_override = base + delta
            t.start_day = max(t.start_day, t.start_override)
            t.end_day = t.start_day + max(1, t.duration_days) - 1
            affected.append(t.name)

    _commit(session, f"shift {len(affected)} задач")
    return {"ok": True, "applied": True, "affected": affected, "state": build_state(session)}


def _parse_offset(value: Any) -> Optional[int]:
    try:
        v = int(value)
        return v
    except (TypeError, ValueError):
        return None


def _parse_day(value: Any) -> Optional[int]:
    """Интерпретация как проектного дня (int) или ISO-даты."""
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        try:
            return int(float(s))
        except ValueError:
            pass
        try:
            import datetime

            d = datetime.date.fromisoformat(s)
            today = datetime.date.today()
            return (d - today).days + 1
        except ValueError:
            pass
    return None


def mcp_set_dependency(session: Session, task: str, depend_on: str, action: str = "add") -> dict:
    t = next((x for x in session.tasks if x.name == task), None)
    if not t:
        return {"ok": False, "error": "not_found", "result": f"задача «{task}» не найдена"}
    if action == "add":
        if not any(x.name == depend_on for x in session.tasks):
            return {"ok": False, "result": f"предшественник «{depend_on}» не найден"}
        if depend_on not in t.predecessors:
            t.predecessors.append(depend_on)
            # проверка цикла
            by_name = {x.name: x for x in session.tasks}
            _, cycle = _topo(by_name)
            if cycle:
                t.predecessors = [p for p in t.predecessors if p != depend_on]
                return {
                    "ok": False,
                    "error": "cycle_predicted",
                    "result": "обнаружен цикл зависимостей, изменений не внесено",
                }
    elif action == "remove":
        if depend_on in t.predecessors:
            t.predecessors.remove(depend_on)
        else:
            return {"ok": True, "applied": False, "affected": [], "new_predecessors": list(t.predecessors)}
    else:
        return {"ok": False, "result": f"неизвестное действие зависимости: {action}"}

    _commit(session, f"зависимость {task} <- {depend_on}")
    return {"ok": True, "applied": True, "affected": [task], "new_predecessors": list(t.predecessors)}


def mcp_add_task(
    session: Session,
    name: str,
    description: str = "",
    assignee: str = "",
    duration_days: int = 1,
    predecessors: Optional[List[str]] = None,
) -> dict:
    if any(t.name == name for t in session.tasks):
        return {"ok": False, "result": f"задача «{name}» уже существует"}
    known = {t.name for t in session.tasks}
    preds = [p for p in (predecessors or []) if p in known]
    from ..core.plan import Task

    session.tasks.append(
        Task(
            name=name,
            description=description,
            assignee=assignee,
            duration_days=duration_days,
            predecessors=list(preds),
        )
    )
    _commit(session, f"add {name}")
    return {"ok": True, "applied": True, "affected": [name]}


def mcp_reassign(session: Session, targets: Dict[str, Any], new_assignee: str) -> dict:
    names = _resolve_from_targets(session, targets)
    affected = []
    for t in session.tasks:
        if t.name in names:
            t.assignee = new_assignee
            affected.append(t.name)
    _commit(session, f"reassign -> {new_assignee}")
    return {"ok": True, "applied": True, "affected": affected}


def mcp_update_field(session: Session, task: str, field: str, value: Any) -> dict:
    t = next((x for x in session.tasks if x.name == task), None)
    if not t:
        return {"ok": False, "error": "not_found", "result": f"задача «{task}» не найдена"}
    if field not in ("name", "description", "assignee", "duration_days"):
        return {"ok": False, "result": f"поле '{field}' не редактируемое"}
    if field == "duration_days":
        try:
            value = max(1, int(value))
        except (TypeError, ValueError):
            return {"ok": False, "result": "длительность должна быть целым положительным числом"}
    setattr(t, field, value)
    _commit(session, f"update {task}.{field}")
    return {"ok": True, "applied": True, "affected": [task]}


def mcp_remove_tasks(session: Session, targets: Dict[str, Any]) -> dict:
    names = _resolve_from_targets(session, targets)
    if len(names) > 100:
        return {"ok": False, "result": "лимит: не более 100 задач за раз"}
    removed = [n for n in names if any(t.name == n for t in session.tasks)]
    drop = set(names)
    session.tasks = [t for t in session.tasks if t.name not in drop]
    for t in session.tasks:
        t.predecessors = [p for p in t.predecessors if p not in drop]
    _commit(session, "remove tasks")
    return {"ok": True, "applied": True, "removed": removed, "affected": removed}


def mcp_undo(session: Session) -> dict:
    v = session.versions.pop()
    if not v:
        return {"ok": False, "result": "нет версий для отката"}
    session.tasks = deep_copy_tasks(v.tasks_snapshot)
    recalc(session)
    return {"ok": True, "applied": True, "version": v.id, "state": build_state(session)}


def mcp_help(session: Session) -> dict:
    return {
        "ok": True,
        "result": "Доступные инструменты: get_schema, get_task, shift_tasks, set_dependency, "
        "add_task, reassign, update_field, remove_tasks, compute, export, undo, help.",
        "state": build_state(session),
    }


# Реестр инструментов: имя -> (функция, обязательные ключи аргументов).
TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "get_schema": {"fn": mcp_get_schema, "need": ["session_id"]},
    "get_task": {"fn": mcp_get_task, "need": ["session_id", "task"], "opts": ["detail"]},
    "shift_tasks": {"fn": mcp_shift_tasks, "need": ["session_id", "targets", "params"]},
    "set_dependency": {"fn": mcp_set_dependency, "need": ["session_id", "task", "depend_on"], "opts": ["action"]},
    "add_task": {"fn": mcp_add_task, "need": ["session_id", "name"], "opts": ["description", "assignee", "duration_days", "predecessors"]},
    "reassign": {"fn": mcp_reassign, "need": ["session_id", "targets", "new_assignee"]},
    "update_field": {"fn": mcp_update_field, "need": ["session_id", "task", "field", "value"]},
    "remove_tasks": {"fn": mcp_remove_tasks, "need": ["session_id", "targets"]},
    "compute": {"fn": mcp_compute, "need": ["session_id"], "opts": ["agg", "field", "by"]},
    "export": {"fn": mcp_export, "need": ["session_id"], "opts": ["format"]},
    "undo": {"fn": mcp_undo, "need": ["session_id"]},
    "help": {"fn": mcp_help, "need": ["session_id"]},
}


def execute(session: Session, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Выполнение whitelist-инструмента над сессией (без eval/exec).

    arguments обычно приходит от MCP-клиента и содержит ключ 'session_id',
    который mcp/server.py отделяет; здесь он стирается для чистых сигнатур.
    """
    entry = TOOL_REGISTRY.get(tool)
    if not entry:
        return {"ok": False, "error": "unknown_tool", "result": f"неизвестный инструмент: {tool}"}
    fn = entry["fn"]
    try:
        args = {k: v for k, v in arguments.items() if k != "session_id"}
        result = fn(session, **args)
        result["tool"] = tool
        return result
    except CycleError as e:
        return {"ok": False, "error": "cycle", "result": str(e)}
    except Exception as e:  # defensive: инструменты не должны падать в REST
        return {"ok": False, "error": "internal", "result": f"{tool}: {e}"}