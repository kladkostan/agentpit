from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    db_path: str = Field(default=":memory:", validation_alias="AGENTPIT_DB_PATH")
    sync_enabled: bool = Field(default=False, validation_alias="SYNC")
    sync_interval_seconds: int = Field(
        default=60 * 60, validation_alias="AGENTPIT_SYNC_INTERVAL_SECONDS"
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:5173"], validation_alias="AGENTPIT_CORS_ORIGINS"
    )
