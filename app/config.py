from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    serper_api_key: str = ""
    google_cse_api_key: str = ""
    google_cse_cx: str = ""
    youtube_api_key: str = ""

    request_timeout_seconds: float = 12.0
    llm_timeout_seconds: float = 40.0
    cache_ttl_seconds: int = 1800
    max_concurrent_searches: int = 4
    max_website_enrichments: int = 5
    port: int = 4000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
