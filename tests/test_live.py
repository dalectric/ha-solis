"""Tests against the real SolisCloud API.

Skipped unless a .env with credentials is present. Run with:

    uv run pytest -m live

These are deliberately tolerant about values (the inverter's output changes minute to
minute) and strict about shape, scale and internal consistency.
"""

from pathlib import Path

import pytest

from soliscloud_api.client import SolisCloudClient
from soliscloud_api.models import InverterDetail

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not ENV_FILE.exists(), reason="no .env; live tests need real credentials"),
]


@pytest.fixture
async def client():
    async with SolisCloudClient() as c:
        yield c


class TestLiveApi:
    async def test_inverter_list_returns_records(self, client):
        listing = await client.inverter_list()
        assert listing.records, "account returned no inverters"
        assert all(inv.sn and inv.id for inv in listing.records)

    async def test_core_fields_are_populated(self, client):
        """Only fields every inverter reports.

        Not every typed field applies to every unit -- a single-phase, two-string
        inverter has no uPv3/uAc2 and the API omits them, which is why the models
        default to None rather than 0.0.
        """
        listing = await client.inverter_list()
        inv = listing.records[0]
        detail = await client.inverter_detail(inverter_id=inv.id, inverter_sn=inv.sn)

        assert isinstance(detail, InverterDetail)
        core = ["pac", "e_today", "e_total", "battery_capacity_soc", "data_timestamp"]
        unset = [name for name in core if getattr(detail, name) is None]
        assert not unset, f"core fields the API did not populate: {unset}"

    async def test_unmapped_fields_are_still_retained(self, client):
        listing = await client.inverter_list()
        inv = listing.records[0]
        detail = await client.inverter_detail(inverter_id=inv.id, inverter_sn=inv.sn)
        # A real response carries ~800 keys; everything beyond the typed set must survive.
        assert len(detail.model_extra or {}) > 100

    async def test_energy_counters_are_consistently_scaled(self, client):
        """Units differ per field (kWh vs MWh); after normalisation they must nest."""
        listing = await client.inverter_list()
        inv = listing.records[0]
        d = await client.inverter_detail(inverter_id=inv.id, inverter_sn=inv.sn)

        counters = {"e_today": d.e_today, "e_month": d.e_month, "e_year": d.e_year, "e_total": d.e_total}
        missing = [k for k, v in counters.items() if v is None]
        assert not missing, f"energy counters not reported: {missing}"
        assert d.e_today <= d.e_month <= d.e_year <= d.e_total, counters

    async def test_power_is_in_watts_not_kilowatts(self, client):
        """A domestic inverter reporting >100 kW means normalisation regressed."""
        listing = await client.inverter_list()
        inv = listing.records[0]
        d = await client.inverter_detail(inverter_id=inv.id, inverter_sn=inv.sn)
        assert d.pac is not None, "pac not reported"
        assert abs(d.pac) < 100_000, f"pac={d.pac} W looks like a scaling error"

    async def test_battery_soc_is_a_percentage(self, client):
        listing = await client.inverter_list()
        inv = listing.records[0]
        d = await client.inverter_detail(inverter_id=inv.id, inverter_sn=inv.sn)
        assert d.battery_capacity_soc is not None, "battery SOC not reported"
        assert 0 <= d.battery_capacity_soc <= 100
