from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/wisepick"
    APP_TITLE: str = "WisePick Decision Router API"
    APP_VERSION: str = "0.1.0"

    model_config = SettingsConfigDict(env_file=str(_ENV_PATH), extra="ignore")


settings = Settings()
