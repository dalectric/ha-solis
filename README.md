# ha-solis

[![CI](https://github.com/dalectric/ha-solis/actions/workflows/ci.yml/badge.svg)](https://github.com/dalectric/ha-solis/actions/workflows/ci.yml)

SolisCloud API client and Home Assistant integration for photovoltaic, battery, load
and grid monitoring.

- `src/soliscloud_api/` — async API client. No Home Assistant imports, usable on its own.
- `custom_components/soliscloud/` — thin Home Assistant layer on top of it.

## Setup

Requires Python 3.14.2+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                  # runtime deps
uv sync --all-groups     # plus dev and test
cp .env.example .env     # then fill in your credentials
```

Solis issues the first three values when you request API access:

```env
SOLIS_ID=<key id>
SOLIS_SECRET=<key secret>
SOLIS_URL=https://www.soliscloud.com:13333/
SOLIS_TIMEOUT=60           # optional, seconds per request
```

`SOLIS_URL` must start with `https://`; any other scheme is rejected.

## CLI

```bash
uv run ha-solis                 # summary of each inverter
uv run ha-solis probe           # diagnose credentials, clock skew and signing
uv run ha-solis probe --hammer  # also exercise the rate limiter
uv run ha-solis dump            # write raw API responses to data/raw/
```

`probe` is the first thing to run when something is wrong. On failure it prints the HTTP
status, the API's own code and message, and the exact string that was signed.

## Library

```python
from soliscloud_api import SolisCloudClient

async with SolisCloudClient() as client:
    listing = await client.inverter_list()
    detail = await client.inverter_detail(inverter_sn=listing.records[0].sn)
    print(detail.pac, "W", detail.e_total, "kWh")
```

## Home Assistant

#### Via HACS (recommended)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dalectric&repository=ha-solis&category=integration)

Or add it by hand: HACS → ⋮ → **Custom repositories** → `https://github.com/dalectric/ha-solis`,
category **Integration**. Then download **SolisCloud** and restart Home Assistant.

HACS installs the archive attached to each release, which is built by CI from this
repo and already contains the API client. Updates arrive through HACS.

#### Manually

```bash
uv run python scripts/build_ha.py
cp -r dist/soliscloud <ha-config>/custom_components/
```

#### Then

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=soliscloud)

Restart Home Assistant, then add **SolisCloud** from Settings → Devices & Services and
enter the API URL, Key ID and Key Secret. The button above opens that dialog once the
integration is installed. Polls every 5 minutes by default (minimum 1), adjustable in
the integration's options.

The component bundles its own copy of `soliscloud_api`, built by `scripts/build_ha.py`,
so its only requirements are `pydantic`, `pydantic-settings` and `python-dotenv`.

Tested against Home Assistant **2026.10.4** (the version pinned in `uv.lock`).

### Multiple inverters

One config entry covers the whole account. Every inverter the API returns becomes its
own **device**, named `Solis <serial>`, with 53 sensors each. Entity IDs are namespaced
by serial.

- **Entities are created at setup.** An inverter added to the Solis account later
  appears after an integration reload.
- **Polling cost scales with inverter count.** Each poll is one `inverterList` plus one
  `inverterDetail` per inverter, at ~16s median per call. Three inverters take roughly a
  minute per poll; for more, raise the interval in options.

## Sign convention

The API's raw signs are not consistent across fields:

| Field | Raw positive means | Under the generator convention |
|---|---|---|
| `pac` (PV) | generating | used as is |
| `psum` (grid) | exporting | negated |
| `batteryPower` | charging | negated |
| `familyLoadPower` (house) | consuming | negated |

The integration normalises every signed power sensor onto one
[sign convention](https://en.wikipedia.org/wiki/Passive_sign_convention), selectable at
runtime via the **Sign convention** entity or in the integration's options:

| | Generator convention (default) | Load convention |
|---|---|---|
| also known as | active sign convention | passive sign convention |
| positive means | the component **supplies** the house | the component **draws** from the house |
| PV generating | `+` | `−` |
| Battery | `+` discharging, `−` charging | `+` charging, `−` discharging |
| Grid | `+` importing, `−` exporting | `+` exporting, `−` importing |
| House load | `−` | `+` |

Every component is treated as a supplier to the house: under the generator convention a
positive reading means "feeding the system" and a negative one "drawing from it". The
two conventions are exact negations (`p′ = −p`). Generator convention is the default.

The selector's attributes state what positive currently means for grid, battery and
PV, so the active convention is readable from a template or dashboard.

### Grid exchange

The API reports grid import and export as two separate one-way counters. **Grid
exchange** sensors carry the balance — export minus import — for today, this month,
this year and total, alongside `Grid exchange power` for the instantaneous figure.

- They follow the sign convention: positive is a net import under the generator
  convention, a net export under the load convention.
- They use `state_class: total`, not `total_increasing`, because a balance can fall.
- A balance is `unknown` unless both import and export are reported.

Cumulative **energy** counters are always positive under both conventions. They are
one-way meters (kWh imported, kWh exported), as the Energy dashboard requires for
`total_increasing` sensors.

### Display precision

| Period | Decimals |
|---|---|
| Today, month, year | 1 |
| Lifetime | 0 |

This is display only: Home Assistant keeps the full value for long-term statistics, and
precision can be overridden per entity in the UI.

## API behaviour and client handling

| API behaviour | Client handling |
|---|---|
| Median response ~16s, tail past 30s; about 1 call in 4 exceeds 30s | Default timeout 60s per request. |
| Transient HTTP 5xx and timeouts | Up to 3 attempts with exponential backoff and jitter. Auth errors are not retried. |
| Limit of 3 calls per 5 seconds per IP | Sliding-window limiter shared across all calls on a client. |
| Units differ between fields in one response — `eToday` in kWh, `eTotal` in MWh | Values normalised to W and kWh via their `<field>Str` companion. |
| `inverterDetail` returns ~812 keys | ~50 typed; the rest retained via `model_extra`. |
| Fields omitted rather than zeroed when not applicable | Numerics default to `None`, never `0.0`; Home Assistant shows `unknown`. |

Each failure cause raises its own exception — `SolisAuthError`, `SolisClockSkewError`,
`SolisRateLimitError`, `SolisAPIError`, `SolisTransportError` — so a wrong key is
distinguishable from an empty account.

## Development

```bash
uv sync --group ha        # optional: installs Home Assistant for integration tests
uv run pytest             # offline suite
uv run pytest -m live     # against the real API; needs .env (~5 min)
uv run ruff check .
uv run ruff format .
```

`tests/test_ha_integration.py` builds the component and loads it against a real Home
Assistant install. It is skipped unless the `ha` group is installed.

CI runs lint, the offline suite, the Home Assistant integration test and a gitleaks scan
of the full history on every push to `main` and every pull request.

### Secret scanning

Install the git hooks once per clone:

```bash
uv run pre-commit install
```

- **gitleaks** scans staged content for API keys, tokens and credentials. `.gitleaks.toml`
  extends the default rule set with a SolisCloud-specific rule for `SOLIS_ID` and
  `SOLIS_SECRET`.
- **`forbid-env-files`** rejects any staged `.env`, since `git add -f` bypasses
  `.gitignore`. `.env.example` is allowed.

To check every file rather than just staged changes:

```bash
uv run pre-commit run --all-files
```
