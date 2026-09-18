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


# --- Sign convention (Zaehlpfeilsystem) -------------------------------------
#
# https://de.wikipedia.org/wiki/Zaehlpfeil
#
#   Verbraucherzaehlpfeilsystem (VZS): a positive value means the component draws
#   power  -- "nimmt der Zweipol die elektrische Leistung p auf".
#   Erzeugerzaehlpfeilsystem   (EZS): a positive value means the component delivers
#   power  -- "gibt der Zweipol die elektrische Leistung p ab".
#
# The two differ only by sign: p' = -p.
#
# SolisCloud itself is not consistent. Measured on a live inverter: pac=+1.369 kW
# while generating, psum=+1.156 kW while exporting and batteryPower=-0.037 kW while
# charging are all EZS, but familyLoadPower=+0.19 kW while consuming is VZS. This
# integration normalises everything to one system and lets the user pick which.
CONF_SIGN_CONVENTION = "sign_convention"

SIGN_CONVENTION_CONSUMER = "consumer"
SIGN_CONVENTION_GENERATOR = "generator"
SIGN_CONVENTIONS = [SIGN_CONVENTION_GENERATOR, SIGN_CONVENTION_CONSUMER]

# EZS by default: it matches the API's native sign for PV, grid and battery, so the
# out-of-the-box values are the ones a solar owner expects (generating, exporting and
# discharging all positive).
DEFAULT_SIGN_CONVENTION = SIGN_CONVENTION_GENERATOR
