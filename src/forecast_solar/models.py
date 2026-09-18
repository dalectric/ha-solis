from pydantic import BaseModel, ConfigDict, Field


class PVArray(BaseModel):
    """A single PV array (group of panels with same orientation)."""

    name: str
    decline: int
    azimuth: int
    kwp: float
    modules: int

    @property
    def nominal_capacity(self) -> float:
        return self.modules * self.kwp


class PVSite(BaseModel):
    """Site location with one or more PV arrays."""

    latitude: float
    longitude: float
    arrays: list[PVArray]


class ForecastResult(BaseModel):
    """Parsed forecast.solar API response for a single array."""

    model_config = ConfigDict(extra="allow")

    array_name: str
    watts: dict[str, float] = Field(default_factory=dict)
    watt_hours_period: dict[str, float] = Field(default_factory=dict)
    watt_hours: dict[str, float] = Field(default_factory=dict)
    watt_hours_day: dict[str, float] = Field(default_factory=dict)
