"""Tests that load the built component against a real Home Assistant install.

Requires the optional `ha` dependency group:

    uv sync --group ha

Skipped otherwise, so the default suite still runs without Home Assistant.
"""

import subprocess
import sys
from pathlib import Path
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


def _coordinator(data: dict):
    from soliscloud.coordinator import SolisCoordinator

    coordinator = SolisCoordinator(MagicMock(), MagicMock(), MagicMock(), 5)
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
