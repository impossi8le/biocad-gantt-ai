# Архитектура и план реализации — AI-native редактор проектного плана (Гант + чат)

> Было: PDF/RAG «Научный помощник» (неверная трактовка ТЗ). **Исправлено** под фактическое ТЗ из `docs/TZ_TEXT.txt`: интерактивная диаграмма Ганта + чат массового редактирования плана + Excel import/export + MCP + LLM.
> Версии исследованы на 2026-08-27. **Реализовано:** развёрнуто на VM (95.142.46.44:8080), Docker Compose, GitHub Actions CI/CD, 40 автотестов.

---

## 1. Резюме решения

Одностраничное (single-view) демо-приложение: **диаграмма Ганта — центральный элемент**. При открытии сразу виден Гант с закешированной тестовой выборкой задач. Пользователь может загрузить свой `.xlsx` (колонки `задача,описание,исполнитель,длительность,предшественники`), править план массово через чат на естественном языке (перенос задач, зависимости, добавление, перераспределение исполнителей), кликом открывать модаль задачи, и экспортировать план обратно в Excel.

Ключевые архитектурные решения:

1. **Единый процесс для демо (FastAPI)**. LLM-слой (LiteLLM) не трогает дата-модель напрямую — он работает как **MCP-клиент** (SDK v2, единый `Client`), вызывающий инструменты `get_schema/get_task/shift_tasks/set_dependency/add_task/reassign/update_field/remove_tasks/compute/export`. MCP-сервер (`MCPServer`) — in-process изолированный модуль, не знающий про REST; на проде выносится в отдельный контейнер (streamable-HTTP/SSE) без смены контрактов.
2. **Модель плана — in-memory**: список задач (id, задача, описание, исполнитель, длительность, предшественники) + **движок расписания** (forward pass по зависимостям → даты старта/конца, критический путь). Стек версий-снапшотов (undo, cap 20), очередь pending-подтверждений для деструктивных операций, TTL сессии 30 мин. БД нет — осознанный техдолг (в roadmap).
3. **Приватность**: в LLM уходит компактное представление плана (названия+даты+исполнители) и точечные результаты инструментов, не сырой файл; при загрузке значения читаются `openpyxl data_only=True` (без формул/макросов).
4. **Безопасность**: все операции — whitelist-инструменты; `compute` — только фиксированные агрегации pandas, без `eval`/`exec`; циклы зависимостей отклоняются; CORS — только фронтенд-origin.
5. **Политика подтверждений — правило бэкенда**: `shift_tasks` (массовый), `remove_tasks`, `update_field` по всей колонке → `pending` + `ConfirmModal`; единичная правка — сразу.
6. **Two-pass LLM**: (1) не-стриминговый structured-output → `Intent {action,targets,params,explanation}` (pydantic, 1 retry при некорректном JSON); (2) стриминговый вызов → человекочитаемая наррация по-русски (SSE). Ошибки парсинга → уточнение у пользователя.
7. **Мгновенное отражение правок**: после каждого MCP-вызова движок пересчитывает расписание, и по SSE летит событие `update` с положением задач → Гант перерисовывается без перезагрузки.
8. **UI на русском**, монохром по `DESIGN.md` (Geist, радиусы 18/24, красный — только destructive): слева Гант (центр), справа чат, сверху тулбар (загрузка/undo/versions/экспорт), модаль задачи, ConfirmModal.

Deliverables (ТЗ): README (запуск, архитектура, решения, раздел «Как использованы AI-ассистенты»), развёрнутая ссылка (Render/Fly.io/VM), демо-gif «загрузка Excel → правка чатом → экспорт», пример Excel в `samples/`, `ROADMAP_TO_PRODUCTION.md`, git-репозиторий.

---

## 2. Стек технологий и структура репозитория

### 2.1 Обоснование выбора стека

| Компонент | Выбор | Почему / trade-off |
|---|---|---|
| Frontend | React + Vite 8 + TypeScript ~5.6 | Быстрая сборка, типизированные контракты, зрелость экосистемы. |
| Диаграмма Ганта | **собственный компонент** (React + CSS grid, absolute-бары) | ТЗ — интерактив + монохром по DESIGN.md; лёгкий канvas без тяжёлых библиотек, интерактив на обычном стейте. Fallback — готовая библиотека при необходимости. |
| Backend | FastAPI 0.141.1 | Async, SSE из коробки, pydantic v2. |
| MCP | MCP Python SDK **2.0.0** | Прямое требование ТЗ; v2 (28.07.2026): `MCPServer` + единый `Client`, `@server.tool()`. |
| Excel | openpyxl 3.1.x + pandas 2.2.x | Чтение/запись `.xlsx` (data_only, без формул) + компактная модель плана и агрегации. |
| LLM | LiteLLM 1.98.0 | Единый интерфейс к OpenAI/Anthropic/Ollama, стриминг, смена модели через env. |
| Сессии | in-memory dict + asyncio-lock + TTL-sweep | Для demo достаточно; Redis — техдолг. |
| Деплой | Docker Compose (backend + frontend через nginx) **и** развёрнутая ссылка (Render/Fly.io/VM) | Обе цели из ТЗ. |

### 2.2 Дерево репозитория

```
biocad-gantt-ai/                      (имя репо из ссылки git)
├─ README.md                          # запуск (local + развёрнутый), архитектура, решения,
│                                     # раздел «Как использованы AI-ассистенты»
├─ ROADMAP_TO_PRODUCTION.md           # обязательный deliverable
├─ docker-compose.yml                 # services: backend, frontend (nginx)
├─ nginx/nginx.conf                   # статика + proxy /api, SSE off-buffer
├─ .env.example                       # LLM_MODEL, ключ, CORS_ORIGINS, SESSION_TTL, лимиты
├─ .gitignore                         # не пускает .env*, node_modules, .venv
├─ docs/                              # REQUIREMENTS.md, ARCHITECTURE_PLAN.md (данный), DESIGN.md
├─ samples/проект_пример.xlsx         # пример Excel для теста (та же возможная форма)
├─ demo/demo.gif                      # «загрузка Excel → правка чатом → экспорт»
├─ backend/
│  ├─ Dockerfile, pyproject.toml
│  ├─ app/
│  │  ├─ main.py                      # create_app, lifespan (MCP + TTL-sweep), CORS
│  │  ├─ config.py                    # pydantic-settings
│  │  ├─ seed.py                      # закешированная тестовая выборка задач (для US-1)
│  │  ├─ api/
│  │  │  ├─ routes_session.py         # POST /api/session, state, tasks, versions, undo, confirm/cancel
│  │  │  ├─ routes_chat.py            # POST .../chat/stream (SSE)
│  │  │  ├─ routes_upload.py          # POST .../upload
│  │  │  └─ routes_export.py          # GET .../export
│  │  ├─ core/
│  │  │  ├─ sessions.py               # SessionStore: dict, TTL-sweep, per-session asyncio.Lock
│  │  │  ├─ plan.py                   # Session-модель плана (задачи, предшественники)
│  │  │  ├─ scheduler.py              # forward pass + критический путь + циклы (ядро)
│  │  │  ├─ import_export.py          # openpyxl: read (data_only) / write, csv, sanitize
│  │  │  ├─ versions.py               # снапшоты-undo, cap=20
│  │  │  └─ policy.py                 # классификация деструктивных/массовых
│  │  ├─ llm/
│  │  │  ├─ router.py                 # LiteLLM completion/stream, retry, timeout
│  │  │  ├─ intents.py                # pydantic Intent + instructions (structured output)
│  │  │  ├─ context.py                # компакт-представление плана + history + tool-результаты
│  │  │  └─ agent.py                  # цикл: intent → policy → MCP-вызов → наррация (SSE)
│  │  └─ mcp/
│  │     ├─ server.py                 # MCPServer (v2), регистрация инструментов
│  │     └─ tools.py                  # 9 инструментов через SessionStore + scheduler
│  └─ tests/                          # pytest: scheduler, import/export, tools, policy, versions, chat
└─ frontend/
   ├─ Dockerfile (multi-stage: node build → nginx), package.json, vite.config.ts, tsconfig.json
   └─ src/
      ├─ main.tsx, App.tsx            # layout: GanttChart | ChatPanel | Toolbar
      ├─ api/client.ts                # fetch + fetch-стрим чтение SSE
      ├─ types/models.ts              # Task, PlanState, Intent, ConfirmPayload
      ├─ store/session.ts             # zustand: sessionId, tasks, versions, pending
      ├─ lib/iso.ts                   # DATE<->DAY utils
      └─ components/
         ├─ GanttChart.tsx          # лента времени, бары, стрелки, клик → TaskModal
         ├─ TaskModal.tsx          # детали задачи (состав решаем сами)
         ├─ ChatPanel.tsx            # сообщения, стриминг, markdown
         ├─ ConfirmModal.tsx          # подтверждение массовых
         └─ Toolbar.tsx               # upload, undo, versions, export
```

Границы: `backend/app/mcp/` не импортирует FastAPI и не знает про REST — только `SessionStore`/`scheduler` по интерфейсу → выносимо в отдельный процесс. `backend/app/llm/` не трогает план напрямую — только через MCP-клиент. LLM-слой — первый реальный потребитель MCP-контрактов (self-host проверяет контракты).

---

## 3. Архитектура и data-flow

### 3.1 Компоненты

```
        React SPA (Vite)                     FastAPI app (единый процесс, demo)
 ┌──────────────┐  REST + SSE   ┌─────────────────────────────────────────────────┐
 │ GanttChart   │ ────────────▶  │ api/routes_*                                    │
 │ ChatPanel    │                │   │  routes_session (state,upload,confirm,undo) │
 │ ConfirmModal │                │   │  routes_chat (SSE)  · import/export          │
 │ TaskModal    │ ◀────────────  │   ▼                                             │
 └──────────────┘                │  llm/ agent (2-pass intent + наррация)          │
        ▲                        │   │  router.py (LiteLLM)                        │
        │ state+update (SSE)     │   ▼                                             │
        │                        │  MCP Client (v2) ◀──▶ MCP Server (MCPServer v2) │
        │                        │  │  tools: get_schema/get_task/shift_tasks/     │
        │                        │  │  set_dependency/add_task/reassign/           │
        │                        │  │  update_field/remove_tasks/compute/export    │
        │                        │  ▼                                              │
        │                        │  SessionStore (задачи, versions, pending, TTL)  │
        │                        │  Scheduler (forward pass, каскад, critical)     │
        │                        │  import/export (openpyxl data_only, sanitize)   │
        │                        └────────────────────────────────────────────────┘
        │                                          │ LLM HTTP (LiteLLM)
        │                                          ▼
        │                              Внешний LLM API (ключ из env) / local Ollama
```

### 3.2 Как FastAPI взаимодействует с MCP (in-process, изолированный модуль)

- `app/mcp/server.py` создаёт `MCPServer` (SDK v2) `"gantt_plan"`; инструменты — декоратор `@server.tool()`.
- `app/llm/agent.py` создаёт MCP-`Client` v2, подключается к серверу по in-memory транспорту, вызывает `client.call_tool("add_task", {...})`.
- `SessionStore` + `scheduler` инжектятся в инструменты при регистрации; MCP-слой не знает про REST.

Trade-off: один процесс и контейнер, нет сетевой хрупкости, общий state без пересылки DataFrame, простой дебаг. Минус: MCP не отдельно разворачиваемая единица. Прод-переход (в `mcp/README.md` / roadmap): тот же `server.py` запускается standalone с streamable-HTTP/SSE транспортом, FastAPI держит `Client` по сети; инструменты и контракты не меняются.

### 3.3 Data-flow полного сценария «загрузка Excel → правка чатом → экспорт»

1. **Открытие + тестовые данные.** `POST /api/session` → создаёт сессию, `seed.py` заваливает кешированную выборку задач. `GET /api/session/{id}/state` → схема + задачи (с вычисленными датами) + критический путь. Frontend рисует Гант.
2. **Загрузка Excel.** `POST /api/session/{id}/upload` (multipart .xlsx/.csv). `openpyxl data_only=True` → значения без формул/макросов; сопоставление колонок `задача/описание/исполнитель/длительность/предшественники`; `scheduler` считает даты; задачи заменяются. Ошибки (нет колонки, пустой лист) → 400 с именем.
3. **Чат на естественном языке.** `POST /api/session/{id}/chat/stream` (SSE). Сбор контекста (компактное представление плана, история, последние tool-результаты) → **первый вызов LLM** — strict structured output → `{action:"shift_tasks", targets:{…}, params:{offset_days:14}, explanation:"…"}`.
4. **Policy.** Классификация: единичное/массовое/деструктивное.
5. **Выполнение через MCP.** Агент вызывает инструмент; инструмент мутирует план через `SessionStore` + `scheduler`. Пересчитывает расписание, критический путь; возвращает `{ok, affected, diff}`. Движок валидирует циклы (отклонение) и каскадно двигает зависимых.
6. **Мгновенное обновление.** Сразу после мутации агент шлёт SSE-событие `update` (актуальные задачи) → **Гант перерисовывается**.
7. **Наррация.** Второй вызов LLM (стриминг) → объяснение по-русски (SSE `delta`). Если `pending` — фронт показывает `ConfirmModal`, по `POST /confirm` применяется тот же отложенный MCP-вызов (outbox), по `cancel` — отменяется.
8. **Уточнения.** Intent не распознан → только read-инструменты, или запрос уточнения; некорректный JSON → 1 retry → честный ответ «уточните».
9. **Undo.** `POST /api/session/{id}/undo` — возврат версии из стека; `versions` список в тулбаре.
10. **Экспорт.** `GET /api/session/{id}/export?format=xlsx|csv` — `export.py` пишет задачи + вычисленные даты, sanitize имени, Content-Disposition.

Сквозной принцип: **LLM не получает весь файл целиком**; любой доступ — через точечные инструменты; большие операции всегда видны пользователю через pending/diff.

---

## 4. Модель состояния сессии

### 4.1 Сущности (`core/plan.py`, `core/versions.py`)

```python
class Task:
    id: str
    name: str            # «задача»
    description: str     # «описание»
    assignee: str        # «исполнитель»
    duration_days: int   # «длительность»
    predecessors: list[str]  # «предшественники» — имена задач
    # вычислено scheduler:
    start_day: int       # 1-based рабочий день проекта
    end_day: int
    critical: bool

class PlanSchema:
    columns: ["задача","описание","исполнитель","длительность","предшественники"]
    n_tasks: int
    total_days: int
    critical_path: list[str]
    source_filename: str

class Intent:    # то же JSON-schema для LLM (см. §7)
    action: Literal["get_schema","get_task","shift_tasks","set_dependency",
                    "add_task","reassign","update_field","remove_tasks",
                    "compute","undo","help"]
    targets: dict     # {tasks:[...]} | {task}| {column:...}
    params: dict      # {offset_days,value,assignee,format,...}
    explanation: str

class PendingOp:
    id: str; tool: str; arguments: dict; diff: str; preview: list; created_at; ttl

class Version:        # снапшот плана для undo
    id:int; label:str; tasks_snapshot: list[Task]; created_at
```

### 4.2 Где хранится (`core/sessions.py`)

`SessionStore`: `dict[Session]`, глобальный `asyncio.Lock`, `ttl_seconds=1800`, `max_sessions=200` (LRU-evict старейших). У каждой сессии свой `asyncio.Lock` — съёмка консистентности на запись. TTL-sweep — фоновый task в `lifespan` каждые 60 c. При мутациях: `versions.push(snapshot)` перед изменением; стек 20, старые срезаются. `undo`: вернуть `tasks_snapshot` и пересчитать расписание.

Особые случаи: файл >100 000 ячеек → отклонение; пустой лист → 400; несколько листов → первый активный (roadmap: выбор листа).

---

## 5. REST API (без MCP)

Префикс `/api`. Ответ: `{ok, data|error:{code,message}}`.

| Метод | Путь | Тело / Query | Ответ |
|---|---|---|---|
| `POST` | `/api/session` | — | `201 {session_id, state}` (seed) |
| `GET` | `/api/session/{id}/state` | — | `{schema, tasks, plan, pending, version_head}` |
| `POST` | `/api/session/{id}/upload` | multipart .xlsx/.csv ≤20MB | `200 {state}` / 400, 413 |
| `POST` | `/api/session/{id}/chat/stream` | `{message}` | SSE |
| `POST` | `/api/session/{id}/confirm` | `{pending_id}` | `{applied,diff,state}` / 409 |
| `POST` | `/api/session/{id}/cancel` | `{pending_id}` | `{cancelled:true}` |
| `POST` | `/api/session/{id}/undo` | — | `{version_head,label,diff}` / 409 |
| `GET` | `/api/session/{id}/versions` | — | `{versions[], head}` |
| `GET` | `/api/session/{id}/export` | `?format=xlsx\|csv` | binary, Content-Disposition / 400 |
| `GET` | `/api/health` | — | `{status:"ok"}` |

### SSE-протокол `/chat/stream`

```
event: intent      data: {"action":"add_task","targets":{},"params":{...},"explanation":"…"}
event: update      data: {"tasks":[...],"plan":{..., "critical_path":["…"]}}   # гант перерисуется
event: delta       data: {"text":"Готово: добавлена задача «Тестирование»…"}    # повторы
event: pending     data: {"pending_id":"…","tool":"remove_tasks","preview":[...],"diff":"…"}
event: done        data: {"status":"applied"|"pending"|"help"|"error","reason":"…"}
```

Порядок: `intent` → (при успехе) `update` → `delta`* → `pending`? → `done`. Frontend читает через `fetch` + `ReadableStream` (POST → не EventSource).

---

## 6. Схема MCP-инструментов (9)

Все инструменты получают `session_id`; вход/выход в JSON-нотации. `scheduler` вызывается после каждой правки.

### 6.1 `get_schema`
Вход `{session_id}`. Выход `{ok, schema:{n_tasks,total_days,critical_path,columns,header_row}}`. Read-only, «словарь языка» для LLM (имена задач доступны).

### 6.2 `get_task`
Вход `{session_id, task: str, detail?: "compact"|"full"}`. Выход `{ok, task|None}`. Read-only, точечное чтение (для контекста и проверки diff).

### 6.3 `shift_tasks`
Вход `{session_id, targets: {tasks: all|[...names], mode: offset|to_date, value: int|"2026-09-01"}}`. Деструктивное/массовое → **pending** (+ каскад через scheduler). Выход (pending): `{applied:false, status:"pending_confirmation", pending_id, diff:"Сдвинуты N задач на 14 дн"}`.

### 6.4 `set_dependency`
Вход `{session_id, task, depend_on: str, action:"add"|"remove"}`. Обычная правка → применяется сразу; если образуется цикл — `{ok:false, reason:"cycle_predicted", result}` и план не меняется. Возвращает `{ok, applied, affected, new_predecessors}`.

### 6.5 `add_task`
Вход `{session_id, name, description?, assignee?, duration_days?, predecessors?}`. Применяется сразу (недеструктив), push версии, пересчёт.

### 6.6 `reassign`
Вход `{session_id, targets: {tasks: all|[...], new_assignee: str}}`. Массивное → pending при `all`; единичное → сразу.

### 6.7 `update_field`
Вход `{session_id, task, field:"name"|"description"|"assignee"|"duration_days", value: str|int}`. Одиночная правка → сразу; если affected>1 → pending. Валидация dtype, length.

### 6.8 `remove_tasks`
Вход `{session_id, targets: {tasks:[...] }}`. **Всегда** pending (деструктивно), аргументы сохраняются для replay на `/confirm`; лимит 100 задач.

### 6.9 `compute`
Вход `{session_id, agg:"sum"|"avg"|"min"|"max"|"median"|"count", field:"duration_days"|..., by?: "assignee"}`. Whitelist-агрегация через pandas; без `eval`/`exec`; не деструктивно, результат в `tool_log` и контекст модели.

### 6.10 `export`
Вход `{session_id, format:"xlsx"|"csv"}`. Выход `{ok, format, filename, bytes}` (в REST — attachment).

---

## 7. Двухпроходный LLM (intent + наррация)

- **Шаг 1 — structured-output.** `router.py` собирает системный промпт с JSON-схемой `Intent` (pydantic; примеры команд RU + их интенты). Non-streaming вызов. Pydantic-валидация → если ошибка, 1 retry с текстом ошибки → иначе переход в режим «уточни вопрос».
- **Шаг 2 — наррация.** Стриминг `stream=True`. Модель получает результат MCP-вызова (`{affected, diff}`) и строит слитный текст «Что изменено». SSE-токены.
- Контекст (шаг 1+2): compact-представление плана (список `name | assignee | dur | preds | start-end | critical`, сечённое), история диалога (обрезана), последние K tool-результатов. Никогда не весь исходный файл.
- Таймаут 60 c, retry с backoff (3), каскад — ответственность scheduler, а не модели.

---

## 8. Движок расписания (`core/scheduler.py`)

- Вход: задачи с `predecessors`, `duration_days`.
- **Топологическая сортировка** (Kahn). Цикл → `ok:false, cycle:[...]` (в `set_dependency`/`upload`).
- **Forward pass**: `start(T)=max(start(P_)+duration(P_))` над её предшественниками; `end=start+duration`. Отсчёт от первого рабочего дня проекта (индекс 0 в расчёте, юзеру — день 1). Каскад после любой правки.
- **Backward pass** → **критический путь** (правила: задачи, у которых нет запаса, флаг `critical`).
- Юнит-тесты: топосортировка, каскад при сдвиге, крительный путь, циклы — обязательный гейт (NFR-8, R-5).

---

## 9. Пошаговый план реализации

- **Этап A — Каркас**: `.env.example`, `.gitignore`, `docker-compose.yml`, backend config, `/api/health`, базовая сессия + seed, frontend scaffold (Vite+TS+Tailwind v4+Geist, globals.css @theme), `GET /api/session` показать Гант.
- **Этап B — План и движок**: `core/plan.py` + `core/scheduler.py` (forward/backward, critical, ticket-циклы) + seed данных; `versions.py` (undo). Tests.
- **Этап C — Excel**: `core/import_export.py` (upload/export, openpyxl data_only, sanitize, .csv), routes_upload/export, ошибки формата.
- **Этап D — MCP-слой**: `mcp/server.py` + `mcp/tools.py` (9 инструментов), `policy.py`, contравятся к SessionStore/scheduler. Интеграционные тесты (без LLM).
- **Этап E — LLM-агент + чат**: `llm/intents.py`, `context.py`, `router.py`, `agent.py`; SSE-proтокол (intent/update/delta/pending/done), ConfirmModal. Интеграция загрузки → чат → экспорт.
- **Этап F — Frontend-центр**: `GanttChart` (Physics, зависимости-стрелки, modal), `TaskModal`, `ChatPanel` (markdown, усмотрение), `Toolbar` (upload/undo/versions/export), store.
- **Этап G — Дизайн/DEFAULT**: строгое соответствие `DESIGN.md`; состояния loading/empty/error.
- **Этап H — Ops + deliverables**: nginx(SSE), Dockerfile multi-stage, деплой на сервер (Render/Fly/Io/VM), README (запуск/архитектура/решения/AI-раздел), `demo.gif`, `samples/проект.xlsx`, `ROADMAP_TO_PRODUCTION.md`.
- **Этап I — QA/pytest**: покрытие scheduler/import/export/policy ≥60%, ≥5 интеграционнных; ручной прогон сценария ТЗ; демо-gif.

---

## 10. Дизайн-система (из `DESIGN.md`, отражено в README)

Монохромная светлая shadcn/ui: canvas `#f5f5f5`, paper `#ffffff`, surface-alt `#fafafa`, ink `#0a0a0a`, ink-soft `#171717`, mid-gray `#737373`, hairline `#e5e5e5`, **Ember `#e7000b` только destructive/error**. Радиусы 18 px (интерактив) / 24 px (карточки). Шрифт Geist. Трёхтоновые поверхности canvas→sidebar→card. Tailwind v4 `@theme` в `globals.css`. Задачи-бары Ганта — пассив цвета по исполнителю (не Ember), критика — штрих/усиление.

---

## 11. Риски и предположения

**Риски**: R-A дрейф MCP SDK v2 → фиксация `mcp==2.0.0`, in-process изоляция; R-B бесплатный хостинг (Render) останавливает демо → повтор первичного запроса + локальный запуск 1 командой; R-C каскад при сдвиге → юнит-тесты scheduler как гейт; R-D SSE буферизируется nginx → `proxy_buffering off` + `X-Accel-Buffering: no`; R-E неверный intent LLM → strict JSON, retry, «уточнить», read-only. 

**Предположения**: one пользователь, без auth; plan in-memory (нет БД) — техдолг; LLM через API (ключ из env), Ollama optional fallback; диаграмма собственный компонент; срок demo 30 мин TTL.

---

## Критика неполных требований (из ТЗ)

1. «Что показывать в модалке — решаете сами» → определены: описание, исполнитель, длительность, предшественники, вычисленные даты, критический признак, редактирование + Сохранить/Удалить.
2. «Массово редактировать план» требует движка расписания (что считать «переносом» при зависимости) → движок вынесен в отдельное ядро (scheduler), тестируемое без LLM.
3. Общая точка отсчёта плана (день 1) → «первый рабочий день проекта»; в расчёте индекс 0, пользователю день 1. Согласовано с FR-14.
4. Проды ссылок динамики (Render/Fly) — не гарантирует постоянной доступности · фри-тир → README обязательная локаль-инструкция.
5. В ТЗ нет требования авторизации/персиста -> сознательно не делаем в demo (roadmap).