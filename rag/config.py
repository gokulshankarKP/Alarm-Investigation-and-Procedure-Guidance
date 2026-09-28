"""RAG configuration, loaded from environment variables and the project ``.env`` file.

Secrets (the database password) are held as ``SecretStr`` so they never appear in
logs, reprs, or exception messages.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = PROJECT_ROOT / ".env"


class DatabaseSettings(BaseSettings):
    """PostgreSQL (pgvector) connection settings. Env vars: ``DB_*``."""

    model_config = SettingsConfigDict(env_prefix="DB_", env_file=_ENV_FILE, extra="ignore")

    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "postgres"
    password: SecretStr = SecretStr("")
    name: str = "agent_db"
    connect_timeout_s: int = 10

    def connection_kwargs(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password.get_secret_value(),
            "dbname": self.name,
            "connect_timeout": self.connect_timeout_s,
        }

    def safe_description(self) -> str:
        """Connection target for logging, without credentials."""
        return f"{self.user}@{self.host}:{self.port}/{self.name}"


class EmbeddingSettings(BaseSettings):
    """Embedding provider settings. Env vars: ``EMBEDDING_*`` (base URL falls back to ``OLLAMA_BASE_URL``)."""

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", env_file=_ENV_FILE, extra="ignore")

    base_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("EMBEDDING_BASE_URL", "OLLAMA_BASE_URL"),
    )
    # "ollama" for real embeddings; "hash" is a deterministic offline embedder for CI/tests.
    provider: Literal["ollama", "hash"] = "ollama"
    model: str = "nomic-embed-text"
    dimension: int = Field(default=768, gt=0)
    # nomic-embed-text is trained with task prefixes; set both to "" for models that are not.
    document_prefix: str = "search_document: "
    query_prefix: str = "search_query: "
    batch_size: int = Field(default=16, gt=0)
    timeout_s: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0)


class IngestionSettings(BaseSettings):
    """Corpus location and chunking parameters."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    document_path: Path = Field(
        default=PROJECT_ROOT / "rag" / "documents",
        validation_alias=AliasChoices("DOCUMENT_PATH", "RAG_DOCUMENT_PATH"),
    )
    chunk_max_chars: int = Field(default=1500, ge=200, validation_alias="RAG_CHUNK_MAX_CHARS")
    chunk_overlap_chars: int = Field(default=200, ge=0, validation_alias="RAG_CHUNK_OVERLAP_CHARS")

    @field_validator("document_path")
    @classmethod
    def _resolve_relative_to_project(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()


class RagSettings:
    """Aggregate of all RAG settings."""

    def __init__(
        self,
        database: DatabaseSettings | None = None,
        embedding: EmbeddingSettings | None = None,
        ingestion: IngestionSettings | None = None,
    ) -> None:
        self.database = database or DatabaseSettings()
        self.embedding = embedding or EmbeddingSettings()
        self.ingestion = ingestion or IngestionSettings()


@lru_cache(maxsize=1)
def get_settings() -> RagSettings:
    return RagSettings()
