#!/usr/bin/env python3
"""
Fetch weather data from Open-Meteo APIs for Start Skydiving, Middletown OH.

Usage:
    python3 skydiving-weather-fetch.py [output_path]

Outputs JSON to /tmp/weather-raw.json by default.
Data sources:
  - GFS: https://api.open-meteo.com/v1/forecast?forecast_model=gfs
  - HRRR: https://api.open-meteo.com/v1/forecast?forecast_model=hrrr
  - ICON: https://api.open-meteo.com/v1/forecast?forecast_model=icon
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# --- Config ---
LAT = 38.52
LON = -84.43
LOCATION_NAME = "Start Skydiving, Middletown OH"
BASE_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "America/New_York"

# Pressure levels for cloud cover bands (skydiving-specific, MSL)
# Low (3k-5k ft): 900, 875, 850 hPa
# Mid (5k-8k ft): 825, 800, 775 hPa
# High (8k-14.5k ft): 750, 725, 700, 675, 650, 625 hPa
CLOUD_BANDS = {
    "low": [900, 875, 850],
    "mid": [825, 800, 775],
    "high": [750, 725, 700, 675, 650, 625],
}

# Exit wind: 625hPa ≈ 14,000 ft MSL ≈ 13,350 ft AGL (close to 13,500 ft AGL exit)
EXIT_WIND_LEVEL = 625

ALL_CLOUD_LEVELS = CLOUD_BANDS["low"] + CLOUD_BANDS["mid"] + CLOUD_BANDS["high"]


def build_hourly_vars():
    """Build the list of hourly variables to request."""
    hourly = [
        "temperature_2m",
        "dewpoint_2m",
        "relative_humidity_2m",
        "wind_speed_10m",
        "wind_direction_10m",
        "wind_gusts_10m",
        "precipitation",
        "weather_code",
        "pressure_msl",
    ]
    # Cloud cover at each pressure level
    for level in ALL_CLOUD_LEVELS:
        hourly.append(f"cloud_cover_{level}hPa")
    # Exit wind at 625hPa
    hourly.append(f"wind_speed_{EXIT_WIND_LEVEL}hPa")
    hourly.append(f"wind_direction_{EXIT_WIND_LEVEL}hPa")
    return hourly


def fetch_model(model_id, display_name, max_days=3):
    """Fetch data from Open-Meteo for a single model."""
    hourly_vars = build_hourly_vars()
    params = {
        "latitude": LAT,
        "longitude": LON,
        "forecast_model": model_id,
        "hourly": ",".join(hourly_vars),
        "timezone": TIMEZONE,
        "forecast_days": max_days,
        "wind_speed_unit": "kn",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
    }

    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise ValueError(f"Open-Meteo error: {data.get('reason', data)}")

    hourly = data["hourly"]
    hourly_units = data.get("hourly_units", {})
    times = hourly["time"]
    n = len(times)

    # Build variable name -> index mapping
    var_names = hourly_vars  # from our request
    var_index = {name: i for i, name in enumerate(var_names)}

    def get_values(var_name):
        """Extract values for a variable, handling None/NaN."""
        if var_name not in hourly:
            return [None] * n
        raw = hourly[var_name]
        result = []
        for v in raw:
            if v is None:
                result.append(None)
            else:
                try:
                    f = float(v)
                    result.append(f if f == f else None)  # NaN check
                except (TypeError, ValueError):
                    result.append(None)
        return result

    # Timestamps as epoch seconds for processing
    timestamps_epoch = []
    timestamps_str = []
    for t in times:
        dt = datetime.fromisoformat(t)
        timestamps_epoch.append(int(dt.replace(tzinfo=timezone.utc).timestamp()))
        timestamps_str.append(dt.strftime("%Y-%m-%d %H:%M %Z"))

    # Surface variables
    surface = {
        "temp_f": get_values("temperature_2m"),
        "dewpoint_f": get_values("dewpoint_2m"),
        "rh": get_values("relative_humidity_2m"),
        "wind_speed": get_values("wind_speed_10m"),
        "wind_direction": get_values("wind_direction_10m"),
        "gust_speed": get_values("wind_gusts_10m"),
        "precip": get_values("precipitation"),
        "weather_code": get_values("weather_code"),
        "pressure": get_values("pressure_msl"),
    }

    # Average cloud cover for each band
    def avg_cloud_band(levels):
        """Average cloud cover across a band of pressure levels."""
        result = []
        for i in range(n):
            values = []
            for level in levels:
                var_name = f"cloud_cover_{level}hPa"
                raw = hourly.get(var_name, [])
                if i < len(raw):
                    v = raw[i]
                    if v is not None:
                        try:
                            f = float(v)
                            if f == f:  # not NaN
                                values.append(f)
                        except (TypeError, ValueError):
                            pass
            result.append(round(sum(values) / len(values)) if values else 0)
        return result

    surface["cloud_low"] = avg_cloud_band(CLOUD_BANDS["low"])
    surface["cloud_mid"] = avg_cloud_band(CLOUD_BANDS["mid"])
    surface["cloud_high"] = avg_cloud_band(CLOUD_BANDS["high"])

    # Exit winds at 625hPa
    exit_winds = {
        "625h": {
            "speed": get_values(f"wind_speed_{EXIT_WIND_LEVEL}hPa"),
            "direction": get_values(f"wind_direction_{EXIT_WIND_LEVEL}hPa"),
        }
    }

    return {
        "name": model_id,
        "display": display_name,
        "timestamps": timestamps_str,
        "timestamps_epoch": timestamps_epoch,
        "surface": surface,
        "exit_winds": exit_winds,
        "units": {k: v for k, v in hourly_units.items()},
    }


def main():
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/weather-raw.json")

    models = []
    # Primary fetch — GFS is the default on free tier and has the best variable coverage
    print("Fetching GFS...")
    try:
        models.append(fetch_model("gfs", "GFS"))
        print(f"  ✅ GFS — {len(models[-1]['timestamps'])} hours")
    except Exception as e:
        print(f"  ✗ GFS failed: {e}", file=sys.stderr)

    # Also try HRRR and ICON — on free tier they may return the same data as GFS
    # We fetch them anyway in case they diverge, and de-dup after
    for model_id, display_name in [("hrrr", "HRRR"), ("icon", "ICON")]:
        print(f"Fetching {display_name}...")
        time.sleep(0.3)
        try:
            m = fetch_model(model_id, display_name)
            # Check if this model actually differs from GFS
            if models:
                gfs = models[0]["surface"]
                gfs_ew = models[0]["exit_winds"]
                same = (m["surface"]["temp_f"] == gfs["temp_f"] and
                        m["surface"]["cloud_low"] == gfs["cloud_low"] and
                        m["exit_winds"]["625h"]["speed"] == gfs_ew["625h"]["speed"])
                if same:
                    print(f"  ⚠️  {display_name} returned identical data to GFS (free tier limitation) — skipping")
                    continue
            models.append(m)
            print(f"  ✅ {display_name} — {len(m['timestamps'])} hours (distinct data)")
        except Exception as e:
            print(f"  ✗ {display_name} failed: {e}", file=sys.stderr)

    if not models:
        print("ERROR: No models fetched", file=sys.stderr)
        sys.exit(1)

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": LAT, "lon": LON, "name": LOCATION_NAME},
        "models": models,
    }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    print(f"\n✅ Saved to {output_path}")
    print(f"   Models: {', '.join(m['display'] for m in models)}")
    print(f"   Hours: {len(models[0]['timestamps']) if models else 0}")


if __name__ == "__main__":
    main()
