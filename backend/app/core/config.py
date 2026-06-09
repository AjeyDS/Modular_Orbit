"""Runtime configuration for Modular Orbit."""

from functools import lru_cache
from typing import Literal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "modular-orbit"
    environment: str = "local"
    database_url: str = "postgresql://orbit:orbit@localhost:5432/modular_orbit"
    gemini_api_key: str = ""
    llm_mode: Literal["auto", "real", "mock", "off"] = "auto"
    gemini_chat_model: str = "gemini-2.5-flash-lite"
    gemini_json_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "models/gemini-embedding-001"
    embedding_dimension: int = 3072
    user_model_dir: Path = Path("../user_model")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
