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

# --- Разбивка составных запросов ------------------------------------------------

# Союзы, по которым разделяем многошаговый запрос на отдельные действия.
# НЕ разделяем: внутри кавычек, после «сделай»/«назначь» (идёт дополнение).
_SPLIT_PATTERNS = [
    re.compile(r"\s+и\s+"),          # «сделай Х и добавь Y»
    re.compile(r"\s*,\s*затем\s+"),   # «сделай Х, затем добавь Y»
    re.compile(r"\s*,\s*потом\s+"),   # «сделай Х, потом добавь Y»
    re.compile(r"\s*,\s*после\s+"),   # «сделай Х, после добавь Y»
]

# Слова, которые не начинают новое действие, а продолжают текущее.
_CONTINUATION_WORDS = {"для", "на", "ей", "ему", "им", "с", "со", "статус",
                       "обычная", "название", "длительностью", "исполнитель"}


def split_requests(text: str) -> List[str]:
    """Разделяет составной запрос на отдельные фразы по союзам.

    «добавь задачу Ветер для Дарьи и перенеси Интеграцию на 2 дня»
    → ["добавь задачу Ветер для Дарьи", "перенеси Интеграцию на 2 дня"]

    «добавь задачу и назови её Ветер» → НЕ разделяется
    (слово после «и» — продолжение: «назови»).
    """
    t = text.strip()
    if not t:
        return [t] if t else []

    for pattern in _SPLIT_PATTERNS:
        candidates = []
        idx = 0
        for m in pattern.finditer(t):
            after = t[m.end():].strip().split()[0] if t[m.end():].strip() else ""
            # Если следующее слово — продолжение, а не новое действие — пропускаем
            if after.lower() in _CONTINUATION_WORDS:
                continue
            candidates.append((m.start(), m.end()))
        if candidates:
            # Разбиваем по последнему подходящему разделителю (наиболее вероятно)
            start, end = candidates[-1]
            part1 = t[:start].strip()
            part2 = t[end:].strip()
            if part1 and part2:
                return [part1, part2]

    return [t]


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
    if "зависимост" in t or "зависим" in t or "предшественник" in t:
        # Из текста берём упомянутые известные задачи. Семантика:
        #   «сделай X предшественником Y» → task=Y, depend_on=X;
        #   «сделай Y зависимым от X»    → task=Y, depend_on=X.
        # Проще: последняя известная задача в тексте = task, остальные → depend_on.
        # Матчим по префиксу слова (учитывает русские падежи: «Интеграции» ⊃ «интеграц»).
        def _mention(n: str) -> bool:
            nl = n.lower()
            if nl in t:
                return True
            # слово в тексте начинается с префикса имени (первые 5-7 символов)
            for w in t.split():
                if len(nl) >= 5 and len(w) >= 5 and w.startswith(nl[:5]):
                    return True
            return False

        def _pos(n: str) -> int:
            nl = n.lower()
            i = t.lower().find(nl)
            if i != -1:
                return i
            for w in t.split():
                if len(w) >= 5 and w.startswith(nl[:5]):
                    return t.lower().find(w)
            return 0

        mentioned = [n for n in (known_names or []) if _mention(n)]
        mentioned.sort(key=_pos)  # по порядку в тексте
        if len(mentioned) >= 2:
            # «сделай X предшественником Y» / «сделай Y зависимым от X» → task=последняя, depend_on=первая
            task, depend_on = mentioned[-1], mentioned[0]
        elif len(mentioned) == 1:
            task, depend_on = mentioned[0], _extract_after(t, "предшественник") or ""
        else:
            task, depend_on = "", _extract_after(t, "предшественник") or ""
        return Intent(action=Action.SET_DEPENDENCY,
                      targets={}, params={"task": task,
                                          "depend_on": depend_on,
                                          "action": "add"})

    # 3. Добавление задачи
    if "добав" in t or "новую задачу" in t or "новая задача" in t:
        name, assignee, duration = _parse_add_params(text, known_names)
        return Intent(action=Action.ADD_TASK,
                      params={"name": name or "Новая задача",
                              "description": "", "assignee": assignee, "duration_days": duration})

    # 4. Удаление
    if "удал" in t or "убери" in t or "remove" in t:
        if known_names:
            return Intent(action=Action.REMOVE_TASKS,
                          targets={"tasks": [n for n in known_names if n.lower() in t] or "all"})
        return Intent(action=Action.REMOVE_TASKS, targets={"tasks": "all"})

    # 5. Назначение исполнителя
    if "исполнител" in t or "назна" in t or "кому" in t or "передай" in t or "передайте" in t:
        # Задача = упомянутая в тексте известная задача (если есть).
        mentioned = [n for n in (known_names or []) if n.lower() in t]
        # «назначь АННУ исполнителем …» — имя до слова «исполнител».
        assignee = ""
        m = re.search(r"назна\w+\s+([А-Яа-яЁё]+)", t)
        if m:
            assignee = _normalize_name(m.group(1))
        if not assignee:
            # Исполнитель: имя после «на »/«кому »/«исполнителем », НЕ являющееся задачей.
            for marker in ("исполнителем ", "исполнител ", "кому ", "на ", "исполнителя "):
                idx = t.find(marker)
                if idx != -1:
                    tail = t[idx + len(marker):].strip(" ,.")
                    word = re.split(r"\s+", tail)[0] if tail else ""
                    if word and word.lower() not in [n.lower() for n in mentioned]:
                        assignee = _normalize_name(word)
                        break
        # Для «передай X Борису» — последнее слово (после удаления имён задач)
        if not assignee:
            words = [w for w in re.split(r"\s+", t) if w.lower() not in [n.lower() for n in mentioned]]
            assignee = _normalize_name(words[-1]) if words else ""
        return Intent(action=Action.REASSIGN,
                      targets={"tasks": mentioned or (known_names or [])},
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

# Маппинг всех падежных форм имён → именительный падеж (кто?)
_NAME_FORMS: dict = {
    # Анна
    "анна": "Анна", "анну": "Анна", "анне": "Анна", "анны": "Анна",
    "анной": "Анна", "анною": "Анна",
    # Борис
    "борис": "Борис", "бориса": "Борис", "борису": "Борис", "борисом": "Борис",
    "борисе": "Борис",
    # Вика
    "вика": "Вика", "вику": "Вика", "вике": "Вика", "вики": "Вика",
    "викой": "Вика",
    # Гриша
    "гриша": "Гриша", "гришу": "Гриша", "грише": "Гриша", "гриши": "Гриша",
    "гришей": "Гриша",
    # Дарья
    "дарья": "Дарья", "дарью": "Дарья", "дарье": "Дарья", "дарьи": "Дарья",
    "дарьей": "Дарья",
    # Даша
    "даша": "Даша", "дашу": "Даша", "даше": "Даша", "даши": "Даша",
    "дашей": "Даша",
    # Елена
    "елена": "Елена", "елену": "Елена", "елене": "Елена", "елены": "Елена",
    "еленой": "Елена",
}


def _normalize_name(name: str) -> str:
    """Приводит имя к начальной форме через словарь падежных форм."""
    n = name.strip(" ,.").lower()
    return _NAME_FORMS.get(n, n.capitalize())


def _extract_assignee(text: str) -> str:
    """Извлекает имя исполнителя из текста.

    Ищет по маркерам («для», «исполнитель») и простым перебором всех слов.
    """
    t = text.lower()
    # 1. По маркерам
    # «для Дарьи» / «для Даши» / «для Анны»
    m = re.search(r"для\s+([а-яё]+)", t)
    if m:
        name = _normalize_name(m.group(1))
        if name.lower() in _NAME_FORMS:
            return name
    # «исполнитель ...» / «исполнителем ...»
    m = re.search(r"исполнител[еьм]\s+([а-яё]+)", t)
    if m:
        name = _normalize_name(m.group(1))
        if name.lower() in _NAME_FORMS:
            return name
    # 2. Любое слово из словаря имён («Анне», «Борису» и т.п.)
    for word in re.split(r"\s+", t):
        word = word.strip(" ,.!?;:")
        if word in _NAME_FORMS:
            return _NAME_FORMS[word]
    return ""


def _parse_add_params(text: str, known_names: Optional[List[str]] = None) -> tuple:
    """Парсит ADD_TASK: возвращает (name, assignee, duration_days).

    Извлекает assignee из «для Имя», название из «название задачи ...»,
    длительность из «длительностью N дней».
    """
    assignee = _extract_assignee(text)
    duration = _extract_duration(text)

    # Ищем явное название: «название задачи ...» / «с названием ...»
    t = text
    explicit_name = ""
    for marker in ("название задачи ", "название ", "с названием "):
        idx = t.lower().find(marker)
        if idx != -1:
            explicit_name = t[idx + len(marker):].strip().rstrip(".,;!?")
            break

    if explicit_name:
        return explicit_name, assignee, duration

    # Имя из хвоста после «задачу»/«задача», без «для ...»
    name = _name_after_add(text)
    # Если assignee уже нашли — убираем «для Имя» из имени
    if assignee and name:
        # Убираем «для Даши», «для Дарьи» и т.п. из начала имени
        name = re.sub(r"для\s+\S+\s*", "", name, count=1).strip()
    return name, assignee, duration


def _extract_duration(text: str) -> int:
    """Извлекает длительность: «длительностью N дней» → N."""
    m = re.search(r"длительностью\s+(\d+)\s*дн", text.lower())
    if m:
        return max(1, int(m.group(1)))
    m = re.search(r"на\s+(\d+)\s*дн", text.lower())
    if m:
        return max(1, int(m.group(1)))
    return 1


def _name_after_add(text: str) -> str:
    """Имя новой задачи — хвост после «задачу»/«задача», без окончания («у»/«а»).

    «добавь задачу Подготовка к демо» → «Подготовка к демо» (не «у»).
    """
    t = text
    marker = "задач"
    idx = t.find(marker)
    if idx == -1:
        return ""
    tail = t[idx + len(marker):]  # после «задач» (в т.ч. окончание «у»/«а»)
    # Отбрасываем односимвольное окончание («у»/«а»), если сразу идёт пробел/конец
    if tail and tail[0] in "уа" and (len(tail) == 1 or tail[1] == " "):
        tail = tail[1:]
    return tail.strip()


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
        "Одно действие за раз. target tasks: 'all' или список имён.\n"
        "ВАЖНО: для add_task параметр 'name' должен содержать ТОЛЬКО название задачи, "
        "без указания длительности, исполнителя или других слов. "
        "Длительность (duration_days) и исполнителя (assignee) вынеси в отдельные поля params. "
        "Пример: запрос 'добавь задачу Ветер для Дарьи на 3 дня' → "
        '{"action":"add_task","targets":{},"params":{"name":"Ветер","assignee":"Дарья","duration_days":3,"description":"","predecessors":null},"explanation":"Добавлена задача Ветер для Дарьи на 3 дня"}'
    )


def _clean_add_task_name(intent: Intent) -> None:
    """Очищает name от остатков длительности/исполнителя, если LLM не отделила."""
    if intent.action != Action.ADD_TASK:
        return
    name = intent.params.get("name", "")
    if not name:
        return
    # «на N дней/дня/день» в конце
    cleaned = re.sub(r"\s+на\s+\d+\s+дн[ейя]\s*$", "", name, flags=re.IGNORECASE)
    # «на N дня» (родительный)
    cleaned = re.sub(r"\s+на\s+\d+\s+дня\s*$", "", cleaned, flags=re.IGNORECASE)
    # «длительностью N дней/дня» в конце
    cleaned = re.sub(r"\s+длительностью\s+\d+\s+дн[ейя]\s*$", "", cleaned, flags=re.IGNORECASE)
    # «для Имя» в конце
    cleaned = re.sub(r"\s+для\s+\S+\s*$", "", cleaned)
    cleaned = cleaned.strip()
    if cleaned:
        intent.params["name"] = cleaned


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
    intent = Intent(**data)
    _clean_add_task_name(intent)
    return intent