"""Tests that load the built component against a real Home Assistant install.

Requires the optional `ha` dependency group:

    uv sync --group ha

Skipped otherwise, so the default suite still runs without Home Assistant.
"""

import subprocess
import sys
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant", reason="install with: uv sync --group ha")

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


@pytest.fixture(scope="module", autouse=True)
def built_component():
    """Build dist/soliscloud and make it importable, as Home Assistant would see it."""
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_ha.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    sys.path.insert(0, str(DIST))
    from homeassistant.helpers import frame

    frame.async_setup(MagicMock())
    yield
    sys.path.remove(str(DIST))


def _detail(serial: str, pac_kw: float):
    from soliscloud.soliscloud_api.models import InverterDetail

    return InverterDetail.model_validate(
        {"id": f"id-{serial}", "sn": serial, "stationId": "st-1", "state": 1, "pac": pac_kw, "pacStr": "kW"}
    )


def _coordinator(data: dict, convention: str | None = None):
    from soliscloud.const import DEFAULT_SIGN_CONVENTION
    from soliscloud.coordinator import SolisCoordinator

    coordinator = SolisCoordinator(MagicMock(), MagicMock(), MagicMock(), 5, convention or DEFAULT_SIGN_CONVENTION)
    coordinator.data = data
    return coordinator


class TestComponentLoads:
    def test_every_module_imports(self):
        """Catches vendoring mistakes: the bundled client must not rely on the
        standalone package being installed, because on a HA box it is not."""
        for module in (
            "soliscloud",
            "soliscloud.const",
            "soliscloud.coordinator",
            "soliscloud.config_flow",
            "soliscloud.sensor",
        ):
            __import__(module)

    def test_bundled_client_uses_relative_imports_only(self):
        """A single absolute `soliscloud_api` import would break on a real HA box."""
        offenders = [
            f"{path.relative_to(DIST)}:{i}"
            for path in (DIST / "soliscloud" / "soliscloud_api").glob("*.py")
            for i, line in enumerate(path.read_text().splitlines(), 1)
            if line.startswith(("import soliscloud_api", "from soliscloud_api"))
        ]
        assert not offenders, f"absolute self-imports in the vendored client: {offenders}"


class TestTranslations:
    def test_build_generates_translations_from_strings(self):
        """HA reads translations/<lang>.json for custom integrations, not strings.json."""
        import json

        component = DIST / "soliscloud"
        strings = json.loads((component / "strings.json").read_text())
        english = json.loads((component / "translations" / "en.json").read_text())
        assert english == strings

    def test_every_config_flow_error_key_is_translated(self):
        """Checked against the file HA actually loads."""
        import ast
        import json

        english = json.loads((DIST / "soliscloud" / "translations" / "en.json").read_text())
        defined = set(english["config"]["error"])

        tree = ast.parse((DIST / "soliscloud" / "config_flow.py").read_text())
        returned = {
            node.value.elts[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Return)
            and isinstance(node.value, ast.Tuple)
            and node.value.elts
            and isinstance(node.value.elts[0], ast.Constant)
            and isinstance(node.value.elts[0].value, str)
        }
        assert returned <= defined, f"untranslated error keys: {sorted(returned - defined)}"


class TestMultipleInverters:
    def test_each_inverter_becomes_its_own_device(self):
        from soliscloud.sensor import SENSORS, SolisSensor

        serials = ["SN-AAA", "SN-BBB", "SN-CCC"]
        coordinator = _coordinator({sn: _detail(sn, 1.0) for sn in serials})
        entities = [SolisSensor(coordinator, sn, d) for sn in coordinator.data for d in SENSORS]

        devices = {next(iter(e.device_info["identifiers"])) for e in entities}
        assert devices == {("soliscloud", sn) for sn in serials}
        assert len(entities) == len(serials) * len(SENSORS)

    def test_unique_ids_do_not_collide_across_inverters(self):
        from soliscloud.sensor import SENSORS, SolisSensor

        coordinator = _coordinator({sn: _detail(sn, 1.0) for sn in ("SN-AAA", "SN-BBB")})
        ids = [SolisSensor(coordinator, sn, d).unique_id for sn in coordinator.data for d in SENSORS]
        assert len(ids) == len(set(ids))

    def test_values_are_read_per_inverter(self):
        from soliscloud.sensor import SENSORS, SolisSensor

        coordinator = _coordinator({"SN-AAA": _detail("SN-AAA", 1.2), "SN-BBB": _detail("SN-BBB", 3.4)})
        pac = next(d for d in SENSORS if d.key == "pac")
        values = {sn: SolisSensor(coordinator, sn, pac).native_value for sn in coordinator.data}
        assert values == {"SN-AAA": 1200.0, "SN-BBB": 3400.0}

    def test_missing_inverter_marks_entity_unavailable(self):
        from soliscloud.sensor import SENSORS, SolisSensor

        coordinator = _coordinator({"SN-AAA": _detail("SN-AAA", 1.0)})
        entity = SolisSensor(coordinator, "SN-GONE", SENSORS[0])
        assert entity.native_value is None


class TestSignConvention:
    """Zaehlpfeilsystem handling -- https://de.wikipedia.org/wiki/Zaehlpfeil

    Figures are from a real inverterDetail payload: pac=1.369 kW while generating,
    psum=1.156 kW while exporting, batteryPower=-0.037 kW while charging and
    familyLoadPower=0.19 kW while consuming. Note SolisCloud signs the load the
    opposite way round to everything else, which is what this normalises.
    """

    RAW: ClassVar[dict] = {
        "id": "1",
        "sn": "SN1",
        "stationId": "S",
        "state": 1,
        "pac": 1.369,
        "pacStr": "kW",
        "psum": 1.156,
        "psumStr": "kW",
        "batteryPower": -0.037,
        "batteryPowerStr": "kW",
        "familyLoadPower": 0.19,
        "familyLoadPowerStr": "kW",
        "eToday": 10.3,
        "eTodayStr": "kWh",
        "gridPurchasedTodayEnergy": 3.03,
        "gridPurchasedTodayEnergyStr": "kWh",
    }

    def _values(self, convention: str) -> dict:
        from soliscloud.sensor import SENSORS, SolisSensor
        from soliscloud.soliscloud_api.models import InverterDetail

        coordinator = _coordinator({"SN1": InverterDetail.model_validate(self.RAW)}, convention)
        return {
            d.key: SolisSensor(coordinator, "SN1", d).native_value
            for d in SENSORS
            if d.key in {"pac", "p_sum", "battery_power", "family_load_power", "e_today", "grid_purchased_today_energy"}
        }

    def test_generator_system_positive_means_delivered(self):
        from soliscloud.const import SIGN_CONVENTION_GENERATOR

        v = self._values(SIGN_CONVENTION_GENERATOR)
        assert v["pac"] == 1369.0, "PV generating must be positive"
        assert v["p_sum"] == 1156.0, "exporting must be positive"
        assert v["battery_power"] == -37.0, "charging must be negative"
        assert v["family_load_power"] == -190.0, "consuming must be negative"

    def test_consumer_system_positive_means_consumed(self):
        from soliscloud.const import SIGN_CONVENTION_CONSUMER

        v = self._values(SIGN_CONVENTION_CONSUMER)
        assert v["pac"] == -1369.0, "PV only delivers, so it is negative in VZS"
        assert v["p_sum"] == -1156.0, "exporting must be negative"
        assert v["battery_power"] == 37.0, "charging must be positive"
        assert v["family_load_power"] == 190.0, "consuming must be positive"

    def test_the_two_systems_are_exact_negations(self):
        """p' = -p, per the Zaehlpfeil definition."""
        from soliscloud.const import SIGN_CONVENTION_CONSUMER, SIGN_CONVENTION_GENERATOR

        ezs = self._values(SIGN_CONVENTION_GENERATOR)
        vzs = self._values(SIGN_CONVENTION_CONSUMER)
        for key in ("pac", "p_sum", "battery_power", "family_load_power"):
            assert vzs[key] == -ezs[key], key

    def test_energy_counters_stay_positive_in_both_systems(self):
        """One-way meters, not signed quantities; flipping breaks total_increasing."""
        from soliscloud.const import SIGN_CONVENTION_CONSUMER, SIGN_CONVENTION_GENERATOR

        for convention in (SIGN_CONVENTION_GENERATOR, SIGN_CONVENTION_CONSUMER):
            v = self._values(convention)
            assert v["e_today"] == 10.3
            assert v["grid_purchased_today_energy"] == 3.03

    def test_unsigned_sensors_are_never_flipped(self):
        from soliscloud.const import SIGN_CONVENTION_CONSUMER
        from soliscloud.sensor import SENSORS, SolisSensor
        from soliscloud.soliscloud_api.models import InverterDetail

        raw = self.RAW | {"batteryCapacitySoc": 96.0, "inverterTemperature": 43.1, "uAc1": "230.5"}
        coordinator = _coordinator({"SN1": InverterDetail.model_validate(raw)}, SIGN_CONVENTION_CONSUMER)
        by_key = {d.key: d for d in SENSORS}
        for key, expected in (("battery_capacity_soc", 96.0), ("inverter_temperature", 43.1), ("u_ac1", 230.5)):
            assert SolisSensor(coordinator, "SN1", by_key[key]).native_value == expected, key

    def test_every_power_sensor_declares_a_flow(self):
        """A power sensor left at Flow.NONE would silently ignore the convention."""
        from homeassistant.components.sensor import SensorDeviceClass
        from soliscloud.sensor import SENSORS, Flow

        missing = [d.key for d in SENSORS if d.device_class is SensorDeviceClass.POWER and d.flow is Flow.NONE]
        assert not missing, f"power sensors with no flow classification: {missing}"
