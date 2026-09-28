"""
Application configuration.

Settings are loaded from environment variables (see .env.example).
Never hardcode secrets or environment-specific paths here.
"""
import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    port: int = Field(default=8000, validation_alias="PORT")

    # Upload constraints
    max_upload_size_mb: int = Field(default=50, validation_alias="MAX_UPLOAD_SIZE_MB")
    max_pages: int = Field(default=100, validation_alias="MAX_PAGES")
    max_processing_time_seconds: int = Field(default=300, validation_alias="MAX_PROCESSING_TIME")
    upload_dir: str = Field(default="./uploads", validation_alias="UPLOAD_DIR")
    result_dir: str = Field(default="./results", validation_alias="RESULT_DIR")

    # CORS & Allowed Origins
    frontend_url: str = Field(default="http://localhost:5173", validation_alias="FRONTEND_URL")
    allowed_origins: str | None = Field(default=None, validation_alias="ALLOWED_ORIGINS")

    # Retention / cleanup
    file_retention_minutes: int = Field(default=30, validation_alias="FILE_RETENTION_MINUTES")

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def result_path(self) -> Path:
        path = Path(self.result_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cors_origins(self) -> list[str]:
        """
        Parses FRONTEND_URL and ALLOWED_ORIGINS into a clean list of allowed CORS origins.
        Also permits local development origins when in development mode.
        """
        origins: set[str] = set()

        if self.frontend_url:
            for url in self.frontend_url.split(","):
                cleaned = url.strip().rstrip("/")
                if cleaned:
                    origins.add(cleaned)

        if self.allowed_origins:
            for url in self.allowed_origins.split(","):
                cleaned = url.strip().rstrip("/")
                if cleaned:
                    origins.add(cleaned)

        # In development mode, guarantee standard local origins
        if self.app_env.lower() in ("development", "dev", "local"):
            origins.add("http://localhost:5173")
            origins.add("http://127.0.0.1:5173")
            origins.add("http://localhost:3000")
            origins.add("http://127.0.0.1:3000")
            origins.add("http://localhost:4173")
            origins.add("http://127.0.0.1:4173")

        return sorted(list(origins)) if origins else ["http://localhost:5173"]


settings = Settings()
