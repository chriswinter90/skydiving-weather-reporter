# Skydiving Weather Reporter

Auto-generated weather forecasts for **Start Skydiving** in Middletown, OH.

- Updated every 6 hours from [Open-Meteo](https://open-meteo.com)
- Models: **NOAA GFS** (`ncep_gfs_seamless`) and **ECMWF** (`ecmwf_ifs`)
- See [Start-Skydiving.md](Start-Skydiving.md) for the latest human-readable forecast
- Raw forecast history in [data.json](data.json)

## Location

- **Airfield elevation:** 650 ft MSL (198 m)
- **Coordinates:** 38.52°N, 84.43°W
- **Typical exit altitude:** 13,500 ft AGL

## Cloud Bands (Pressure-Level Averages)

Cloud cover is averaged from specific pressure levels mapped to skydiving-relevant altitude bands:

| Band | Approx. Altitude | NOAA US Levels | ECMWF Levels |
|------|-----------------|------------|--------------|
| **Low** | 3,000–5,000 ft | 900, 875, 850 hPa | 925, 850 hPa |
| **Mid** | 5,000–8,000 ft | 825, 800, 775 hPa | *(none — gap in data)* |
| **High** | 8,000–14,500 ft | 750, 725, 700, 675, 650, 625 hPa | 700, 600, 500 hPa |

**Exit altitude (13,500 ft AGL ≈ 14,150 ft MSL) falls near the high-band ceiling.** Exit winds are sampled at 625 hPa (GFS) / 600 hPa (ECMWF), both ~14,000 ft MSL. Mid-cloud coverage is the primary concern — 100% mid clouds means exiting into a solid layer with no horizon reference and a blind deployment. Low clouds affect landing visibility.
