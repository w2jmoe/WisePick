from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
# Load before Settings() so any import path (main, tests, reload) sees .env vars.
load_dotenv(_ENV_PATH)


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/wisepick"
    APP_TITLE: str = "WisePick Decision Router API"
    APP_VERSION: str = "0.1.5"
    # Optional YantrikDB cluster health (state-aware routing); empty = disabled
    YANTRIK_DB_URL: str = ""
    YANTRIK_DB_API_KEY: str = ""
    # Optional Langfuse routing telemetry (mcp.route_decision.v1); empty keys = disabled
    WISEPICK_LANGFUSE_PUBLIC_KEY: str = ""
    WISEPICK_LANGFUSE_SECRET_KEY: str = ""
    WISEPICK_LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    WISEPICK_LANGFUSE_OTEL: bool = False
    WISEPICK_LANGFUSE_ROUTER_NAME: str = "wisepick"
    WISEPICK_LANGFUSE_TIMEOUT_SECONDS: float = 5.0

    model_config = SettingsConfigDict(env_file=str(_ENV_PATH), extra="ignore")


settings = Settings()
