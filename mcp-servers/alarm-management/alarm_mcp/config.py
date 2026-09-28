from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class McpServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Upstream Alarm Management API (credential stays inside the MCP server boundary).
    alarm_api_base_url: str = Field(default="http://127.0.0.1:8000", validation_alias="ALARM_API_BASE_URL")
    alarm_api_token: SecretStr = Field(default=SecretStr("demo-token"), validation_alias="ALARM_API_TOKEN")
    alarm_api_timeout_s: float = Field(default=10.0, gt=0, validation_alias="ALARM_API_TIMEOUT_S")
    alarm_api_max_retries: int = Field(default=2, ge=0, le=5, validation_alias="ALARM_API_MAX_RETRIES")
    alarm_api_backoff_s: float = Field(default=0.5, ge=0, validation_alias="ALARM_API_BACKOFF_S")

    # MCP server itself.
    host: str = Field(default="127.0.0.1", validation_alias="MCP_HOST")
    port: int = Field(default=9000, validation_alias="MCP_PORT")
    # Bearer token MCP clients must present. Empty disables auth (local stdio use only).
    auth_token: SecretStr = Field(default=SecretStr("mcp-demo-token"), validation_alias="MCP_AUTH_TOKEN")
    allowed_hosts: str = Field(default="127.0.0.1:*,localhost:*,alarm-mcp:*", validation_alias="MCP_ALLOWED_HOSTS")
    max_pages: int = Field(default=5, ge=1, le=20, validation_alias="MCP_MAX_PAGES")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
