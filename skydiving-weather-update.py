#!/usr/bin/env python3
"""
Process Open-Meteo forecast data (multi-model) into markdown + JSON for the
skydiving-weather-reporter repo.

Usage:
    python3 skydiving-weather-update.py <raw_data.json> <repo_path>

Expects raw_data.json:
{
  "generated_at": "2026-07-26T22:00:00Z",
  "location": {"lat": 38.52, "lon": -84.43, "name": "Start Skydiving, Middletown OH"},
  "models": [
    {
      "name": "gfs_hrrr",
      "display": "GFS+HRRR",
      "timestamps": ["2026-07-26 22:00 UTC", ...],
      "surface": {
        "temp_f": [...], "dewpoint_f": [...], "rh": [...],
        "wind_speed": [...], "wind_direction": [...], "gust_speed": [...],
        "precip": [...], "weather_code": [...], "pressure": [...],
        "cloud_low": [...], "cloud_mid": [...], "cloud_high": [...]
      },
      "exit_winds": { "625h": { "speed": [...], "direction": [...] } }
    }
  ]
}
"""

import json
import math
import sys
from calendar import month_abbr
from datetime import datetime, timezone, timedelta

# --- Config ---
LAT = 38.52
LON = -84.43
LOCATION_NAME = "Start Skydiving, Middletown OH"
AIRFIELD_ELEVATION_Ft = 650  # ft MSL
EXIT_ALTITUDE_AGL = 13500  # ft AGL
EXIT_ALTITUDE_MSL = EXIT_ALTITUDE_AGL + AIRFIELD_ELEVATION_Ft  # ~14,150 ft MSL
MAX_HOURS = 72  # Only show first 72 hours

# Jump-readiness thresholds
WIND_GO, WIND_CAUTION = 20, 23
GUST_SPREAD_GO, GUST_SPREAD_CAUTION = 10, 15
LOW_CLOUD_GO, LOW_CLOUD_CAUTION = 50, 80
MID_CLOUD_GO, MID_CLOUD_CAUTION = 50, 80
EXIT_WIND_GO, EXIT_WIND_CAUTION = 25, 35

# Cloud band definitions (skydiving-specific, MSL)
CLOUD_BANDS = {
    "low": (3000, 5000),    # 900, 875, 850 hPa
    "mid": (5000, 8000),    # 825, 800, 775 hPa
    "high": (8000, 14500),  # 750, 725, 700, 675, 650, 625 hPa
}


def local_tz(dt: datetime) -> timezone:
    year = dt.year
    march_first = datetime(year, 3, 1)
    dst_start = march_first + timedelta(days=(6 - march_first.weekday()) % 7 + 7)
    nov_first = datetime(year, 11, 1)
    dst_end = nov_first + timedelta(days=(6 - nov_first.weekday()) % 7)
    naive = dt.replace(tzinfo=None)
    return timezone(timedelta(hours=-4)) if dst_start <= naive < dst_end else timezone(timedelta(hours=-5))


def wind_dir(deg: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(deg / 22.5) % 16]


def parse_ts(ts_str: str) -> datetime:
    clean = ts_str.strip().rstrip(" UTC")
    return datetime.strptime(clean, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def utc_to_local(ts_str: str) -> tuple:
    dt = parse_ts(ts_str)
    tz = local_tz(dt)
    local = dt.astimezone(tz)
    hour = local.hour % 12 or 12
    return local, f"{hour}:{local.minute:02d}{'am' if local.hour < 12 else 'pm'}"


def truncate_to_max_hours(timestamps: list, arrays: dict, max_hours: int) -> tuple:
    """Truncate timestamps and all arrays to cover at most max_hours from the first timestamp."""
    if len(timestamps) < 2:
        return timestamps, arrays
    first_dt = parse_ts(timestamps[0])
    last_dt = parse_ts(timestamps[-1])
    actual_hours = (last_dt - first_dt).total_seconds() / 3600
    if actual_hours <= max_hours:
        return timestamps, arrays
    cutoff = first_dt + timedelta(hours=max_hours)
    limit = 0
    for i, ts in enumerate(timestamps):
        if parse_ts(ts) <= cutoff:
            limit = i + 1
        else:
            break
    truncated_ts = timestamps[:limit]
    truncated_arrays = {}
    for key, arr in arrays.items():
        truncated_arrays[key] = arr[:limit] if arr else arr
    return truncated_ts, truncated_arrays


def process_surface(surface: dict, timestamps: list) -> list:
    """Process surface data into per-timestamp entries."""
    entries = []
    for i, ts in enumerate(timestamps):
        local_dt, time_str = utc_to_local(ts)
        e = {"time_utc": ts, "time_local": time_str, "datetime_local_iso": local_dt.isoformat()}

        # Temperature & dewpoint (already in Fahrenheit)
        for key in ("temp_f", "dewpoint_f"):
            arr = surface.get(key, [])
            if i < len(arr) and arr[i] is not None:
                e[key] = round(arr[i], 1)

        # Wind speed, direction, gusts (already in knots)
        ws = surface.get("wind_speed", [])
        wd = surface.get("wind_direction", [])
        gs = surface.get("gust_speed", [])
        if i < len(ws) and ws[i] is not None:
            e["wind_kts"] = round(ws[i], 1)
        if i < len(wd) and wd[i] is not None:
            e["wind_dir"] = wind_dir(wd[i])
        if i < len(gs) and gs[i] is not None:
            e["gust_kts"] = round(gs[i], 1)
        if "wind_kts" in e and "gust_kts" in e:
            e["gust_spread_kts"] = round(max(0, e["gust_kts"] - e["wind_kts"]), 1)

        # Cloud cover (pre-averaged bands, already in %)
        for key, out in [("cloud_low", "low_pct"), ("cloud_mid", "mid_pct"), ("cloud_high", "high_pct")]:
            arr = surface.get(key, [])
            if i < len(arr) and arr[i] is not None:
                e[out] = round(arr[i])

        # Precipitation (already in inches)
        arr = surface.get("precip", [])
        if i < len(arr) and arr[i] is not None:
            e["precip"] = round(arr[i], 4)

        # Relative humidity
        arr = surface.get("rh", [])
        if i < len(arr) and arr[i] is not None:
            e["rh_pct"] = round(arr[i])

        # Pressure (hPa -> inHg)
        arr = surface.get("pressure", [])
        if i < len(arr) and arr[i] is not None:
            e["pressure_inhg"] = round(arr[i] / 33.8639, 2)

        # Weather code
        arr = surface.get("weather_code", [])
        if i < len(arr) and arr[i] is not None:
            e["weather_code"] = int(arr[i])

        # Cloud base estimate: (Temp - Dewpoint spread in F) * 400 ft
        if "temp_f" in e and "dewpoint_f" in e:
            spread = e["temp_f"] - e["dewpoint_f"]
            e["cloud_base_ft"] = max(0, round(spread * 400))

        entries.append(e)
    return entries


def process_exit_winds(exit_winds: dict, timestamps: list) -> list:
    """Process exit wind data — supports any pressure level key (e.g. '625h', '600h')."""
    entries = []
    if not exit_winds:
        return entries
    # Use whatever pressure level key the model provides
    level_key = list(exit_winds.keys())[0]
    speed_arr = exit_winds[level_key].get("speed", [])
    dir_arr = exit_winds[level_key].get("direction", [])
    for i, ts in enumerate(timestamps):
        if i >= len(speed_arr) or speed_arr[i] is None:
            continue
        spd = speed_arr[i]
        e = {"time_utc": ts, "pressure_level": level_key, "approx_alt_ft": 14000,
             "wind_kts": round(spd, 1)}
        if i < len(dir_arr) and dir_arr[i] is not None:
            e["wind_dir"] = wind_dir(dir_arr[i])
        entries.append(e)
    return entries


def evaluate_hour(entry: dict, exit_wind: dict) -> str:
    """Evaluate a single hour. Returns 'GO', 'CAUTION', or 'NO JUMP'."""
    hr = "GO"

    wind = entry.get("wind_kts", 0)
    if wind > WIND_CAUTION:
        hr = "NO JUMP"
    elif wind > WIND_GO:
        hr = "CAUTION"

    spread = entry.get("gust_spread_kts", 0)
    if spread > GUST_SPREAD_CAUTION:
        hr = "NO JUMP"
    elif spread > GUST_SPREAD_GO:
        if hr != "NO JUMP":
            hr = "CAUTION"

    low = entry.get("low_pct", 0)
    if low > LOW_CLOUD_CAUTION:
        hr = "NO JUMP"
    elif low > LOW_CLOUD_GO:
        if hr != "NO JUMP":
            hr = "CAUTION"

    mid = entry.get("mid_pct", 0)
    if mid > MID_CLOUD_CAUTION:
        hr = "NO JUMP"
    elif mid > MID_CLOUD_GO:
        if hr != "NO JUMP":
            hr = "CAUTION"

    precip = entry.get("precip", 0)
    if precip > 0.001:
        hr = "NO JUMP"

    ew = exit_wind.get(entry.get("time_utc"))
    if ew:
        ew_kts = ew["wind_kts"]
        if ew_kts > EXIT_WIND_CAUTION:
            hr = "NO JUMP"
        elif ew_kts > EXIT_WIND_GO:
            if hr != "NO JUMP":
                hr = "CAUTION"

    return hr


def evaluate_day(entries: list, exit_winds: list) -> dict:
    """Evaluate all hours in a day. Returns summary dict."""
    exit_map = {ew["time_utc"]: ew for ew in exit_winds}

    ratings = []
    for entry in entries:
        ratings.append(evaluate_hour(entry, exit_map))

    go_count = ratings.count("GO")
    caution_count = ratings.count("CAUTION")
    no_jump_count = ratings.count("NO JUMP")
    total = len(ratings)

    if no_jump_count > total / 2:
        day_rating = "NO JUMP"
    elif go_count > total / 2:
        day_rating = "GO"
    elif go_count >= no_jump_count:
        day_rating = "CAUTION"
    else:
        day_rating = "NO JUMP"

    winds = [e.get("wind_kts", 0) for e in entries]
    gusts = [e.get("gust_kts", 0) for e in entries]
    spreads = [e.get("gust_spread_kts", 0) for e in entries]
    low_clouds = [e.get("low_pct", 0) for e in entries]
    mid_clouds = [e.get("mid_pct", 0) for e in entries]
    temps = [e.get("temp_f", 0) for e in entries]
    dewpoints = [e.get("dewpoint_f", 0) for e in entries]
    precip_vals = [e.get("precip", 0) for e in entries]

    exit_winds_list = []
    for e in entries:
        ew = exit_map.get(e["time_utc"])
        if ew:
            exit_winds_list.append(ew["wind_kts"])

    cloud_bases = [e.get("cloud_base_ft") for e in entries if e.get("cloud_base_ft") is not None]

    jump_hours = [e for e in entries if 6 <= datetime.fromisoformat(e["datetime_local_iso"]).hour <= 20]
    jump_ratings = [evaluate_hour(e, exit_map) for e in jump_hours]
    jump_go = jump_ratings.count("GO") if jump_ratings else 0
    jump_total = len(jump_ratings)

    return {
        "rating": day_rating,
        "go_hours": go_count,
        "caution_hours": caution_count,
        "no_jump_hours": no_jump_count,
        "total_hours": total,
        "jump_go": jump_go,
        "jump_total": jump_total,
        "avg_surf_wind": round(sum(winds) / len(winds), 1) if winds else 0,
        "max_surf_wind": max(winds) if winds else 0,
        "avg_exit_wind": round(sum(exit_winds_list) / len(exit_winds_list), 1) if exit_winds_list else 0,
        "max_exit_wind": max(exit_winds_list) if exit_winds_list else 0,
        "max_gust": max(gusts) if gusts else 0,
        "max_spread": max(spreads) if spreads else 0,
        "avg_low_cloud": round(sum(low_clouds) / len(low_clouds)) if low_clouds else 0,
        "max_low_cloud": max(low_clouds) if low_clouds else 0,
        "avg_mid_cloud": round(sum(mid_clouds) / len(mid_clouds)) if mid_clouds else 0,
        "max_mid_cloud": max(mid_clouds) if mid_clouds else 0,
        "avg_temp": round(sum(temps) / len(temps), 1) if temps else 0,
        "max_temp": max(temps) if temps else 0,
        "min_temp": min(temps) if temps else 0,
        "avg_dewpoint": round(sum(dewpoints) / len(dewpoints), 1) if dewpoints else 0,
        "total_precip": round(sum(precip_vals), 3),
        "has_precip": any(p > 0.001 for p in precip_vals),
        "avg_cloud_base": round(sum(cloud_bases) / len(cloud_bases)) if cloud_bases else 0,
    }


def evaluate_verdict(surface: list, exit_winds: list) -> dict:
    """Overall verdict for the entire forecast (used for data.json history)."""
    jump_hours = [e for e in surface if 6 <= datetime.fromisoformat(e["datetime_local_iso"]).hour <= 20]
    if not jump_hours:
        return {"rating": "NO JUMP", "best_window": "N/A", "reasons": ["No jump-hour data"]}

    exit_map = {ew["time_utc"]: ew for ew in exit_winds}

    good, caution, no_jump = [], [], []
    for entry in jump_hours:
        hr = evaluate_hour(entry, exit_map)
        if hr == "GO":
            good.append(entry)
        elif hr == "CAUTION":
            caution.append(entry)
        else:
            no_jump.append(entry)

    rating = "GO" if good else "CAUTION" if caution else "NO JUMP"
    best = good or caution
    window = (f"{best[0]['time_local']}-{best[-1]['time_local']}" if len(best) >= 2
              else (best[0]['time_local'] if best else "None"))

    summary = []
    for label, grp in [("GO", good), ("CAUTION", caution), ("NO JUMP", no_jump)]:
        if grp:
            summary.append(f"{len(grp)} hour{'s' if len(grp) != 1 else ''} rated {label}")

    return {"rating": rating, "best_window": window, "reasons": summary}


def render_model_section(entries: list, exit_winds: list, model_name: str, display_name: str) -> list:
    """Render a single model's forecast as markdown lines."""
    days = {}
    for e in entries:
        dt = datetime.fromisoformat(e["datetime_local_iso"])
        key = dt.strftime("%A %b %d")
        days.setdefault(key, []).append(e)

    exit_map = {ew["time_utc"]: f"{ew['wind_kts']}{ew['wind_dir']}" for ew in exit_winds}

    lines = [f"### {display_name}", "",
             f"*Note: Exit winds at ~14k ft MSL (~13,350 ft AGL — actual exit: {EXIT_ALTITUDE_AGL:,} ft AGL)*", ""]
    for day, group in days.items():
        # Only show 4am–10pm local time
        visible = [e for e in group if 4 <= datetime.fromisoformat(e["datetime_local_iso"]).hour <= 22]
        if not visible:
            continue
        lines.extend([f"**{day}**", "",
                       "| Time | Temp°F | Surf | Gusts | Spread | Exit(~13.5k) | ClBase(ft) | LowCl | MidCl | HighCl | Dewpt°F | Precip |",
                       "|---|---|---|---|---|---|---|---|---|---|---|---|"])
        for e in visible:
            w = f"{e.get('wind_kts', '-')} {e.get('wind_dir', '')}"
            cb = e.get('cloud_base_ft', '-')
            lines.append(
                f"| {e['time_local']} | {e.get('temp_f', '-')} | {w} | {e.get('gust_kts', '-')} | "
                f"{e.get('gust_spread_kts', '-')} | {exit_map.get(e['time_utc'], '-')} | {cb} | "
                f"{e.get('low_pct', '-')}% | {e.get('mid_pct', '-')}% | {e.get('high_pct', '-')}% | "
                f"{e.get('dewpoint_f', '-')} | {e.get('precip', 0):.3f}\" |"
            )
        lines.append("")
    return lines


def rating_emoji(rating: str) -> str:
    return {"GO": "✅", "CAUTION": "⚠️", "NO JUMP": "❌"}.get(rating, "❓")


def render_daily_summaries(models_data: list) -> list:
    """Render per-model daily summaries + cross-model consensus."""
    lines = ["## Daily Summary", ""]

    # Build per-day summaries for each model
    model_daily = {}
    for md in models_data:
        disp = md["display_name"]
        entries = md["surface"]
        exit_winds = md["exit_winds"]

        days = {}
        for e in entries:
            dt = datetime.fromisoformat(e["datetime_local_iso"])
            key = dt.strftime("%A %b %d")
            days.setdefault(key, []).append(e)

        model_daily[disp] = {}
        for day, group in days.items():
            model_daily[disp][day] = evaluate_day(group, exit_winds)

    # Collect all unique days
    all_days = []
    seen_days = set()
    for disp in model_daily:
        for day in model_daily[disp]:
            if day not in seen_days:
                all_days.append(day)
                seen_days.add(day)

    # Sort chronologically
    month_num = {m: i for i, m in enumerate(month_abbr) if m}
    def day_sort_key(d):
        parts = d.split()
        return (month_num.get(parts[1], 0), int(parts[2]))
    all_days.sort(key=day_sort_key)

    # --- Per-model summary tables ---
    for disp, daily in model_daily.items():
        lines.append(f"### {disp}")
        lines.append("")
        lines.append("| Day | Rating | Jump Hrs | Avg Surf | Max Gust | Avg Exit(~13.5k) | ClBase(ft) | Avg LowCl | Avg MidCl | Temp Range | Precip |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for day in all_days:
            if day not in daily:
                continue
            d = daily[day]
            jump_str = f"{d['jump_go']}/{d['jump_total']}" if d['jump_total'] > 0 else "N/A"
            precip_str = f"{d['total_precip']:.3f}\"" if d['has_precip'] else "None"
            temp_str = f"{d['min_temp']}–{d['max_temp']}°"
            cb_str = f"{d['avg_cloud_base']}ft" if d['avg_cloud_base'] > 0 else "—"
            lines.append(
                f"| {day} | {rating_emoji(d['rating'])} {d['rating']} | {jump_str} | "
                f"{d['avg_surf_wind']}kt | {d['max_gust']}kt | {d['avg_exit_wind']}kt | "
                f"{cb_str} | {d['avg_low_cloud']}% | {d['avg_mid_cloud']}% | {temp_str} | {precip_str} |"
            )
        lines.append("")

    # --- Cross-model consensus ---
    lines.append("### Consensus Across Models")
    lines.append("")

    # Build model column list dynamically
    model_disps = list(model_daily.keys())
    header = "| Day " + " | ".join(f"{m}" for m in model_disps) + " | Consensus |"
    sep = "|---" * (len(model_disps) + 2) + "|"
    lines.append(header)
    lines.append(sep)

    priority = {"GO": 0, "CAUTION": 1, "NO JUMP": 2}

    for day in all_days:
        day_ratings = []
        cells = []
        for disp in model_disps:
            if disp in model_daily and day in model_daily[disp]:
                d = model_daily[disp][day]
                cells.append(f"{rating_emoji(d['rating'])} {d['rating']}")
                day_ratings.append(d['rating'])
            else:
                cells.append("—")

        if day_ratings:
            rating_counts = {}
            for r in day_ratings:
                rating_counts[r] = rating_counts.get(r, 0) + 1
            if len(day_ratings) >= 2:
                majority = max(rating_counts, key=rating_counts.get)
                if rating_counts[majority] >= 2:
                    consensus = majority
                else:
                    consensus = max(day_ratings, key=lambda r: priority.get(r, -1))
            else:
                consensus = max(day_ratings, key=lambda r: priority.get(r, -1))

            jump_gos = []
            for disp in model_disps:
                if disp in model_daily and day in model_daily[disp]:
                    j = model_daily[disp][day]['jump_go']
                    jt = model_daily[disp][day]['jump_total']
                    if jt > 0:
                        jump_gos.append(f"{j}/{jt}")
            jump_summary = ", ".join(jump_gos) if jump_gos else "N/A"
            lines.append(f"| {day} | {' | '.join(cells)} | {rating_emoji(consensus)} {consensus} ({jump_summary}) |")

    lines.append("")

    # --- Key concerns ---
    lines.append("### Key Concerns")
    lines.append("")

    concerns = []
    for day in all_days:
        day_issues = []
        for disp in model_disps:
            if disp in model_daily and day in model_daily[disp]:
                d = model_daily[disp][day]
                if d["has_precip"]:
                    day_issues.append(f"{disp}: precip {d['total_precip']:.3f}\"")
                if d["max_surf_wind"] > WIND_CAUTION:
                    day_issues.append(f"{disp}: surf wind {d['max_surf_wind']}kt")
                if d["max_exit_wind"] > EXIT_WIND_CAUTION:
                    day_issues.append(f"{disp}: exit wind {d['max_exit_wind']}kt")
                if d["max_low_cloud"] > LOW_CLOUD_CAUTION:
                    day_issues.append(f"{disp}: low clouds {d['max_low_cloud']}%")
                if d["max_mid_cloud"] > MID_CLOUD_CAUTION:
                    day_issues.append(f"{disp}: mid clouds {d['max_mid_cloud']}% (blind exit)")
                if d["max_spread"] > GUST_SPREAD_CAUTION:
                    day_issues.append(f"{disp}: gust spread {d['max_spread']}kt")

        if day_issues:
            unique_issues = list(dict.fromkeys(day_issues))
            concerns.append(f"- **{day}**: {'; '.join(unique_issues)}")
        else:
            concerns.append(f"- **{day}**: No major concerns across models")

    if not concerns:
        concerns.append("- No forecast data available")

    for c in concerns:
        lines.append(c)
    lines.append("")

    return lines


def render_md(models_data: list, generated_at: str) -> str:
    """Render full markdown with all models."""
    gen_dt = datetime.fromisoformat(generated_at)
    if gen_dt.tzinfo is None:
        gen_dt = gen_dt.replace(tzinfo=timezone.utc)
    gen_local = gen_dt.astimezone(local_tz(gen_dt))
    tz = "EDT" if gen_local.utcoffset() == timedelta(hours=-4) else "EST"
    display = gen_local.strftime(f"%Y-%m-%d %-I:%M %p {tz}")

    lines = [
        f"# Start Skydiving — Middletown, OH", "",
        f"*Auto-updated every 6h · Last: {display}*",
        f"*Coordinates: {LAT}°N, {abs(LON)}°W*",
        f"*Airfield elevation: {AIRFIELD_ELEVATION_Ft} ft MSL · Exit: {EXIT_ALTITUDE_AGL:,} ft AGL*", "",
        f"## Models: {', '.join(m['display_name'] for m in models_data)}", "",
    ]

    for md in models_data:
        lines.extend(render_model_section(md["surface"], md["exit_winds"], md["model_name"], md["display_name"]))

    # Daily summaries + consensus
    lines.extend(render_daily_summaries(models_data))

    return "\n".join(lines)


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 skydiving-weather-update.py <raw_data.json> <repo_path>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        raw = json.load(f)

    generated_at = raw.get("generated_at", datetime.now(timezone.utc).isoformat())
    models = raw.get("models", [])
    if not models:
        print("ERROR: no models in raw data", file=sys.stderr)
        sys.exit(1)

    # Process each model — truncate to MAX_HOURS
    models_data = []
    for m in models:
        name = m["name"]
        display = m.get("display", name)
        timestamps = m.get("timestamps", [])

        # Truncate to first MAX_HOURS
        truncated_ts, truncated_surface = truncate_to_max_hours(
            timestamps, m.get("surface", {}), MAX_HOURS
        )
        # Truncate exit winds too
        truncated_exit = {}
        for level, data in m.get("exit_winds", {}).items():
            _, truncated_level = truncate_to_max_hours(timestamps, data, MAX_HOURS)
            truncated_exit[level] = truncated_level

        surface = process_surface(truncated_surface, truncated_ts)
        exit_winds = process_exit_winds(truncated_exit, truncated_ts)
        verdict = evaluate_verdict(surface, exit_winds)
        models_data.append({
            "model_name": name,
            "display_name": display,
            "surface": surface,
            "exit_winds": exit_winds,
            "verdict": verdict,
        })

    # Build forecast entry — store only verdicts and compact summary
    compact_models = []
    for md in models_data:
        compact_models.append({
            "model_name": md["model_name"],
            "display_name": md["display_name"],
            "verdict": md["verdict"],
            "surface_count": len(md["surface"]),
            "exit_winds_count": len(md["exit_winds"]),
        })
    forecast_entry = {
        "generated_at": generated_at,
        "location": {"lat": LAT, "lon": LON, "name": LOCATION_NAME},
        "models": compact_models,
    }

    # Update data.json with rolling 3-day window
    data_path = f"{sys.argv[2]}/data.json"
    try:
        with open(data_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"forecasts": []}

    forecasts = data.get("forecasts", [])
    forecasts.append(forecast_entry)

    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    pruned = []
    for fc in forecasts:
        try:
            ft = datetime.fromisoformat(fc["generated_at"])
            if ft.tzinfo is None:
                ft = ft.replace(tzinfo=timezone.utc)
            if ft >= cutoff:
                pruned.append(fc)
        except (KeyError, ValueError):
            pruned.append(fc)

    data["forecasts"] = pruned
    with open(data_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    # Render markdown
    md = render_md(models_data, generated_at)
    with open(f"{sys.argv[2]}/Start-Skydiving.md", "w") as f:
        f.write(md)

    # Summary
    model_names = ", ".join(
        f"{md['display_name']}({md['verdict']['rating']})" for md in models_data
    )
    print(f"✅ Updated — Models: {model_names}")
    print(f"   History entries: {len(pruned)}")


if __name__ == "__main__":
    main()
