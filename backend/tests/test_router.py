# -*- coding: utf-8 -*-
"""Автотесты детерминированного intent-парсера (fallback без LLM)."""
from app.llm.router import parse_deterministic

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
