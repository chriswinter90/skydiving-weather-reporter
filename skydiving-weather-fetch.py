#!/usr/bin/env python3
"""
Fetch weather data from Open-Meteo APIs for Start Skydiving, Middletown OH.

Usage:
    python3 skydiving-weather-fetch.py [output_path]

Outputs JSON to /tmp/weather-raw.json by default.
Data sources: Open-Meteo v1 forecast API (api.open-meteo.com)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# --- Config ---
LAT = 38.52
LON = -84.43
LOCATION_NAME = "Start Skydiving, Middletown OH"
BASE_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "America/New_York"

# Per-model configuration: pressure levels for cloud bands + exit wind level
MODEL_CONFIGS = {
    "ncep_gfs_seamless": {
        "display": "NOAA GFS",
        "cloud_levels": {
            "low":  [900, 875, 850],
            "mid":  [825, 800, 775],
            "high": [750, 725, 700, 675, 650, 625],
        },
        "exit_wind_level": 625,  # ~14,000 ft MSL ≈ 13,350 ft AGL
    },
    "ecmwf_ifs": {
        "display": "ECMWF",
        "cloud_levels": {
            "low":  [925, 850],
            "mid":  [700],
            "high": [600, 500],
        },
        "exit_wind_level": 600,  # ~14,000 ft MSL ≈ 13,350 ft AGL
    },
}


def build_hourly_vars(model_id):
    """Build the list of hourly variables to request for a specific model."""
    cfg = MODEL_CONFIGS[model_id]
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
    # Cloud cover at this model's pressure levels
    all_levels = []
    for levels in cfg["cloud_levels"].values():
        all_levels.extend(levels)
    for level in sorted(set(all_levels)):
        hourly.append(f"cloud_cover_{level}hPa")
    # Exit wind
    hourly.append(f"wind_speed_{cfg['exit_wind_level']}hPa")
    hourly.append(f"wind_direction_{cfg['exit_wind_level']}hPa")
    return hourly


def fetch_model(model_id):
    """Fetch data from Open-Meteo for a single model using its specific config."""
    cfg = MODEL_CONFIGS[model_id]
    display_name = cfg["display"]
    exit_level = cfg["exit_wind_level"]
    hourly_vars = build_hourly_vars(model_id)

    params = {
        "latitude": LAT,
        "longitude": LON,
        "forecast_model": model_id,
        "hourly": ",".join(hourly_vars),
        "timezone": TIMEZONE,
        "forecast_days": 3,
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

    def get_values(var_name):
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
                    result.append(f if f == f else None)
                except (TypeError, ValueError):
                    result.append(None)
        return result

    timestamps_epoch = []
    timestamps_str = []
    for t in times:
        dt = datetime.fromisoformat(t)
        timestamps_epoch.append(int(dt.replace(tzinfo=timezone.utc).timestamp()))
        timestamps_str.append(dt.strftime("%Y-%m-%d %H:%M %Z"))

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

    def avg_cloud_band(levels):
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
                            if f == f:
                                values.append(f)
                        except (TypeError, ValueError):
                            pass
            result.append(round(sum(values) / len(values)) if values else 0)
        return result

    surface["cloud_low"] = avg_cloud_band(cfg["cloud_levels"]["low"])
    surface["cloud_mid"] = avg_cloud_band(cfg["cloud_levels"]["mid"])
    surface["cloud_high"] = avg_cloud_band(cfg["cloud_levels"]["high"])

    exit_key = f"{exit_level}h"
    exit_winds = {
        exit_key: {
            "speed": get_values(f"wind_speed_{exit_level}hPa"),
            "direction": get_values(f"wind_direction_{exit_level}hPa"),
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
    for model_id in MODEL_CONFIGS:
        cfg = MODEL_CONFIGS[model_id]
        display_name = cfg["display"]
        print(f"Fetching {display_name} ({model_id})...")
        try:
            models.append(fetch_model(model_id))
            print(f"  ✅ {display_name} — {len(models[-1]['timestamps'])} hours")
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
