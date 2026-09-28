from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SimulatorSettings(BaseSettings):
    """Env vars: ``ALARM_API_*`` / ``ALARM_SIM_*``."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_token: SecretStr = Field(default=SecretStr("demo-token"), validation_alias="ALARM_API_TOKEN")
    # Seed data covers the 183 days ending at this instant. Fixed by default so the data,
    # the Postman collections (May-July 2026) and the automated tests are reproducible.
    anchor_time: datetime = Field(default=datetime(2026, 9, 30, tzinfo=UTC), validation_alias="ALARM_SIM_ANCHOR_TIME")
    seed: int = Field(default=42, validation_alias="ALARM_SIM_SEED")
    enable_admin: bool = Field(default=True, validation_alias="ALARM_SIM_ENABLE_ADMIN")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator("anchor_time", mode="before")
    @classmethod
    def _parse_anchor(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() == "now":
            return datetime.now(UTC).replace(second=0, microsecond=0)
        return value

    @field_validator("anchor_time")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)
