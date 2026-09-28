from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag.config import _ENV_FILE


class CopilotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # MCP (the only path to the Alarm Management API).
    mcp_server_url: str = Field(default="http://127.0.0.1:9000/mcp", validation_alias="MCP_SERVER_URL")
    mcp_auth_token: SecretStr = Field(default=SecretStr("mcp-demo-token"), validation_alias="MCP_AUTH_TOKEN")
    mcp_tool_timeout_s: float = Field(default=45.0, gt=0, validation_alias="MCP_TOOL_TIMEOUT_S")

    # LLM (replaceable provider; "none" = deterministic composer only).
    llm_provider: Literal["ollama", "none"] = Field(default="ollama", validation_alias="LLM_PROVIDER")
    ollama_base_url: str = Field(default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen3:8b", validation_alias="OLLAMA_MODEL")
    llm_timeout_s: float = Field(default=600.0, gt=0, validation_alias="LLM_TIMEOUT_S")
    llm_temperature: float = Field(default=0.1, ge=0, le=1, validation_alias="LLM_TEMPERATURE")
    llm_num_ctx: int = Field(default=12288, ge=2048, validation_alias="LLM_NUM_CTX")
    llm_max_tokens: int = Field(default=900, ge=128, validation_alias="LLM_MAX_TOKENS")
    # hybrid: LLM only when the rule classifier is not decisive (fast on CPU); llm: always; rules: never.
    intent_mode: Literal["hybrid", "llm", "rules"] = Field(default="hybrid", validation_alias="COPILOT_INTENT_MODE")

    # Orchestration.
    reference_time: datetime | None = Field(default=None, validation_alias="COPILOT_REFERENCE_TIME")
    default_lookback_days: int = Field(default=90, ge=1, le=365, validation_alias="COPILOT_LOOKBACK_DAYS")
    max_priority_scoring: int = Field(default=6, ge=1, le=20, validation_alias="COPILOT_MAX_PRIORITY_SCORING")
    max_history_turns: int = Field(default=6, ge=0, le=20, validation_alias="COPILOT_MAX_HISTORY_TURNS")

    host: str = Field(default="127.0.0.1", validation_alias="BACKEND_HOST")
    port: int = Field(default=8080, validation_alias="BACKEND_PORT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator("reference_time", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if value in ("", "now", None) else value

    def now(self) -> datetime:
        if self.reference_time is None:
            return datetime.now(UTC).replace(microsecond=0)
        return self.reference_time if self.reference_time.tzinfo else self.reference_time.replace(tzinfo=UTC)
