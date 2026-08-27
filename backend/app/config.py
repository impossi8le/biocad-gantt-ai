"""Конфигурация приложения из окружения/.env (pydantic-settings)."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Gantt AI Plan"
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:8080"]
    # LLM (опционально; при отсутствии ключа работает детерминированный fallback)
    llm_api_key: str = ""
    llm_model: str = "anthropic/claude-3-5-haiku-latest"
    base_url: str = ""
    llm_timeout: float = 60.0
    llm_max_retries: int = 3
    # Сессии
    session_ttl: int = 1800
    max_sessions: int = 200
    # Лимиты
    max_upload_bytes: int = 20 * 1024 * 1024
    max_cells: int = 100_000


@lru_cache
def get_settings() -> Settings:
    return Settings()


def llm_enabled() -> bool:
    """Есть ли API-ключ — если нет, используем детерминированный intent-parser."""
    return bool(get_settings().llm_api_key)