"""Two-pass LLM-агент над in-process MCP-клиентом.

Проход 1: router.parse → List[Intent] (LLM structured-output ИЛИ fallback).
Проход 2: политика (policy.py) решает — отложить (pending) либо применить.
Наррация по-русски генерируется стримингом и пушится через SSE events
('delta','done'). Агент НЕ исполняет операции сам: только вызывает whitelist
MCP-инструменты через MCPSessionClient.

Стриминг реализован как асинхронный генератор (event-stream), который FastAPI
отдаёт по SSE-соединению; при отсутствии LLM-ключа выдаёт детерминированную
наррацию по чанкам.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from ..config import llm_enabled, get_settings
from ..core.policy import needs_confirmation, policy_decision
from ..core.sessions import Session
from ..mcp.server import MCPSessionClient
from .intents import Action, Intent
from .router import parse_deterministic, split_requests


# --- проход 1: intent (LLM ИЛИ fallback) ---------------------------------------

def resolve_intents(text: str, session: Session) -> List[Intent]:
    """Строит список Intent-ов. Разбивает составной запрос на шаги.

    Разрешает местоимения («её», «его», «ей») через контекст предыдущих шагов.
    """
    fragments = split_requests(text)
    known_names = [t.name for t in session.tasks]
    last_name = ""

    def _resolve(f: str) -> Intent:
        nonlocal last_name
        resolved = f
        for pronoun in ("её", "ее", "его", "ей", "им", "нему"):
            if pronoun in resolved.lower() and last_name:
                resolved = re.sub(r'\b' + pronoun + r'\b', last_name, resolved, flags=re.IGNORECASE)
        intent = parse_deterministic(resolved, known_names=known_names) if not llm_enabled() \
            else _llm_intent(resolved, session)
        if intent.action == Action.ADD_TASK and intent.params.get("name"):
            last_name = intent.params["name"]
        elif intent.action == Action.SET_START_DAY and not intent.params.get("task"):
            intent.params["task"] = last_name
        elif intent.action in (Action.SHIFT_TASKS, Action.REASSIGN, Action.UPDATE_FIELD, Action.REMOVE_TASKS) and last_name:
            targets = intent.targets.get("tasks", [])
            if not targets or targets == "all":
                if last_name not in targets:
                    intent.targets["tasks"] = [last_name]
        return intent

    return [_resolve(f) for f in fragments]


def _llm_intent(text: str, session: Session) -> Intent:
    """Синхронная обёртка над LiteLLM structured-output. При ошибке → fallback."""
    try:
        cfg = get_settings()
        return asyncio.run(_llm_intent_async(text, session, cfg))
    except Exception:
        return parse_deterministic(text, known_names=[t.name for t in session.tasks])


async def _llm_intent_async(text: str, session: Session, cfg) -> Intent:
    from ..llm.router import build_llm_prompt, parse_llm_response

    schema = {
        "n_tasks": len(session.tasks),
        "names": [t.name for t in session.tasks],
        "critical_path": _state_critical(session),
    }
    prompt = build_llm_prompt(
        text,
        schema=schema,
        known_names=[t.name for t in session.tasks],
    )
    import litellm

    messages = [{"role": "user", "content": prompt}]
    kwargs = {}
    if cfg.base_url:
        kwargs["api_base"] = cfg.base_url

    # Gemini НЕ поддерживает response_format json_object, но игнорирует его.
    # Для других провайдеров передаём.
    from ..llm.router import llm_enabled
    kwargs["response_format"] = {"type": "json_object"}

    resp = await litellm.acompletion(
        model=cfg.llm_model,
        messages=messages,
        api_key=cfg.llm_api_key,
        temperature=0.0,
        **kwargs,
    )
    raw = resp.choices[0].message.content
    return parse_llm_response(raw)


def _state_critical(session: Session) -> List[str]:
    by_name = {t.name: t for t in session.tasks}
    from ..core.scheduler import find_critical_path

    return find_critical_path(by_name) if by_name else []


def parse_llm_response(raw: str) -> Intent:
    from .router import parse_llm_response as _p

    return _p(raw)


# --- проход 2: исполнение через MCP + стриминг наррации ------------------------

async def apply_intent_events(
    session: Session, intents: List[Intent], client: MCPSessionClient, stream: bool = True
) -> AsyncIterator[Dict[str, Any]]:
    """Применяет список intent-ов и отдаёт SSE-события.

    Для каждого intent:
    1. intent — диагностика
    2. update — результат применения
    3. delta — чанки наррации
    В конце: done.

    Возвращает генератор событий для /chat/stream.
    """
    plan_size = len(session.tasks)

    for idx, intent in enumerate(intents):
        # Post-process: clean add_task name from duration (LLM часто пишет «Ветер на 3 дня»)
        if intent.action == Action.ADD_TASK and intent.params.get("name"):
            import re as _re
            name = intent.params["name"]
            cleaned = _re.sub(r"\s+на\s+\d+\s+дн[а-яё]+\s*", " ", name, flags=_re.IGNORECASE).strip()
            if cleaned:
                intent.params["name"] = cleaned

        # 1) событие intent — диагностика
        yield {
            "type": "intent",
            "step": idx + 1,
            "total_steps": len(intents),
            "action": intent.action.value,
            "targets": intent.targets,
            "params": intent.params,
            "explanation": intent.explanation,
        }

        # 2) политика
        decision = policy_decision(intent.action, intent.targets, plan_size)
        if decision["need_confirmation"]:
            pending_id = _enqueue_pending(session, intent)
            yield {
                "type": "pending",
                "pending_id": pending_id,
                "reason": decision["reason"],
                "affected_count": decision["affected_count"],
            }
            return

        # 3) применяем
        tool_name = intent.action.value
        result = client.call_tool(tool_name, session.id, _merge_args(intent))
        yield {
            "type": "update",
            "state": session.state(),
            "applied": isinstance(result, dict) and result.get("applied", False),
            "result": result,
        }

        # 4) стриминг наррации
        narration = _compose_narration(intent, result)
        async for chunk in _stream_narration(narration, enabled=bool(llm_enabled())):
            yield {"type": "delta", "text": chunk}

    yield {"type": "done"}


def _merge_args(intent: Intent) -> Dict[str, Any]:
    if intent.action in (Action.REMOVE_TASKS,):
        return {"targets": intent.targets}
    args: Dict[str, Any] = {}
    args.update(intent.targets or {})
    args.update(intent.params or {})
    # выравнивание: shift_tasks ожидает targets/params
    if intent.action == Action.SHIFT_TASKS:
        args = {"targets": intent.targets, "params": intent.params}
    if intent.action == Action.SET_DEPENDENCY:
        args = {k: v for k, v in intent.params.items()}
        args["task"] = (intent.params.get("task") or intent.targets.get("task") or "")
        args["depend_on"] = intent.params.get("depend_on")
        args["action"] = intent.params.get("action", "add")
    if intent.action == Action.REASSIGN:
        args = {"targets": intent.targets, "new_assignee": intent.params.get("new_assignee", "")}
    if intent.action == Action.UPDATE_FIELD:
        args = {"task": (intent.params.get("task") or intent.targets.get("task") or ""),
                "field": intent.params.get("field", ""),
                "value": intent.params.get("value")}
    if intent.action == Action.ADD_TASK:
        args = {
            "name": intent.params.get("name", ""),
            "description": intent.params.get("description", ""),
            "assignee": intent.params.get("assignee", ""),
            "duration_days": intent.params.get("duration_days", 1),
            "predecessors": intent.params.get("predecessors"),
        }
    if intent.action == Action.SET_START_DAY:
        args = {
            "task": intent.params.get("task") or intent.targets.get("task", ""),
            "day": int(intent.params.get("day", intent.params.get("value", 1))),
        }
    if intent.action == Action.COMPUTE:
        args = {k: v for k, v in intent.params.items() if v is not None}
    return args


def _enqueue_pending(session: Session, intent: Intent) -> str:
    import uuid

    pid = uuid.uuid4().hex[:12]
    session.pending[pid] = {
        "tool": intent.action.value,
        "arguments": _merge_args(intent),
        "intent": intent.model_dump(),
    }
    return pid


def _compose_narration(intent: Intent, result: Any) -> str:
    names = (result or {}).get("affected", []) if isinstance(result, dict) else []
    label = {
        Action.SHIFT_TASKS: "перенёс задачи",
        Action.SET_DEPENDENCY: "изменил зависимости",
        Action.ADD_TASK: "добавил задачу",
        Action.REASSIGN: "перераспределил исполнителей",
        Action.UPDATE_FIELD: "обновил задачи",
        Action.REMOVE_TASKS: "удалил задачи",
        Action.COMPUTE: "выполнил вычисления",
        Action.EXPORT: "подготовил экспорт",
        Action.UNDO: "откатил последнее изменение",
    }.get(intent.action, "обновил план")
    affected = ", ".join(names) if names else ""
    result_str = ""
    if isinstance(result, dict):
        result_str = str(result.get("result") or result.get("error") or "").strip()
    return f"{_label(intent.action)}: {affected or 'план'}{' • ' + result_str if result_str else ''}"


def _label(action: Action) -> str:
    return {
        Action.SHIFT_TASKS: "Перенос задач",
        Action.SET_DEPENDENCY: "Изменение зависимостей",
        Action.ADD_TASK: "Добавление задачи",
        Action.REASSIGN: "Перераспределение исполнителей",
        Action.UPDATE_FIELD: "Обновление задач",
        Action.REMOVE_TASKS: "Удаление задач",
        Action.COMPUTE: "Вычисления",
        Action.EXPORT: "Экспорт",
        Action.UNDO: "Откат",
        Action.HELP: "Справка",
        Action.GET_SCHEMA: "Схема",
        Action.GET_TASK: "Детали задачи",
    }.get(action, "Изменение плана")


async def _stream_narration(text: str, enabled: bool, chunk: int = 3) -> AsyncIterator[str]:
    """Отдаёт наррацию по чанкам. Без LLM — детерминированные чанки (демо)."""
    if enabled:
        for i in range(0, max(1, len(text)), chunk):
            yield text[i : i + chunk]
            await asyncio.sleep(0.01)
        return
    # fallback без API: сразу в 1-2 чанка (быстрое демо)
    yield text[: len(text) // 2]
    await asyncio.sleep(0.05)
    yield text[len(text) // 2 :]
    await asyncio.sleep(0.05)


# Асинхронный не-стриминговый intent (для REST /chat non-stream)
async def intents_from_text(text: str, session: Session) -> List[Intent]:
    return await asyncio.to_thread(resolve_intents, text, session)