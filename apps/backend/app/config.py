from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "대화동행 API"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://frontier:frontier@localhost:5432/frontier"
    provider_mode: Literal["mock", "remote"] = "mock"
    ai_service_url: AnyHttpUrl = AnyHttpUrl("http://ai:8100")
    ai_service_timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    anthropic_api_key: str | None = None
    data_go_kr_service_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
