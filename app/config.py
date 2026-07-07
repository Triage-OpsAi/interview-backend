import os
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


RUNNING_ON_VERCEL = os.getenv("VERCEL") == "1"
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
LOCAL_STORAGE_DIR = Path(
    os.getenv("LOCAL_STORAGE_DIR")
    or ("/tmp/interview-backend-storage" if RUNNING_ON_VERCEL else BACKEND_DIR / "storage")
)
DEFAULT_DATABASE_URL = "sqlite:////tmp/interview_agent.db" if RUNNING_ON_VERCEL else "sqlite:///./interview_agent.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_secret: str = "change-me-in-production"
    database_url: str = DEFAULT_DATABASE_URL
    cors_origins: str = "*"
    frontend_base_url: str = "http://127.0.0.1:3000"

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o"
    openai_stt_model: str = "whisper-1"

    elevenlabs_api_key: str = ""
    elevenlabs_default_voice_id: str = Field(
        default="",
        validation_alias=AliasChoices("ELEVENLABS_DEFAULT_VOICE_ID", "ELEVENLABS_VOICE_ID"),
    )
    elevenlabs_model_id: str = "eleven_turbo_v2_5"

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_resumes_bucket: str = "resumes"
    supabase_storage_recordings_bucket: str = "recordings"
    supabase_storage_reports_bucket: str = "reports"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "interviews@example.com"
    smtp_use_tls: bool = True
    dev_expose_logged_otp: bool = False

    magic_link_expiry_hours: int = 72
    otp_expiry_minutes: int = 10
    candidate_session_expiry_hours: int = 6
    max_interview_questions: int = 10

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql://" + value.removeprefix("postgres://")
        return value


settings = Settings()
