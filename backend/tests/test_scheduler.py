"""Scheduler-ядро: топосорт, критический путь, длительности, циклы, агрегаты."""
from __future__ import annotations

import pytest

from app.core.plan import Task
from app.core.scheduler import (
    CycleError,
    aggregate_by,
    find_critical_path,
    forward_pass,
    schedule,
)


def _engine(specs) -> dict[str, Task]:
    return {name: Task(name=name, duration_days=dur, predecessors=list(preds)) for name, dur, preds in specs}


def test_forward_order():
    tasks = _engine([("a", 2, []), ("b", 3, ["a"]), ("c", 4, ["a", "b"])])
    schedule(list(tasks.values()))
    assert tasks["a"].start_day == 1
    assert tasks["b"].start_day == 3  # a окончилась на 2 → старт 3
    assert tasks["c"].start_day == 6  # b окончилась на 5 → старт 6
    assert tasks["c"].end_day == 9


def test_duration_extends_end():
    tasks = _engine([("a", 1, []), ("b", 4, ["a"])])
    schedule(list(tasks.values()))
    assert tasks["a"].end_day == 1
    assert tasks["b"].start_day == 2
    assert tasks["b"].end_day == 5


def test_seed_has_critical_path():
    from app.seed import SEED_TASKS

    cp = find_critical_path({t.name: t for t in SEED_TASKS})
    assert cp, "critical path должен быть непустым"
    assert cp[0] == "Инициация"


def test_cycle_raises():
    tasks = _engine([("a", 1, ["b"]), ("b", 1, ["a"])])
    with pytest.raises(CycleError):
        forward_pass(tasks)


def test_aggregate_rejects_non_whitelist():
    tasks = _engine([("a", 2, []), ("b", 3, [])])
    by = aggregate_by(list(tasks.values()), agg="sum", field="duration_days", by="assignee")
    assert isinstance(by, dict)
    with pytest.raises(ValueError):
        aggregate_by(list(tasks.values()), agg="__import__('os')", field="duration_days", by="assignee")


def test_critical_includes_terminal():
    # Все концевые задачи (без наследников) не имеют запаса по CPM → критичны.
    tasks = _engine([("a", 2, []), ("b", 5, ["a"]), ("c", 1, ["a"])])
    schedule(list(tasks.values()))
    cp = find_critical_path(tasks)
    assert "a" in cp and "b" in cp and "c" in cp


def test_shift_override_is_honored_and_cascades():
    # Сдвиг через start_override должен удерживаться forward_pass и каскадиться на
    # зависимые задачи, но НЕ сжиматься обратно к предшественникам.
    tasks = _engine([("a", 2, []), ("b", 3, ["a"]), ("c", 2, ["b"])])
    schedule(list(tasks.values()))
    assert tasks["b"].start_day == 3
    # сдвигаем b на +2 как mcp_shift_tasks
    b = tasks["b"]
    b.start_override = (b.start_day or 1) + 2
    forward_pass(tasks)
    assert tasks["b"].start_day == 5  # удержано сдвигом
    assert tasks["c"].start_day == 8  # каскад: b закончилась на 7 → c старт 8


def test_critical_mid_chain_has_slack():
    # Сходящиеся ветки к общему стоку: короткая ветка должна иметь запас,
    # даже если она не концевая (sink зависит и от неё, и от длинной b).
    tasks = _engine([
        ("a", 1, []),
        ("x", 1, ["a"]),   # короткая ветка
        ("b", 10, ["a"]),  # длинная ветка — она и задаёт критический путь
        ("sink", 1, ["x", "b"]),
    ])
    schedule(list(tasks.values()))
    cp = find_critical_path(tasks)
    assert "b" in cp      # длинная ветка критична
    assert "sink" in cp   # сток критичен
    assert "x" not in cp  # короткая ветка имеет запас (slack)