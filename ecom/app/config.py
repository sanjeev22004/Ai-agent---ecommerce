import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory paths
APP_DIR = Path(__file__).resolve().parent
ECOM_ROOT = APP_DIR.parent
DATA_DIR = ECOM_ROOT / "data"
POLICIES_DIR = DATA_DIR / "policies"
STATIC_DIR = APP_DIR / "static"

# Pre-populate os.environ from .env so third-party SDKs (Langfuse, OpenAI) read them at module load time
env_file_path = ECOM_ROOT / ".env"
if env_file_path.exists():
    load_dotenv(env_file_path, override=True)


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:Hrhk%404321@127.0.0.1:5432/ecom"

    # JWT Authentication
    JWT_SECRET: str = "ecom-super-secret-jwt-key-2026-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480

    # LLM Settings
    LLM_PROVIDER: str = "groq"  # "groq" or "ollama"
    LLM_MODEL: str = "openai/gpt-oss-120b"
    LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_API_KEY: str = "your_groq_api_key_here_placeholder_for_local_env_config0"

    # Embedding Model
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    # System parameters
    MAX_ITERATIONS: int = 5
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50

    # Langfuse Observability
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"

    model_config = SettingsConfigDict(
        env_file=str(ECOM_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.DATABASE_URL.lower()

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL.lower()


settings = Settings()

# Ensure Langfuse SDK environment variables are cleanly synchronized to os.environ
if settings.LANGFUSE_PUBLIC_KEY:
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY.strip("\"'")
if settings.LANGFUSE_SECRET_KEY:
    os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY.strip("\"'")
if settings.LANGFUSE_BASE_URL:
    clean_host = settings.LANGFUSE_BASE_URL.strip("\"'")
    os.environ["LANGFUSE_BASE_URL"] = clean_host
    os.environ["LANGFUSE_HOST"] = clean_host
