# Архитектура и план реализации — AI-агент «Научный помощник» (BIOCAD)

## 1. Резюме решения

Локальное single-user fullstack-приложение на Docker Compose из 4 контейнеров (db, qdrant, backend, frontend+nginx), где RAG-конвейер построен на прямых вызовах LiteLLM + qdrant-client с тонким слоем LangGraph, а не на тяжёлом LangChain. PDF индексируются in-process асинхронными фоновыми задачами (парсинг pypdf, чанкинг, эмбеддинги в Qdrant), статусы и метаданные в PostgreSQL. OpenAI text-embedding-3-small (dim=1536) основной эмбеддер, стриминг через SSE с отдельным событием sources, сессии в PG с X-User-Id. UI строго по DESIGN.md (монохром shadcn/ui, Geist, радиусы 18/24, Tailwind v4).

## 2. Выбор стека (версии из §8 REQUIREMENTS.md)

### Backend — Python 3.12.14
Python 3.12.14; FastAPI 0.141.1; Uvicorn 0.52.4; Pydantic 2.13.4; SQLAlchemy 2.0.52; asyncpg 0.31.0; Alembic 1.19.1; LiteLLM 1.98.0; langchain-text-splitters 1.1.2; qdrant-client 1.19.0; sentence-transformers 5.1.x (+transformers 4.x); pypdf 6.16.2; pdfplumber 0.11.10; pytest 9.1.1; pytest-asyncio 1.4.0; httpx 0.28.1; python-multipart 0.0.32.

### Frontend — Node 24 LTS
React 19.2.8; TypeScript ~5.6.x; Vite 8.2.2 + @vitejs/plugin-react 6.1.0; react-router-dom 7.18.2; Tailwind CSS 4.3.3; shadcn 4.19.0; lucide-react 1.34.0; geist 1.7.2; pdfjs-dist (последняя стабильная); axios 1.20.0.

### Инфраструктура
postgres:16.15-alpine; qdrant/qdrant:v1.19.0; python:3.12-slim; node:24-alpine (build-stage); nginx:1.27-alpine (статика + proxy /api, SSE-буферизация отключена).

Ключевые решения: 1) прямые LiteLLM + qdrant-client вместо LangChain-цепочек (R-3); 2) Python 3.12 вместо 3.10 (EOL, §8.4); 3) Tailwind v4 под DESIGN.md (@theme, без tailwind.config.js); 4) Qdrant вместо pgvector/Chroma/Weaviate: встроенный фильтр по payload для подмножества статей, поддержка 1536-мерных векторов, HNSW + score_threshold; pgvector перегружал бы PG, Chroma слаб в фильтрах, Weaviate избыточен.

## 3. Решения по открытым вопросам §9

1. Эмбеддинги: OpenAI text-embedding-3-small (dim=1536) основной; локальный sentence-transformers 5.1.x optional fallback (EMBEDDINGS_PROVIDER=openai|local, torch отдельным слоем Dockerfile).
2. Фоновые задачи: in-process asyncio (BackgroundTasks + Semaphore(2)). Redis/воркер не нужны single-user.
3. LangGraph: минимальный граф retrieve→generate (2 узла), без сложного StateGraph.
4. Сессии: только PostgreSQL.
5. Multi-user хук: X-User-Id header, user_id в таблицах, без аутентификации.
6. Sources: отдельное SSE-событие sources после done.
7. OCR: вне MVP, статус failed с сообщением для скан-PDF.
8. UI: только RU, PDF могут быть EN.
9. Превью PDF: pdf.js (pdfjs-dist) на frontend, без poppler.
10. Миграции: Alembic auto-migrate при старте (alembic upgrade head в entrypoint).
11. top-terms: key_terms из саммари primary, fallback online TF-IDF по чанкам.
12. Rate limiting: не требуется (single-user).

## 4. Структура репозитория

```
BIOCAD AI TestWork/
├── docs/ (REQUIREMENTS.md, ARCHITECTURE_PLAN.md, DESIGN.md)
├── samples/ (FR-41, 3-5 open-access PDF)
├── backend/
│   ├── Dockerfile, requirements.txt, pyproject.toml, alembic.ini
│   ├── alembic/ (env.py, versions/)
│   ├── app/
│   │   ├── main.py, core/ (config, logging), db/ (base, session)
│   │   ├── models.py, schemas.py
│   │   ├── repositories/ (articles, chat, analytics, summary)
│   │   ├── services/ (pdf, chunker, embedding, qdrant, indexing, llm, rag, summary)
│   │   ├── api/ (deps, routes/ articles, chat, summary, analytics, health)
│   │   └── utils/error_handlers.py
│   ├── tests/ (conftest, ingestion, rag, summary, analytics, health)
│   └── data/ (mount ./data/uploads)
├── frontend/
│   ├── Dockerfile, package.json, tsconfig.json, vite.config.ts, index.html
│   └── src/
│       ├── main.tsx, App.tsx, routes/ (Chat, Library, Summary, Analytics)
│       ├── components/ (ui/ shadcn, layout/AppShell, chat/, library/, summary/, analytics/, shared/)
│       ├── lib/ (api, sse, pdfPreview), hooks/ (useSSE, useCitations, useAnalytics)
│       ├── styles/globals.css (@theme из DESIGN.md), types.ts
├── nginx/nginx.conf
├── docker-compose.yml, .env.example, .gitattributes, README.md
```

## 5. Схема БД (PostgreSQL)

Все таблицы имеют user_id (TEXT NOT NULL, default 'local') - хук multi-user. UUID PK.

articles: id, user_id, sha256 CHAR(64) UNIQUE(user_id,sha256), filename, stored_path, status ('uploaded/parsing/chunking/embedding/indexed/failed'), title nullable, authors TEXT[] nullable, year SMALLINT nullable, page_count INT nullable, file_size BIGINT, token_count INT nullable, uploaded_at, indexed_at, created_at, updated_at. Индексы: sha, status, uploaded_at, user_id.

chunks (метаданные; векторы в Qdrant, vector_id == chunks.id): id UUID PK, article_id FK->articles ON DELETE CASCADE, chunk_idx INT, page_start, page_end, text TEXT, token_count INT, vector_id TEXT. Индексы: UNIQUE(article_id, chunk_idx), idx_article_id.

summaries: id, article_id FK CASCADE, objective, methods, results, conclusions TEXT, key_terms TEXT[], generated_at, fresh BOOLEAN.

chat_sessions: id, user_id, title, created_at, updated_at.

chat_messages: id, session_id FK CASCADE, role CHECK in ('user','assistant'), content TEXT, status default 'complete', created_at.

chat_message_sources: id, message_id FK CASCADE, article_id FK, chunk_id FK, page INT, snippet TEXT, score REAL.

analytics - нет таблицы, прямые SQL-агрегации (FR-22..25). pg_trgm GIN-индекс на articles.title для поиска (FR-8).

## 6. Схема Qdrant

Коллекция articles_chunks; vectors size=1536 distance=Cosine; payload {article_id, page, chunk_idx}; vector_id UUID == chunks.id в PG. Создание на startup. Retrieval: qdrant.search(embedding, filter=FieldCondition('article_id', MatchAny(ids)), limit=top_k, score_threshold 0.3). Delete по фильтру article_id.

## 7. API-контракты

Все под /api. Заголовок X-User-Id (default 'local').

POST /api/articles/upload (multipart files[] 1-10 PDF) -> [{article_id, filename, status, existing?}] | 400 не-PDF, 413 >50MB, 409 dup.
GET /api/articles (q?, status?, from?, to?) -> список статей.
GET /api/articles/{id} -> статья | 404.
DELETE /api/articles/{id} -> 204 (каскад Qdrant+PG) | 404.
GET /api/articles/{id}/summary -> {objective, methods, results, conclusions, key_terms[], generated_at, fresh} | 404, 409 (не indexed).
POST /api/articles/{id}/summary/regenerate -> summary | 503.
POST /api/chat/sessions {title?} -> {session_id}.
GET /api/chat/sessions -> list.
POST /api/chat/stream {question, session_id?, article_ids?, top_k?=6} -> SSE | 400 пустая коллекция, 503.
GET /api/analytics/overview -> {articles_total, articles_indexed, articles_failed, chunks_total, total_bytes, avg_pages}.
GET /api/analytics/timeline?days=30 -> [{date, uploads_count}].
GET /api/analytics/top-terms?limit=10 -> [{term, frequency}].
GET /api/analytics/by-year -> [{year, count}].
GET /api/healthz -> {status, db, qdrant, llm, version} | 503.

SSE-формат (POST /api/chat/stream):
event: meta      data: {"message_id":"...","session_id":"..."}
event: token     data: {"text":"..."}
event: done      data: {"role":"assistant","message_id":"..."}
event: sources   data: {"sources":[{"chunk_id","article_id","title","page","snippet","score"}]}
event: error     data: {"code":"LLM_UNAVAILABLE","message":"..."}

SSE-заголовки: text/event-stream, Cache-Control: no-cache, X-Accel-Buffering: no. sources - отдельное событие ПОСЛЕ done.

## 8. Архитектурная ASCII-диаграмма

```
                       ┌──────────────────────────────┐
  Browser (localhost)  │  React 19 + shadcn/ui + Tailwind v4
                       └──────────────┬───────────────┘
                              HTTP /api · SSE /api/chat/stream
                                     ▼
                 ┌───────────────────────────────┐
                 │  nginx:1.27-alpine            │
                 │  static / -> dist; proxy /api │
                 │  SSE: proxy_buffering off     │
                 └──────────────┬────────────────┘
                                │
                 ┌──────────────▼───────────────┐   ┌──────────────────────┐
                 │  fastapi:8000 (python:3.12)  │   │  PostgreSQL 16       │
                 │  routes -> services          │◄──┤  articles, chunks,   │
                 │  Chat/Summary/Analytics/     │   │  summaries, sessions,│
                 │  Upload (SSE)                │   │  messages, sources   │
                 │  ─────────────────────────   │   └──────────────────────┘
                 │  asyncio background tasks    │
                 │  (indexing: pypdf -> chunk ->│
                 │   embed -> Qdrant + PG)      │
                 └──────────────┬───────────────┘
                                │ qdrant-client
                 ┌──────────────▼───────────────┐
                 │  Qdrant v1.19                │  collection: articles_chunks
                 │  vectors 1536 · Cosine       │  payload: article_id,page,chunk_idx
                 └──────────────────────────────┘
```

## 9. Пошаговый план реализации

Этап A - Каркас и БД: .gitignore, .env.example, docker-compose.yml, backend config/db/models, alembic init + auto-migrate, /api/healthz.
Этап B - Ingestion и эмбеддинги: pdf_service, chunker, embedding_service, qdrant_service, indexing_service, routes/articles (upload/GET/DELETE, duplicate 409).
Этап C - RAG/Чат: llm_service, rag_service (LangGraph retrieve->generate -> SSE stream), api/routes/chat, repositories/chat, интеграционный тест.
Этап D - Summary + Analytics: summary_service, analytics_service, routes, покрытие аналитики.
Этап E - Frontend, дизайн-система: Vite+shadcn+tailwind v4+geist scaffold; globals.css @theme (FR-31); UI-компоненты; AppShell; Library (DnD, status-badge, duplicate); useSSE/useCitations/api; ChatPage (citations [n], SourcesPanel, copy); SummaryPage; AnalyticsPage (4 виджета, prefill->chat); pdfPreview.
Этап F - Nginx + Docker + SSE: nginx.conf (proxy_buffering off), Dockerfile multi-stage, проверка на Windows.
Этап G - samples + docs: samples/ PDF, docs/ARCHITECTURE.md (<=500 слов, ASCII, обоснование Qdrant), README (quickstart, скриншоты, рекомендации Q&A, раздел Дизайн-система), .env.example финал.
Этап H - тесты и приёмка: прогон критериев §10, pytest >=60% (ingestion/rag/summary), >=5 интеграционных.

## 10. Дизайн-система в README (FR-39)

Раздел Дизайн-система в README: ссылка на docs/DESIGN.md; 8 токенов (canvas #f5f5f5, paper #ffffff, surface-alt #fafafa, ink #0a0a0a, ink-soft #171717, mid-gray #737373, hairline #e5e5e5, ember #e7000b); радиусы 18px интерактив / 24px карточки; красный #e7000b только error/destructive; шрифт Geist; трёхтоновые поверхности (canvas->sidebar->card); Tailwind v4 @theme в globals.css.

## 11. Риски и предположения

Риски: R-A дрейф эмбеддингов OpenAI/локальный -> единый EMBEDDINGS_PROVIDER, проверка размерности; R-B свежие версии (3.12, TS 5.6) -> проверить compose на Windows; R-C грязные метаданные bio-PDF -> pypdf->pdfplumber fallback; R-D SSE-буферизация прокси -> proxy_buffering off + X-Accel-Buffering: no; R-E стоимость OpenAI -> кэш саммари, лимит 6x500 токенов, локальный fallback.

Предположения: один пользователь без авторизации; файлы в named volume (без S3); OpenAI основной, Ollama fallback; OCR вне скоупа; UI на русском, PDF могут быть EN; до 100 статей, до 10 одновременных загрузок, ~1 RPS чата.

## Критика неполных требований

1. Нет отдельной таблицы метаданных чанков в SQL при векторах в Qdrant. Для chunks_total (FR-22), копирования отрывков в citations (US-11) и восстановления Qdrant после down -v нужна таблица chunks в PG. Заложена (метаданные + vector_id).
2. chunks_total и avg_pages не специфицированны как решаемые без метаданных - решается таблицей chunks; avg_pages нулабелен.
3. Дисбаланс default-OpenAI и критерия приемки нет-сети (§10 п.9). Без ключа все не работает. Митигация: README инструкция (Ollama fallback), осмысленные сообщения.
4. Порядок чтения двухколоночных PDF не специфицирован (R-2). pypdf default + pdfplumber fallback, README предупреждает.
