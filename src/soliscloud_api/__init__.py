"""SolisCloud API client.

from . import SolisCloudClient

async with SolisCloudClient() as client:
    listing = await client.inverter_list()
    detail = await client.inverter_detail(inverter_sn=listing.records[0].sn)
"""

from .client import SolisCloudClient
from .errors import (
    SolisAPIError,
    SolisAuthError,
    SolisClockSkewError,
    SolisError,
    SolisRateLimitError,
    SolisTransportError,
)
from .models import (
    InverterDetail,
    InverterInfo,
    InverterListResponse,
    SolisResponse,
)
from .settings import Settings, get_settings

__all__ = [
    "InverterDetail",
    "InverterInfo",
    "InverterListResponse",
    "Settings",
    "SolisAPIError",
    "SolisAuthError",
    "SolisClockSkewError",
    "SolisCloudClient",
    "SolisError",
    "SolisRateLimitError",
    "SolisResponse",
    "SolisTransportError",
    "get_settings",
]
