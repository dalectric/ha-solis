"""Command line entry point: show, probe and dump.

``probe`` exists because the integration this replaces reports every failure as
"No inverters found". When something goes wrong here, the exact HTTP status, the API's
own code and message, and the literal string that was signed are all printed.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from pydantic import ValidationError

from .client import SolisCloudClient
from .errors import SolisError
from .settings import get_settings

DUMP_DIR = Path("data/raw")


def _mask(value: str) -> str:
    return f"{value[:4]}...{value[-2:]}" if len(value) > 8 else "***"


def _print_debug(client: SolisCloudClient) -> None:
    dbg = client.last_request_debug
    if not dbg:
        return
    print("\n  --- last request ---")
    print(f"  endpoint:    {dbg.get('endpoint')}")
    print(f"  http status: {dbg.get('status', '(no response)')}")
    print(f"  body:        {dbg.get('body')}")
    print(f"  Date sent:   {dbg.get('date')}")
    print(f"  Date server: {dbg.get('server_date') or '(none)'}")
    print("  string-to-sign (newlines shown as \\n):")
    print(f"    {dbg.get('sign_string', '').encode('unicode_escape').decode()}")


def _clock_offset(client: SolisCloudClient) -> None:
    server = client.last_request_debug.get("server_date")
    if not server:
        return
    try:
        skew = (datetime.now(UTC) - parsedate_to_datetime(server)).total_seconds()
    except TypeError, ValueError:
        return
    verdict = "OK" if abs(skew) < 30 else "TOO LARGE -- this will break the signature"
    print(f"  clock offset vs server: {skew:+.1f}s  [{verdict}]")


async def cmd_show() -> int:
    async with SolisCloudClient() as client:
        inverters = await client.inverter_list()
        status = inverters.inverter_status_vo
        print(
            f"Inverters: {status.all} total, {status.normal} normal, {status.fault} fault, {status.offline} offline\n"
        )
        for inv in inverters.records:
            print(f"Inverter {inv.sn} (id={inv.id}, state={inv.state})")
            print(f"  Power:           {inv.pac} W")
            print(f"  Today:           {inv.e_today} kWh")
            print(f"  Total:           {inv.e_total} kWh")
            print(f"  Battery SOC:     {inv.battery_capacity_soc} %")
            print(f"  Battery Power:   {inv.battery_power} W")
            print(f"  Home Load:       {inv.family_load_power} W")
            print(f"  Grid Power:      {inv.p_sum} W")
            print(f"  Grid Buy Today:  {inv.grid_purchased_today_energy} kWh")
            print(f"  Grid Sell Today: {inv.grid_sell_today_energy} kWh")
            print()
        if not inverters.records:
            print("No inverter records found (the API answered successfully with an empty list).")
    return 0


async def cmd_probe(hammer: bool) -> int:
    settings = get_settings()
    print("Config")
    print(f"  url:    {settings.solis_url}")
    print(f"  key id: {_mask(settings.solis_id.get_secret_value())}")
    print(f"  secret: {_mask(settings.solis_secret.get_secret_value())}\n")

    async with SolisCloudClient() as client:
        print("1. /v1/api/inverterList")
        try:
            inverters = await client.inverter_list()
        except SolisError as err:
            print(f"  FAILED: {type(err).__name__}: {err}")
            # Printed here as well: a signing failure caused by clock skew takes this
            # path, which is precisely when the offset needs to be visible.
            _clock_offset(client)
            _print_debug(client)
            return 1
        _clock_offset(client)
        print(f"  ok -- {len(inverters.records)} record(s), status {inverters.inverter_status_vo.all} total")
        for inv in inverters.records:
            print(f"     - {inv.sn} (id={inv.id}, station={inv.station_id})")

        if not inverters.records:
            print("\n  The call succeeded but returned no inverters. That is an empty account or")
            print("  the wrong region URL -- not an auth or signature problem.")
            return 1

        print("\n2. /v1/api/inverterDetail")
        for inv in inverters.records:
            try:
                detail = await client.inverter_detail(inverter_id=inv.id, inverter_sn=inv.sn)
            except SolisError as err:
                print(f"  {inv.sn}: FAILED: {type(err).__name__}: {err}")
                _print_debug(client)
                return 1
            declared = type(detail).model_fields
            set_count = sum(1 for name in declared if getattr(detail, name) is not None)
            extra = len(detail.model_extra or {})
            print(
                f"  {inv.sn}: ok -- {set_count}/{len(declared)} typed field(s) set, "
                f"{extra} further field(s) retained via model_extra"
            )

        if hammer:
            print("\n3. Rate limit check -- 10 calls as fast as the limiter allows")
            start = asyncio.get_running_loop().time()
            for i in range(10):
                await client.inverter_list()
                print(f"  call {i + 1:2d} at t+{asyncio.get_running_loop().time() - start:5.2f}s")
            print("  no rate-limit errors -- the 3-per-5s limiter is holding")

    print("\nAll checks passed.")
    return 0


async def cmd_dump() -> int:
    """Write the API's own JSON, straight off the wire.

    Deliberately bypasses the pydantic models: dumping validated output would show
    values this package has already transformed, which is useless for working out
    what SolisCloud actually sends.
    """
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    async with SolisCloudClient() as client:
        listing = await client._request("/v1/api/inverterList", {"pageNo": 1, "pageSize": 100})
        calls: list[tuple[str, object]] = [("inverterList", listing)]
        for record in listing.get("page", {}).get("records", []):
            sn, inv_id = record.get("sn"), record.get("id")
            calls.append(
                (f"inverterDetail_{sn}", await client._request("/v1/api/inverterDetail", {"id": inv_id, "sn": sn}))
            )
            if station_id := record.get("stationId"):
                calls.append(
                    (f"stationDetail_{station_id}", await client._request("/v1/api/stationDetail", {"id": station_id}))
                )
        for name, payload in calls:
            path = DUMP_DIR / f"{name}.json"
            path.write_text(json.dumps(payload, indent=2, default=str))
            print(f"wrote {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ha-solis", description="SolisCloud API client")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("show", help="print a summary of each inverter (default)")
    probe = sub.add_parser("probe", help="diagnose connectivity, credentials and signing")
    probe.add_argument("--hammer", action="store_true", help="also exercise the rate limiter")
    sub.add_parser("dump", help="write raw API responses to data/raw/ for inspection")

    args = parser.parse_args()
    try:
        if args.command == "probe":
            return asyncio.run(cmd_probe(args.hammer))
        if args.command == "dump":
            return asyncio.run(cmd_dump())
        return asyncio.run(cmd_show())
    except SolisError as err:
        print(f"{type(err).__name__}: {err}", file=sys.stderr)
        return 1
    except ValidationError as err:
        missing = ", ".join(str(e["loc"][0]).upper() for e in err.errors() if e["type"] == "missing")
        print(
            f"Configuration error: {missing or err}.\n"
            "Copy .env.example to .env and fill in your SolisCloud credentials.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
