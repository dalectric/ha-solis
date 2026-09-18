"""Site configuration for forecast.solar, loaded from the environment.

Location and array geometry are personal data, so they live in .env rather than in
source. See .env.example for the variable names.
"""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import PVArray, PVSite


class ForecastSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORECAST_", env_file=".env", extra="ignore")

    latitude: float
    longitude: float
    # Supplied as a JSON list, e.g.
    # FORECAST_ARRAYS='[{"name":"South","decline":40,"azimuth":0,"kwp":0.445,"modules":12}]'
    arrays: list[PVArray] = Field(default_factory=list)


@lru_cache
def get_settings() -> ForecastSettings:
    """Load on first use, so importing this module never requires a .env."""
    load_dotenv()
    return ForecastSettings()


@lru_cache
def get_site() -> PVSite:
    settings = get_settings()
    return PVSite(latitude=settings.latitude, longitude=settings.longitude, arrays=settings.arrays)
