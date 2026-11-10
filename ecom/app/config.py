from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory paths
APP_DIR = Path(__file__).resolve().parent
ECOM_ROOT = APP_DIR.parent
DATA_DIR = ECOM_ROOT / "data"
POLICIES_DIR = DATA_DIR / "policies"
STATIC_DIR = APP_DIR / "static"


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ecom"

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
