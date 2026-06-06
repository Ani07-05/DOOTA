from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = ROOT_DIR / "doota.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    groq_api_key: str = ""
    scan_interval_hours: int = 6
    rss_poll_interval_hours: int = 1
    database_url: str = f"sqlite:///{DEFAULT_DB.as_posix()}"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    recent_circulars_limit: int = 10


settings = Settings()
