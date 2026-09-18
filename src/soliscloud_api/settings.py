from functools import lru_cache

from dotenv import load_dotenv
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SolisCloud credentials, loaded from the environment or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    solis_id: SecretStr
    solis_secret: SecretStr
    solis_url: str = "https://www.soliscloud.com:13333/"
    # Measured against the live API: median response ~16s, tail to 29s, and roughly
    # one call in four exceeding 30s. The integration this replaces used a 10s timeout,
    # which is why it reported "No inverters found" on most polls.
    solis_timeout: float = 60.0


@lru_cache
def get_settings() -> Settings:
    """Load settings on first use.

    Deliberately lazy: building Settings at import time makes importing this package
    fail outright when no credentials are present, which breaks CI and Home Assistant.
    """
    load_dotenv()
    return Settings()
