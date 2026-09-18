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
CONFIG_FLOW_TIMEOUT_SECONDS = 30.0
CONFIG_FLOW_MAX_ATTEMPTS = 1

# Each poll costs one inverterList call plus one inverterDetail per inverter, and the
# API allows three calls per five seconds. Five minutes leaves ample headroom.
DEFAULT_SCAN_INTERVAL_MINUTES = 5
MIN_SCAN_INTERVAL_MINUTES = 1
