# -*- coding: utf-8 -*-
"""Автотесты детерминированного intent-парсера (fallback без LLM)."""
import pytest
from app.llm.router import parse_deterministic, split_requests, _parse_add_params, _extract_assignee, _normalize_name

NAMES = [
    "Инициация", "Анализ", "Прототипирование", "Разработка бэкенда",
    "Разработка фронтенда", "Дизайн-система", "База данных", "Интеграция",
    "Нагрузочное тестирование", "Функциональное тестирование", "Документация",
    "Подготовка релиза", "Релиз",
]


def test_shift_task():
    i = parse_deterministic("перенеси задачу Интеграция на 2 дня позже", NAMES)
    assert i.action.value == "shift_tasks"
    assert i.targets.get("tasks") == ["Интеграция"]


def test_add_task_full_name():
    i = parse_deterministic("добавь задачу Подготовка к демо", NAMES)
    assert i.action.value == "add_task"
    assert i.params["name"].lower() == "подготовка к демо"


def test_add_task_short_name():
    i = parse_deterministic("добавь задачу Отчет", NAMES)
    assert i.action.value == "add_task"
    assert i.params["name"].lower() == "отчет"


def test_add_task_with_assignee():
    i = parse_deterministic("добавь задачу для Дарьи проектирование", NAMES)
    assert i.action.value == "add_task"
    assert i.params["assignee"] == "Дарья"
    assert i.params["name"].lower() == "проектирование"


def test_add_task_with_name_and_assignee():
    i = parse_deterministic("добавь задачу для Дарьи название задачи Ветер", NAMES)
    assert i.action.value == "add_task"
    assert i.params["assignee"] == "Дарья"
    assert i.params["name"].lower() == "ветер"


def test_add_task_with_assignee_and_duration():
    i = parse_deterministic("добавь задачу Анне длительностью 3 дня отчет", NAMES)
    assert i.action.value == "add_task"
    assert i.params["assignee"] == "Анна"
    assert i.params["duration_days"] == 3


def test_set_dependency_predecessor():
    i = parse_deterministic("сделай Дизайн-система предшественником Интеграции", NAMES)
    assert i.action.value == "set_dependency"
    assert i.params["task"] == "Интеграция"
    assert i.params["depend_on"] == "Дизайн-система"


def test_set_dependency_dependent():
    i = parse_deterministic("сделай Интеграцию зависимой от Дизайн-система", NAMES)
    assert i.action.value == "set_dependency"
    assert i.params["task"] == "Дизайн-система"
    assert i.params["depend_on"] == "Интеграция"


def test_remove_task():
    i = parse_deterministic("удали задачу Релиз", NAMES)
    assert i.action.value == "remove_tasks"
    assert i.targets.get("tasks") == ["Релиз"]


def test_unknown_help():
    i = parse_deterministic("что-то непонятное бла-бла", NAMES)
    assert i.action.value == "help"


# --- split_requests tests ---------------------------------------------------

def test_split_requests_simple():
    assert split_requests("добавь задачу Ветер") == ["добавь задачу Ветер"]


def test_split_requests_and():
    result = split_requests("добавь задачу Ветер и перенеси Интеграцию на 2 дня")
    assert len(result) == 2
    assert "добавь" in result[0]
    assert "перенеси" in result[1]


def test_split_requests_and_with_continuation():
    """«и поставь» — это новое действие, НЕ продолжение."""
    result = split_requests("добавь задачу для Дарьи и поставь ей статус обычная")
    assert len(result) == 2  # два действия: добавить + поставить статус


def test_split_requests_with_continuation_only():
    """После «и» идёт слово-продолжение (для, название) — не разделяем."""
    result = split_requests("добавь задачу для Дарьи и для Анны")
    assert len(result) == 1


def test_split_requests_complex():
    result = split_requests("добавь задачу Ветер для Дарьи и перенеси Интеграцию на 2 дня позже")
    assert len(result) == 2
    assert "Ветер" in result[0]
    assert "перенеси" in result[1]


# --- _parse_add_params helpers -----------------------------------------------

def test_extract_assignee():
    assert _extract_assignee("добавь задачу для Дарьи") == "Дарья"
    assert _extract_assignee("добавь задачу для Анны") == "Анна"
    assert _extract_assignee("добавь задачу") == ""


def test_parse_add_params():
    name, assignee, duration = _parse_add_params("добавь задачу для Дарьи название задачи Ветер")
    assert name.lower() == "ветер"
    assert assignee == "Дарья"
    assert duration == 1


def test_parse_add_params_only_assignee():
    name, assignee, duration = _parse_add_params("добавь задачу для Дарьи проектирование")
    assert assignee == "Дарья"
    assert name  # какое-то имя есть
    assert duration == 1


def test_normalize_name():
    assert _normalize_name("анну") == "Анна"
    assert _normalize_name("анна") == "Анна"
    assert _normalize_name("дашу") == "Даша"
    assert _normalize_name("дарью") == "Дарья"
    assert _normalize_name("бориса") == "Борис"
