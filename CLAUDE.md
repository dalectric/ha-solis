# CLAUDE.md

## Project Overview

ha-solis uses the SolisCloud API to fetch inverter data for photovoltaic, battery, load
and grid in-feed monitoring, and exposes it to Home Assistant.

## Tech Stack

- Python 3.14+
- **uv** for dependency management and running code (not Poetry)
- Pydantic / Pydantic Settings for configuration and data models
- httpx (async) for HTTP, respx for mocking it in tests
- ruff for lint and format

## Running Code

```bash
uv run ha-solis [show|probe|dump]
uv run python -m soliscloud_api probe
```

Always use `uv run` to invoke anything — never bare `python`.

## Project Structure

```
src/soliscloud_api/      # async API client; no Home Assistant imports
  auth.py                # request signing (pure functions)
  client.py              # SolisCloudClient, rate limiter, retry, error mapping
  errors.py              # one exception type per failure cause
  models.py              # pydantic response models
  settings.py            # pydantic-settings; lazy get_settings()
  __main__.py            # show / probe / dump CLI
custom_components/soliscloud/   # thin Home Assistant layer
scripts/build_ha.py      # vendors the client into dist/soliscloud for deployment
tests/
```

## Design Conventions

- Use **Pydantic `BaseModel`** for all data structures; **`BaseSettings`** for config.
  No dataclasses.
- Use **`pathlib.Path`** for local file paths — never `os.path`.
- **Never signal failure by returning an empty collection.** Raise the specific
  `SolisError` subclass. An empty inverter list must mean exactly that.
- **Numerics default to `None`, never `0.0`**, so "not reported" stays distinguishable
  from "zero".
- Dependency versions in `pyproject.toml` are unpinned (`uv.lock` pins the resolved
  set). Upgrade deliberately with `uv lock --upgrade`, then run the tests.

## API Behaviour Worth Remembering

Measured against the live API — do not re-derive:

- **Slow and lossy.** Median response ~16s, tail past 30s, roughly 1 call in 4 exceeds
  30s. Default timeout is 60s with up to 3 retries. A short timeout is the reason
  `fboundy/solis-sensor` reports "No inverters found".
- **Rate limit:** three calls per five seconds per IP.
- **Units vary between fields in one response** (`eToday` kWh, `eTotal` MWh). The
  `<field>Str` companion gives the unit; `models.py` normalises to W and kWh.
- **`inverterDetail` returns ~812 keys.** ~50 typed, the rest kept via `model_extra`.
- When investigating field names, run `uv run ha-solis dump` and read `data/raw/` —
  it writes the raw wire payload, deliberately bypassing the models.

## Testing

```bash
uv run pytest             # offline; live tests excluded via addopts
uv run pytest -m live     # against the real API; needs .env (~5 min)
```

`tests/test_ha_component.py` validates the Home Assistant layer by AST-parsing it, so
the suite runs without `homeassistant` installed. `tests/test_ha_integration.py` builds
the component and imports it against a real Home Assistant (`uv sync --group ha`);
skipped otherwise.

**The vendored client must use relative imports only.** `src/soliscloud_api/` is copied
inside the component by `scripts/build_ha.py`, where the standalone package does not
exist. A single `from soliscloud_api.x import y` breaks the integration on a real HA box
while still passing locally, because the installed copy masks it. A test guards this.

## Secrets

`uv run pre-commit install` once per clone. Staged content is scanned by **gitleaks**
(config in `.gitleaks.toml`, with a custom `soliscloud-key-secret` rule), and a local
`forbid-env-files` hook rejects any staged `.env` because `git add -f` bypasses
`.gitignore`. Never add credentials to tests or fixtures — use the placeholder values
in `.env.example`.

## Environment Configuration

`.env` in the project root provides `SOLIS_ID`, `SOLIS_SECRET`, `SOLIS_URL` and
optionally `SOLIS_TIMEOUT`. See `.env.example`.

**Do not commit `.env`**, and do not put coordinates or site geometry back into source:
they identify where the user lives. `.gitignore` matches `.env` at any depth and a
pre-commit hook rejects it outright.

## VS Code

Launch configurations in `.vscode/launch.json`.

## Living Documentation

Keep this file and `README.md` up to date as the project evolves — new modules,
dependencies, commands or structure changes should be reflected in both.
