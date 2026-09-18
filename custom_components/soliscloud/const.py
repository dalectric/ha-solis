"""Constants for the SolisCloud integration."""

DOMAIN = "soliscloud"

CONF_KEY_ID = "key_id"
CONF_KEY_SECRET = "key_secret"
CONF_URL = "url"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"

DEFAULT_URL = "https://www.soliscloud.com:13333/"

# The API is slow: measured median ~16s, tail beyond 30s, with roughly one call in four
# exceeding 30s. A generous per-request timeout plus retries beats a short timeout.
DEFAULT_TIMEOUT_SECONDS = 60.0

# The config-flow dialog must not appear frozen. One attempt, shorter timeout: with a
# ~16s median the common case still succeeds, and a bad URL fails in 30s rather than
# the ~184s that 3 retries at 60s would take.
# Measured: ~1 call in 4 exceeds 30s, so a single 30s attempt fails roughly a quarter
# of the time. Two attempts at 45s is ~91s worst case -- long for a dialog, but far
# better than telling the user it cannot connect when the API was merely slow.
CONFIG_FLOW_TIMEOUT_SECONDS = 45.0
CONFIG_FLOW_MAX_ATTEMPTS = 2

# Each poll costs one inverterList call plus one inverterDetail per inverter, and the
# API allows three calls per five seconds. Five minutes leaves ample headroom.
DEFAULT_SCAN_INTERVAL_MINUTES = 5
MIN_SCAN_INTERVAL_MINUTES = 1


# --- Sign convention --------------------------------------------------------
#
# https://en.wikipedia.org/wiki/Passive_sign_convention
#
#   Generator convention (active sign convention): power flowing OUT of the component
#   is positive -- "the power variable represents power produced".
#   Load convention (passive sign convention): power flowing INTO the component is
#   positive -- "electric power flowing out of the circuit into an electrical
#   component as positive".
#
# The two are opposites: p' = -p.
#
# SolisCloud itself is not consistent. Measured on a live inverter: pac=+1.369 kW
# while generating, psum=+1.156 kW while exporting and batteryPower=-0.037 kW while
# charging all follow the generator convention, but familyLoadPower=+0.19 kW while
# consuming follows the load convention. This integration normalises everything onto
# one convention and lets the user pick which.
CONF_SIGN_CONVENTION = "sign_convention"

SIGN_CONVENTION_GENERATOR = "generator"
SIGN_CONVENTION_LOAD = "load"
SIGN_CONVENTIONS = [SIGN_CONVENTION_GENERATOR, SIGN_CONVENTION_LOAD]

# Renamed from "consumer" once the English reference was adopted; mapped on read so an
# entry saved by an earlier version keeps working.
_LEGACY_SIGN_CONVENTIONS = {"consumer": SIGN_CONVENTION_LOAD}

# Generator convention by default: it matches the API's native sign for PV, grid and
# battery, so out of the box generating, exporting and discharging are all positive.
# As the reference puts it, "No manufacturer sells a '-5 kilowatt generator.'"
DEFAULT_SIGN_CONVENTION = SIGN_CONVENTION_GENERATOR


def normalise_sign_convention(value: str | None) -> str:
    """Accept legacy values and fall back to the default for anything unknown."""
    if value is None:
        return DEFAULT_SIGN_CONVENTION
    value = _LEGACY_SIGN_CONVENTIONS.get(value, value)
    return value if value in SIGN_CONVENTIONS else DEFAULT_SIGN_CONVENTION
