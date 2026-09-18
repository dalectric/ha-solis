# ha-solis

[![CI](https://github.com/dalectric/ha-solis/actions/workflows/ci.yml/badge.svg)](https://github.com/dalectric/ha-solis/actions/workflows/ci.yml)

SolisCloud API client and Home Assistant integration for photovoltaic, battery, load
and grid monitoring.

- `src/soliscloud_api/` — async API client. No Home Assistant imports, usable on its own.
- `custom_components/soliscloud/` — thin Home Assistant layer on top of it.

## Setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                  # runtime deps
uv sync --all-groups     # plus dev and test
cp .env.example .env     # then fill in your credentials
```

Solis issues three values when you request API access:

```env
SOLIS_ID=<key id>
SOLIS_SECRET=<key secret>
SOLIS_URL=https://www.soliscloud.com:13333/
```


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
enter the API URL, Key ID and Key Secret. The button above jumps straight to that
dialog once the integration is installed. Polls every 5 minutes by default, adjustable
in the integration's options.

Verified against Home Assistant **2026.9.2**.

### Multiple inverters

One config entry covers the whole account. Every inverter the API returns becomes its
own **device**, named `Solis <serial>`, each carrying the full set of ~45 entities.
Entity IDs are namespaced by serial, so nothing collides.

Two things to know:

- **Entities are created at setup.** Adding an inverter to your Solis account later
  needs an integration reload before it appears.
- **Polling cost scales with inverter count.** Each poll is one `inverterList` plus one
  `inverterDetail` per inverter, and the API is slow (~16s median). Three inverters is
  roughly a minute per poll — comfortable at a 5 minute interval; ten would be tight, so
  raise the interval in options.

The build step vendors the client into the component because this repo has no published
package yet. Once it is on GitHub, that can become a single manifest entry:
`"requirements": ["ha-solis @ git+https://github.com/dalectric/ha-solis@main"]`.

## Sign convention

SolisCloud is not internally consistent about signs. Measured on a live inverter:
`pac=+1.369 kW` while generating, `psum=+1.156 kW` while exporting and
`batteryPower=-0.037 kW` while charging all follow the generator convention, but
`familyLoadPower=+0.19 kW` while consuming follows the load convention.

This integration normalises every signed power sensor onto one
[sign convention](https://en.wikipedia.org/wiki/Passive_sign_convention), selectable at
runtime via the **Sign convention** entity or in the integration's options:

| | Generator convention (default) | Load convention |
|---|---|---|
| also known as | active sign convention | passive sign convention |
| positive means | power **produced** | power **consumed** |
| PV generating | `+` | `−` |
| Grid | `+` exporting | `+` importing |
| Battery | `+` discharging | `+` charging |
| House load | `−` | `+` |

The two are exact negations (`p′ = −p`). Generator convention is the default because it
matches the API's native signs for PV, grid and battery — or as the reference puts it,
*"No manufacturer sells a '−5 kilowatt generator.'"*

### Grid exchange

The API reports grid import and export as two separate one-way counters, so neither
alone answers "am I ahead?". **Grid exchange** sensors carry the balance — export minus
import — for today, this month, this year and total, alongside `Grid exchange power`
for the instantaneous figure.

These are genuine signed quantities, so they follow the sign convention: positive is a
net export under the generator convention, a net import under the load convention. They
use `state_class: total` rather than `total_increasing`, because a balance legitimately
falls whenever more is drawn than delivered — `total_increasing` would make Home
Assistant read every dip as a meter reset.

A balance is only published when both sides are reported; netting a present value
against a missing one would quietly understate it, so the sensor stays `unknown`.

Cumulative **energy** counters are deliberately left positive under both. They are not
signed quantities but separate one-way meters (kWh imported, kWh exported), and Home
Assistant's Energy dashboard requires `total_increasing` sensors to stay positive and
monotonic.

The selector's attributes spell out what positive currently means for grid, battery and
PV, so the active convention is readable from a template or dashboard.

## What this handles that a naive client does not

Behaviour measured against the live API, not assumed:

| Observation | Consequence |
|---|---|
| Median response ~16s, tail past 30s, and roughly **1 call in 4 exceeds 30s** | Default timeout is 60s. A 10s timeout — as used by `fboundy/solis-sensor` — times out on most polls and reports it as "No inverters found". |
| Transient HTTP 502s | Up to 3 attempts with exponential backoff and jitter. Auth errors are never retried. |
| Documented limit of 3 calls per 5 seconds per IP | A sliding-window limiter shared across all calls on a client. |
| Units differ **between fields in the same response** — `eToday` in kWh but `eTotal` in MWh | Values are normalised via their `<field>Str` companion to W and kWh, so counters nest correctly. |
| A real `inverterDetail` response has ~812 keys | ~50 are explicitly typed; the rest are retained via `model_extra`, so nothing is discarded and no schema change is needed when Solis adds a field. |
| Fields are omitted rather than zeroed when not applicable | Numerics default to `None`, never `0.0`, so Home Assistant shows `unknown` instead of a false zero. |

Each failure cause raises its own exception — `SolisAuthError`, `SolisClockSkewError`,
`SolisRateLimitError`, `SolisAPIError`, `SolisTransportError` — so a wrong key never
looks like an empty account.

## Development

```bash
uv sync --group ha        # optional: installs Home Assistant for integration tests
uv run pytest             # offline suite
uv run pytest -m live     # against the real API; needs .env (slow, ~5 min)
uv run ruff check .
uv run ruff format .
```

`tests/test_ha_integration.py` builds the component and loads it against a real Home
Assistant install. It is skipped unless the `ha` group is installed.

### Secret scanning

Install the git hooks once per clone:

```bash
uv run pre-commit install
```

Two layers stop credentials reaching the repo, both verified against the real `.env`:

- **gitleaks** scans staged content for API keys, tokens and credentials. `.gitleaks.toml`
  extends the default rule set with a SolisCloud-specific rule for `SOLIS_ID` and
  `SOLIS_SECRET`.
- **`forbid-env-files`** rejects any staged `.env` outright, since `git add -f` bypasses
  `.gitignore`. `.env.example` is deliberately not matched.

To check the whole history rather than just staged changes:

```bash
uv run pre-commit run --all-files
```
