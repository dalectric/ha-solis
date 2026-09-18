from .client import ForecastSolarClient
from .settings import get_site


def main():
    site = get_site()
    print(f"Site: {site.latitude}, {site.longitude}")
    print(f"Arrays: {', '.join(a.name for a in site.arrays)}\n")

    with ForecastSolarClient(site) as client:
        for result in client.estimate_all():
            _print_result(result)

        total = client.estimate_aggregated()
        _print_result(total)


def _print_result(result):
    print(f"--- {result.array_name} ---")

    if result.watt_hours_day:
        for day, wh in result.watt_hours_day.items():
            print(f"  {day}: {wh / 1000:.2f} kWh")

    if result.watt_hours_period:
        print(f"  Hourly periods: {len(result.watt_hours_period)} data points")

    print()


if __name__ == "__main__":
    main()
