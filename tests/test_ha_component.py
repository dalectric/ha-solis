"""Checks on the Home Assistant component that do not require homeassistant installed.

sensor.py imports homeassistant, so it is parsed rather than imported.
"""

import ast
import json
from pathlib import Path

from soliscloud_api.models import InverterDetail

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "soliscloud"


def _sensor_keys() -> list[str]:
    """Every `key=` string passed to a SensorEntityDescription or helper in sensor.py."""
    tree = ast.parse((COMPONENT / "sensor.py").read_text())
    keys: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                keys.append(kw.value.value)
        func = node.func
        if (
            isinstance(func, ast.Name)
            and func.id in {"_power", "_energy", "_volts", "_amps"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            keys.append(node.args[0].value)
    return keys


class TestSensorTable:
    def test_every_sensor_key_exists_on_the_model(self):
        """A typo here would produce a permanently `unknown` entity, silently."""
        unknown = sorted(set(_sensor_keys()) - set(InverterDetail.model_fields))
        assert not unknown, f"sensor.py references fields InverterDetail does not have: {unknown}"

    def test_sensor_keys_are_unique(self):
        keys = _sensor_keys()
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        assert not duplicates, f"duplicate sensor keys: {duplicates}"

    def test_table_is_not_empty(self):
        assert len(_sensor_keys()) > 20


class TestManifest:
    def test_manifest_is_valid_json_with_required_keys(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        for key in ("domain", "name", "version", "documentation", "codeowners", "requirements"):
            assert key in manifest, f"manifest.json is missing {key!r}"
        assert manifest["domain"] == "soliscloud"
        assert manifest["config_flow"] is True

    def test_every_config_flow_error_has_a_string(self):
        """A missing entry renders as a raw key in the UI instead of a message."""
        strings = json.loads((COMPONENT / "strings.json").read_text())
        defined = set(strings["config"]["error"])

        tree = ast.parse((COMPONENT / "config_flow.py").read_text())
        returned = {
            node.value.elts[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Return)
            and isinstance(node.value, ast.Tuple)
            and node.value.elts
            and isinstance(node.value.elts[0], ast.Constant)
            and isinstance(node.value.elts[0].value, str)
        }
        assert returned <= defined, f"config_flow returns errors with no string: {sorted(returned - defined)}"


class TestHacs:
    """HACS installs the release archive, so its config must match the component."""

    @staticmethod
    def _hacs() -> dict:
        return json.loads((COMPONENT.parent.parent / "hacs.json").read_text())

    def test_hacs_json_is_valid_and_names_the_release_asset(self):
        hacs = self._hacs()
        assert hacs["name"]
        # zip_release requires filename; without it HACS falls back to the repo tree,
        # which does not contain the bundled client and would install a broken copy.
        if hacs.get("zip_release"):
            assert hacs.get("filename", "").endswith(".zip")

    def test_release_workflow_publishes_the_named_asset(self):
        workflow = (COMPONENT.parent.parent / ".github" / "workflows" / "release.yml").read_text()
        assert self._hacs()["filename"] in workflow, "hacs.json filename is not what the release workflow uploads"

    def test_manifest_domain_matches_the_component_directory(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        assert manifest["domain"] == COMPONENT.name
