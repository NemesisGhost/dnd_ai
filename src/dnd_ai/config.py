"""Application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Fields mirror .env.example — keep the two in sync.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai"
    test_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai_test"

    feature_ai_npc_dialogue: bool = False
    feature_discord_integration: bool = False
    feature_foundry_integration: bool = False


settings = Settings()
