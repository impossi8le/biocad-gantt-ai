# Gantt AI Plan — AI-native редактор проектного плана

Тестовое задание: **Full-stack разработчик AI-native продукта (React + FastAPI)**.

AI-native планировщик: интерактивная **диаграмма Ганта**, которую можно править на
естественном русском языке через чат — ассистент переносит задачи, меняет
зависимости, добавляет и удаляет задачи, перераспределяет исполнителей, а
изменения **мгновенно** отражаются на диаграмме. План можно загрузить из Excel и
экспортировать обратно.

---

## Ссылки

- **Git-репозиторий:** https://github.com/impossi8le/biocad-gantt-ai
- **Развёрнутое приложение:** http://95.142.46.44:8080 (собственная VM, Docker Compose)

## Демо

| Сценарий | Статус |
|---|---|
| Демо-ссылка | http://95.142.46.44:8080 |
| Пример Excel | [`samples/example.xlsx`](samples/example.xlsx) |
| Дорожная карта → продукта | [`ROADMAP_TO_PRODUCTION.md`](ROADMAP_TO_PRODUCTION.md) |

*Демо-видео/gif сценария «загрузка Excel → правка через чат → экспорт» — добавится
в `docs/demo.gif` (снимается отдельно).*

---

## Запуск

### Локально (бэкенд + фронтенд дев-сервер)

Требования: Python ≥ 3.12, Node ≥ 20.

```bash
# 1) Backend (порт 8000)
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload    # http://localhost:8000

# 2) Frontend (Vite dev, проксирует /api на 8000) — в отдельном терминале
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

Откройте [http://localhost:5173](http://localhost:5173) — увидите Гант с
закешированным стартовым планом (13 задач, ~3 месяца — включает задачи длиннее
месяца). Без `LLM_API_KEY` ассистент работает на детерминированном парсере
(см. ниже).

Шкала Ганта — **стандартная логика**: бары позиционируются по дням (фикс. ширина
дня), при длинном плане появляется горизонтальный скролл. Переключатель «Показывать»:
- **1 неделя** — детально одна неделя (7 дней по дням) с навигацией «‹ ›»
  («Неделя N из M · дни X–Y»);
- **Недели · 5** — страница из 5 недель (≈ месяц, 35 дней) с пагинацией «‹ ›»
  («Стр. N из M · недели X–Y»);
- **Месяц** — полный план, шкала по месяцам (30/31 день: чётный → 30, нечётный → 31).
Задачи длиннее месяца помечены значком «↗» и в тултипе «>1 мес».

### Docker Compose (прод-режим, nginx + backend)

```bash
# задёте LLM_API_KEY в окружении (опционально)
export LLM_API_KEY=...
docker compose up --build
# фронт: http://localhost:8080 (nginx раздаёт статик и проксирует /api на backend)
```

### LLM: ключ или fallback

- **Google AI Studio (бесплатный Gemini, дефолт)** — ключ из [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
  модель по умолчанию `gemini/gemini-3.6-flash` (free tier, rate-limited). Достаточно задать `LLM_API_KEY`; `BASE_URL` не нужен.
- **Любой OpenAI-совместимый роутер** (OpenRouter, RouterAI и т.п.) — задайте `LLM_API_KEY`, `LLM_MODEL`,
  `BASE_URL` (например `https://routerai.ru/api/v1`); используются `litellm`.
- **Без ключа** — работает **детерминированный intent-parse®** (`llm/router.py`):
  чат-сценарий («перенеси … на N дней», «удали …», «добавь задачу …» и пр.)
  полностью работает на тестовых/демо данных. Подходит для демо и тестов.

**Развёрнутое демо:** http://95.142.46.44:8080 (фронт на 8080, бэкенд на 8001).

---

## Архитектура

```
┌──────────────┐   REST/SSE    ┌──────────────────────────────┐
│   Frontend   │◄────────────►│          Backend (FastAPI)   │
│  React 19    │               │  app/core    — model/расписа│
│  Vite 8 + TS │               │                scheduler*,  │
│  Tailwind v4 │               │                versions*,   │
│  nginx (e2e) │               │                policy*,     │
└──────────────┘               │                import/export│
                               │  app/mcp     — tools*, MCPServer (SDK 2.0)
                               │  app/llm     — router*, agent (two-pass)
                               │  app/api     — REST + SSE routes
                               │  SessionStore— in-memory (TTL 30m, LRU 200)
                               └───────────────────────────────────────┘
                     ┌────────────────────────────────────────────────┐
                     │ LLM-агент = MCP-клиент                         │
                     │   первый проход: intent (structured JSON)      │
                     │   второй проход: рус. наррация → SSE 'delta'   │
                     └────────────────────────────────────────────────┘
```

### Ключевые решения

1. **Единый процесс, in-process MCP.** Backend FastAPI + MCP-сервер (Python MCP
   SDK **2.0.0**: `MCPServer`) на одной машине; LLM-агент обращается к плану
   ТОЛЬКО через whitelist MCP-инструменты (`MCPSessionClient.call_tool`), не
   видя сырых данных всего файла. Вынос MCP в отдельный процесс не меняет контракт.
2. **Scheduler-движок** — отдельное ядро: forward pass (тополог. сортировка),
   backward pass (критический путь, CPM), детект циклов, каскадный сдвиг. Правки
   всегда прохожа через него, даты пересчитываются детерминированно. Сдвиг хранится
   `start_override` и удерживается при пересчёте (`scheduler.py`).
3. **Two-pass LLM.** Первый проход — structured output (JSON `Intent{action,
   targets, params, explanation}`), второй — стриминговая народная рус.
   наррация по SSE (`delta`). LLM не имеет «free will»: любое действие
   классифицирует `policy.py` (деструктивное/массовое → подтверждение).
4. **Policy → pending.** Деструктивные (`remove_tasks`) и массовые (`shift`/`reassign`
   на многие задачи) уходят в очередь подтверждения `pending`, единичные — сразу.
5. **Безопасность.** Whitelist-инструменты, `compute` — фикс. pandas-агрегации,
   **нет `eval`/`exec`**, Excel читается через `openpyxl data_only=True`
   (без формул и макросов), CORS ограничен origin фронта.
6. **Undo.** Снапшоты версий (cap 20) в памяти для отката (`US-10`).
7. **Двухпроходность + instant-update** через SSE (`fetch` + `ReadableStream`,
   не `EventSource`), т.к. POST-стрим сожанного чата.

### Структура репозитория

```
backend/
  app/
    core/      plan, scheduler, versions, policy, import_export, sessions
    mcp/       tools (11), server (MCPServer, SDK 2.0)
    llm/       intents, router, agent
    api/       routes (REST+SSE), state
    seed.py, main.py, config.py
    tests/     pytest (28 тестов)
  requirements.txt, Dockerfile
frontend/
  src/components/  GanttChart, TaskModal, ChatPanel, ConfirmModal, Toolbar
  src/             App, api (SSE stream), types, main
  package.json, vite.config.ts
samples/           example.xlsx (пример Excel)
docs/              REQUIREMENTS.md, ARCHITECTURE_PLAN.md, TZ_TEXT.txt
ROADMAP_TO_PRODUCTION.md
docker-compose.yml, Dockerfile.frontend, nginx.conf
```

### REST API (основные)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/session` | создать сессию с **закешированным** стартовым планом |
| GET | `/api/session/{id}` | состояние плана |
| POST | `/api/session/{id}/upload` | загрузить свой `.xlsx`/`.csv` |
| GET | `/api/export/{fmt}?session_id=` | экспорт в Excel/CSV |
| POST | `/api/chat/{id}` | чат-запрос (intent → применение → наррация) |
| GET | `/api/chat/{id}/stream` | то же, **SSE-поток** (`intent/update/delta/done/pending`) |
| POST | `/api/pending/{id}/confirm` · `/cancel` | подтвердить/отменить массовую операцию |
| POST | `/api/session/{id}/undo` | откатить последнее изменение |

Формат Excel: колонки `задача | описание | исполнитель | длительность | предшественники`.

---

## Автор

**Выполнено как тестовое задание.** Ключевые особенности разработки описаны
в `ROADMAP_TO_PRODUCTION.md` (технические долга, риски, порядок закрытия).

## Как использовались AI-ассистенты в разработке

Разработка велась в **AI-native** режиме (это и был один из аспектов задания).
Ниже — честный разбор, где именно ассистент работал, а где — человек.

### Планирование и системный анализ
- **Аналитик + архитектор + согласователь** — роли субагентов (multi-agent
  pipeline): аналитик собрал требования (REQUIREMENTS.md), архитектор
  спроектировал стек/API/MCP (ARCHITECTURE_PLAN.md), согласователь проверил и
  выдал APPROVED. Каждый следующий артефакт строился на результате предыдущего.
- Выбор версий библиотек (React 19, FastAPI 0.141, MCP SDK 2.0, LiteLLM 1.98…)
  сверялся через **веб-поиск** (tavily2), чтобы не угадывать.

### Реализация (developer → devops → QA)
- **Генерация кода**: бэкенд (scheduler, MCP-слой, LLM-агент), фронтенд
  (React-компоненты, Gantt), Docker/Compose, тесты — написаны с Claude
  (Claude Code) в качестве ассистента-разработчика.
- **DevOps**: Docker Compose, nginx, деплой на VM (95.142.46.44), **GitHub
  Actions CI/CD** (pytest + SSH-deploy на каждый push) настроены ассистентом.
- **QA**: автотесты (28 pytest), а также **E2E через Playwright** — ассистент
  заходил в живое приложение, общался с чатом, проверял загрузку/экспорт Excel,
  смену исполнителей, переносы, удаления и **сохранение после перезагрузки**.

### Отладка и исправление
- Ассистент находил и чинил реальные баги: `NameError` в fallback-парсере,
  «add task» создавал задачу «у» (окончание падежа), reassign не понимал
  «передай … на Имя», CORS-конфиг, статик-путь в контейнере, отсутствие
  персистентности. Каждая правка — отдельный коммит.

### Ограничения и ответственность
- AI даёт вероятный output; человек контролировал: безопасность (нет eval/exec,
  `openpyxl data_only=True` без формул), соответствие ТЗ, финальный состав кода,
  тесты (28 pass), деплой и проверку в браузере. Конечный результат проверен
  человеком, ассистент — инструмент.

*Детальный разбор AI-процессов — в `docs/` и `ARCHITECTURE_PLAN.md`.*