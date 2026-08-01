# Skydiving Weather Reporter

Auto-generated skydiving weather forecasts updated every 6 hours from [Open-Meteo](https://open-meteo.com).

## Dropzones

| Dropzone | Forecast | Raw Data |
|----------|----------|----------|
| **Start Skydiving** — Middletown, OH | [weather-reports/Start-Skydiving/Start-Skydiving.md](weather-reports/Start-Skydiving/Start-Skydiving.md) | [data.json](weather-reports/Start-Skydiving/data.json) |
| **Cleveland Skydiving Center** — Northfield, OH | [weather-reports/Cleveland-Skydiving-Center/Cleveland-Skydiving-Center.md](weather-reports/Cleveland-Skydiving-Center/Cleveland-Skydiving-Center.md) | [data.json](weather-reports/Cleveland-Skydiving-Center/data.json) |

## Models

- **NOAA GFS** (`ncep_gfs_seamless`) — global forecast, ~13 km resolution
- **ECMWF** (`ecmwf_ifs`) — European Centre medium-range, ~8 km resolution

Both models provide 55 hours of hourly forecasts covering surface conditions, exit-altitude winds, cloud bands, precipitation, and CAPE.

## Cloud Bands (Pressure-Level Averages)

Cloud cover is averaged from specific pressure levels mapped to skydiving-relevant altitude bands:

| Band | Approx. Altitude | NOAA GFS Levels | ECMWF Levels |
|------|-----------------|-----------------|--------------|
| **Low** | 3,000–5,000 ft | 900, 875, 850 hPa | 925, 850 hPa |
| **Mid** | 5,000–8,000 ft | 825, 800, 775 hPa | *(none — gap in data)* |
| **High** | 8,000–14,500 ft | 750, 725, 700, 675, 650, 625 hPa | 700, 600, 500 hPa |

**Exit altitude (13,500 ft AGL ≈ 14,150 ft MSL) falls near the high-band ceiling.** Exit winds are sampled at 625 hPa (GFS) / 600 hPa (ECMWF), both ~14,000 ft MSL. Mid-cloud coverage is the primary concern — 100% mid clouds means exiting into a solid layer with no horizon reference and a blind deployment. Low clouds affect landing visibility.

## Ratings

Each model produces an overall verdict per forecast period:

- **GO** — conditions are within safe limits for the majority of the day
- **CAUTION** — jumpable with caveats (e.g., strong winds, high clouds, moderate CAPE)
- **NO JUMP** — conditions exceed safe limits (excessive winds, severe CAPE, sustained cloud cover)

## Repo Structure

```
weather-reports/
  Start-Skydiving/
    Start-Skydiving.md    # human-readable forecast table
    data.json             # raw hourly data + verdict
  Cleveland-Skydiving-Center/
    ...
scripts/                  # not committed — lives in a separate private repo
README.md
```
