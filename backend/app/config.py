"""
Application configuration.

Settings are loaded from environment variables (see .env.example).
Never hardcode secrets or environment-specific paths here.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # Upload constraints
    max_upload_size_mb: int = 50
    upload_dir: str = "./uploads"
    result_dir: str = "./results"

    # CORS
    frontend_url: str = "http://localhost:5173"

    # Retention / cleanup
    file_retention_minutes: int = 30

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def result_path(self) -> Path:
        path = Path(self.result_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
