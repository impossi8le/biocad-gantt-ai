"""Scheduler — отдельное ядро расписания.

Правки плана всегда проходят через scheduler (каскадный пересчёт).

Алгоритмы (FR-14..FR-16):
- _topo: топологическая сортировка (Кан) + детект циклов.
- forward_pass: start(T) = max(start(P) + duration(P)); отсчёт от первого
  рабочего дня проекта (индекс 0 в расчёте, юзеру → день 1).
- backward_pass / critical: критический путь (длиннейшая цепочка без запаса).

Никаких eval/exec; чистые детерминированные вычисления для юнит-тестов.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Tuple

from .plan import Task


class CycleError(Exception):
    """Граф зависимостей содержит цикл."""

    def __init__(self, cycle: List[str]):
        self.cycle = cycle
        super().__init__("Обнаружен цикл зависимостей: " + " -> ".join(cycle))


def _topo(tasks: Dict[str, Task]) -> Tuple[List[str], Optional[List[str]]]:
    """Kahn topological sort. Возвращает (order, cycle_or_None)."""
    by_name = {t.name: t for t in tasks.values()}
    indeg: Dict[str, int] = {n: 0 for n in by_name}
    adj: Dict[str, List[str]] = {n: [] for n in by_name}
    for name, task in by_name.items():
        for p in task.predecessors:
            if p in by_name:
                adj[p].append(name)
                indeg[name] += 1
            # неизвестный предшественник: игнорируем (не ломаем сортировку)
    q = deque([n for n, d in indeg.items() if d == 0])
    order: List[str] = []
    while q:
        n = q.popleft()
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    if len(order) != len(by_name):
        # Находим замкнутый цикл через обратные рёбра.
        start = next(n for n, d in indeg.items() if d > 0)
        path, seen, cur = [], set(), start
        while cur not in seen:
            seen.add(cur)
            path.append(cur)
            prevs = [p for p in by_name[cur].predecessors if p in by_name and indeg[p] > 0]
            if not prevs:
                break
            cur = prevs[0]
        cycle = path + [path[0]] if path else [start]
        return order, cycle
    return order, None


def check_cycle(tasks: Dict[str, Task]) -> Optional[List[str]]:
    """Список имён задач цикла или None, если циклов нет."""
    _, cycle = _topo(tasks)
    return cycle


def forward_pass(tasks: Dict[str, Task]) -> None:
    """Вычисляет start_day/end_day (1-based) для всех задач. Мутирует на месте."""
    order, cycle = _topo(tasks)
    if cycle:
        raise CycleError(cycle)
    for name in order:
        task = tasks[name]
        earliest = 0  # индекс 0 в расчёте = первый рабочий день проекта
        for p in task.predecessors:
            pred = tasks.get(p)
            if pred and pred.end_day is not None:
                earliest = max(earliest, pred.end_day)
        computed = earliest + 1  # на следующий день после позднейшего конца предшественника
        # Явный сдвиг (start_override) удерживает позицию вместо пересчёта из
        # предшественников; каскад держит order топосорта, чтобы не создавать
        # новых конфликтов с датами зависимых задач.
        if task.start_override is not None:
            task.start_day = max(computed, task.start_override)
        else:
            task.start_day = computed
        task.end_day = task.start_day + task.duration_days - 1


def find_critical_path(tasks: Dict[str, Task]) -> List[str]:
    """Backward pass → критический путь. Проставляет флаг critical на задачи.

    latest_end(T) = самому позднему допустимому концу, не ломая зависимостей:
      - без наследников → end_day задачи;
      - иначе → min( latest_end(next) - 1 ) по наследникам.
    Задача критическая, если latest_end == end_day (нет запаса).
    """
    by_name = {t.name: t for t in tasks.values()}
    if not by_name:
        return []
    order, cycle = _topo(tasks)
    if cycle:
        return []
    if any(t.end_day is None for t in by_name.values()):
        forward_pass(tasks)

    latest_end: Dict[str, int] = {}
    for name in reversed(order):
        task = by_name[name]
        # Для поставщика start/end успешной задачи гальванизироваться как
        # earliest-сдвижение: T должна закончиться не позже LS(successor)-1.
        # LS(successor) = latest_end(successor) - duration(successor) + 1.
        succ_latest_start = [
            latest_end[s] - by_name[s].duration_days for s, t in by_name.items() if name in t.predecessors
        ]
        latest_end[name] = min(succ_latest_start) if succ_latest_start else task.end_day

    critical: List[str] = []
    for name in order:
        task = by_name[name]
        if latest_end[name] == task.end_day:
            task.critical = True
            critical.append(name)
        else:
            task.critical = False
    return critical


def schedule(tasks: List[Task]) -> Tuple[List[Task], Optional[List[str]], List[str]]:
    """Полный пересчёт: топосорт + forward + критический путь.

    Returns: (задачи с датами, цикл_или_None, critical_path).
    """
    by_name = {t.name: t for t in tasks}
    _, cycle = _topo(by_name)
    if cycle:
        return tasks, cycle, []
    forward_pass(by_name)
    critical = find_critical_path(by_name)
    return list(by_name.values()), None, critical


def total_days(tasks) -> int:
    """Общая длительность проекта в рабочих днях (наибольший end_day)."""
    ends = [t.end_day for t in tasks if t.end_day is not None]
    return max(ends) if ends else 0


# Whitelist агрегаций для compute (без eval/exec). {имя: sql-подобная опция}
AGG_WHITELIST: Dict[str, str] = {
    "sum": "sum",
    "avg": "mean",
    "mean": "mean",
    "min": "min",
    "max": "max",
    "median": "median",
    "count": "count",
}


def aggregate_by(
    tasks: List[Task], agg: str = "sum", field: str = "duration_days", by: str = "assignee"
) -> Dict[str, float]:
    """Фиксированные pandas-агрегации по полю и группе, без eval/exec.

    Возвращает {группа: значение}. Поле и агрегат — из whitelist.
    """
    import pandas as pd

    if agg not in AGG_WHITELIST:
        raise ValueError(f"агрегация '{agg}' недоступна (whitelist: {list(AGG_WHITELIST)})")
    rows = [t.detail_dict() for t in tasks]
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    if df.empty:
        return {}
    if field not in df.columns:
        raise ValueError(f"поле '{field}' недоступно для агрегации")
    if by and by not in df.columns:
        raise ValueError(f"группа '{by}' не найдена в плане")
    grouped = df.groupby(by)[field].agg(AGG_WHITELIST[agg])
    return {str(k): (float(v) if not pd.isna(v) else 0.0) for k, v in grouped.items()}