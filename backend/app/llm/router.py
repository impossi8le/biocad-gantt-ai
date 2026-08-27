"""Router: решает, кто парсит текст в Intent — LLM или детерминированный fallback.

Если настроен LLM_API_KEY — используем structured-output запрос к LiteLLM.
Без ключа (демо/тесты) — детерминированный парсер по ключевым словам,
чтобы приложение и весь сценарий «загрузка → чат → экспорт» работали без
внешнего API (NFR-6, mock/fallback-специфика из ARCHITECTURE_PLAN).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..config import llm_enabled
from .intents import Action, Intent

# --- Детерминированный парсер (fallback без LLM) ------------------------------

_FIELD_HINTS: Dict[str, str] = {
    "длительность": "длительность",
    "days": "длительность",
    "дней": "длительность",
    "продолжительность": "длительность",
}


def _find_tasks(text: str) -> List[str]:
    """Простой поиск задач по именам, встречающимся в seed-плане.

    Для fallback-парсера список известных имён берётся из запроса (targets)
    либо из эвристики: не извлекаем реальные имена без seed. На практике
    fallback опирается на `targets`/`params`, заданные явно. Возвращает пустое.
    """
    return []


def parse_deterministic(text: str, known_names: Optional[List[str]] = None) -> Intent:
    """Разбор текста без LLM: первый подходящий action по ключевым словам."""
    t = " ".join(text.lower().split())

    # 1. Массово/перенос (по умолчанию shift, если есть «на N дней»/дата)
    if "перенес" in t or "сдви" in t or "двинь" in t or "позже" in t or "раньше" in t:
        targets: List[str] = []
        if known_names:
            for n in known_names:
                if n.lower() in t:
                    targets.append(n)
        params: Dict[str, Any] = {"mode": "offset", "value": _extract_offset(t)}
        if targets:
            return Intent(action=Action.SHIFT_TASKS, targets={"tasks": targets}, params=params,
                          explanation="перенос задач")
        return Intent(action=Action.SHIFT_TASKS, targets={"tasks": "all"}, params=params,
                      explanation="перенос всех задач")

    # 2. Зависимость
    if "зависимост" in t or "предшественник" in t:
        pred = _after(t, ["от", "после", "на"])
        return Intent(action=Action.SET_DEPENDENCY,
                      targets={}, params={"task": _task_in_text(t, known_names),
                                          "depend_on": pred,
                                          "action": "add"})

    # 3. Добавление задачи
    if "добав" in t or "новую задачу" in t or "новая задача" in t:
        return Intent(action=Action.ADD_TASK,
                      params={"name": _extract_between(t, "задач", ""),
                              "description": "", "assignee": "", "duration_days": 1})

    # 4. Удаление
    if "удал" in t or "убери" in t or "remove" in t:
        if known_names:
            return Intent(action=Action.REMOVE_TASKS,
                          targets={"tasks": [n for n in known_names if n.lower() in t] or "all"})
        return Intent(action=Action.REMOVE_TASKS, targets={"tasks": "all"})

    # 5. Назначение исполнителя
    if "исполнител" in t or "назна" in t or "кому" in t:
        assignee = _extract_after(t, "исполнител")
        return Intent(action=Action.REASSIGN,
                      targets={"tasks": known_names and known_names or []},
                      params={"new_assignee": assignee})

    # 6. Статистика
    if "сумма" in t or "сколько" in t or "статистика" in t or "посчита" in t:
        return Intent(action=Action.COMPUTE, params={"agg": "sum", "field": "duration_days", "by": "assignee"})

    # 7. Экспорт
    if "экспорт" in t or "выгрузи" in t or "скачай" in t:
        return Intent(action=Action.EXPORT, params={"fmt": "xlsx"})

    # 8. Откат / справка
    if "отмен" in t or "откат" in t or "назад" in t:
        return Intent(action=Action.UNDO)
    if "справк" in t or "помощь" in t or "что можешь" in t:
        return Intent(action=Action.HELP)

    return Intent(action=Action.HELP, explanation="не удалось распознать намерение; "
                                                  "переформулируйте или выберите инструмент вручную")


# --- Хелперы для детерминированного разбора -----------------------------------

def _extract_offset(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*дн", text)
    if m:
        return int(m.group(1))
    if "завтра" in text:
        return 1
    if "послезавтра" in text:
        return 2
    return 1


def _task_name_in_text(text: str, known: Optional[List[str]]) -> str:
    if known:
        for n in known:
            if n.lower() in text:
                return n
    return ""


def _extract_after(text: str, marker: str) -> str:
    if marker in text:
        idx = text.index(marker) + len(marker)
        tail = text[idx:]
        m = re.search(r"[\wа-яёА-ЯЁ]+", tail)
        if m:
            return m.group(0)
    return ""


# --- LLM-проход -----------------------------------------------------------------

def build_llm_prompt(text: str, schema: Dict[str, Any], known_names: List[str]) -> str:
    """Промпт первого прохода: LLM возвращает только JSON Intent."""
    return (
        "Ты — ассистент редактора проектного плана (диаграмма Ганта). "
        'Ответь строго JSON-объектом вида {"action": "<инструмент>", "targets": {...}, '
        '"params": {...}, "explanation": "<на русском>"}. '
        "Инструменты: get_schema, get_task, shift_tasks, set_dependency, add_task, "
        "reassign, update_field, remove_tasks, compute, export, undo, help.\n"
        f"Схема плана: {json.dumps(schema, ensure_ascii=False)[:800]}.\n"
        f"Известные задачи: {', '.join(known_names) or '(нет)'}.\n"
        f"Запрос пользователя: {text}\n"
        "Одно действие за раз. target tasks: 'all' или список имён."
    )


def parse_llm_response(raw: str) -> Intent:
    """Разбирает JSON-ответ LLM в Intent (устойчив к markdown-обёртке)."""
    s = raw.strip()
    # отрезаем ```json ... ```
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.DOTALL)
    if m:
        s = m.group(1)
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        raise ValueError("LLM не вернул JSON")
    data = json.loads(m.group(0))
    return Intent(**data)