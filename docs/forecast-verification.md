# Live forecast verification

The Top/Low ranking only judges a forecast after the day is over. By then the
garden watering or the heating has already been adjusted. The live check
compares the **hour by hour** forecast with what is happening *right now* and
raises a `forecast_failure` flag when the forecast is clearly wrong.

```
GET  /api/live-check/{location_id}   # assessment + impact per consumer
POST /api/readings/{location_id}     # Home Assistant pushes sensor readings
GET  /api/failures/{location_id}     # stored failure events (newest first)
```

## Sources

| Source | What it tells | Limits |
| --- | --- | --- |
| Hourly forecast | temperature, rain, cloud cover, weather code, CAPE (storm energy) of the Open-Meteo based providers, weighted like the daily consensus and archived per run | – |
| EUMETSAT (cloud mask, lightning) | cloud / clear around the location every 15 min, lightning flashes every 5 min | ~15 min publication delay, fog/low cloud can be misread |
| ha_satellite | any cloud reading your own satellite service produces | visible-light images are useless at night |
| Thermometer (Home Assistant) | the real temperature | sensor position (sun, wall) skews readings → a running offset is learned |
| Rain gauge (Home Assistant, optional) | the only direct proof of rain | – |

Evidence rules: a clear sky confirmed by several readings in a row is strong
evidence against predicted rain or thunderstorms, clouds alone are only weak
evidence for rain, a rain gauge always wins.

### EUMETSAT data

EUMETSAT offers far more than images. What is useful for a point check:

| Product | Access | Used |
| --- | --- | --- |
| Cloud Mask (`msg_fes:clm`, MSG, 15 min, infrared based → day **and** night) | EUMETView WMS `GetFeatureInfo` | ✅ cloud cover from 5 points (location + 4 points `HAW_EUMETSAT_SAMPLE_OFFSET_DEG` away) |
| Lightning Imager accumulated flash area (`mtg_fd:li_afa`, MTG, 5 min) | EUMETView WMS `GetFeatureInfo` | ✅ `convective` flag |
| Cloud Top Height (`msg_fes:cth`), Cloud Type (`mtg_fd:rgb_cloudtype`), H SAF precipitation rate layers | EUMETView WMS | not yet (colour scales without calibrated legend) |
| Full resolution Level 2 products, e.g. FCI Cloud Mask `EO:EUM:DAT:0678`, LI flashes/groups, Optimal Cloud Analysis, Global Instability Indices, MPE precipitation | Data Store API (`api.eumetsat.int`, OAuth2 with your consumer key/secret) | not used: full disk NetCDF files of hundreds of MB – too heavy for a check every few minutes |

`GetFeatureInfo` returns the pixel value (or the rendered legend colour) at a
coordinate, so no image processing is needed. The public layers work without
registration; when `HAW_EUMETSAT_CONSUMER_KEY`/`_SECRET` are set an OAuth2
token (`https://api.eumetsat.int/token`, client credentials) is fetched,
cached and sent as a bearer token in the `Authorization` header – needed for restricted layers.
Every product scene is queried only once (`HAW_EUMETSAT_INTERVAL_MINUTES`) and
stamped with the scene time (`now − HAW_EUMETSAT_LAG_MINUTES`, snapped to the
product grid).

### ha_satellite contract

Set `HAW_SATELLITE_URL` (e.g. `http://ha-satellite:8080/api/clouds/{location_id}`,
`{latitude}`/`{longitude}` are also replaced) and optionally
`HAW_SATELLITE_API_KEY` (sent as `X-API-Key`). The endpoint returns a list,
`{"readings": [...]}` or a single object:

```json
{"readings": [{
  "observed_at": "2026-06-15T11:45:00Z",
  "cloud_cover": 85,
  "convective": false,
  "cloud_top_temperature": -52.0,
  "channel": "infrared"
}]}
```

`cloud_fraction` (0..1) may replace `cloud_cover` (percent), `time`/`timestamp`
may replace `observed_at`, `lightning` may replace `convective`, cloud top
temperatures above 100 are treated as Kelvin. `channel` is `infrared` or
`visible` (`ir108`, `vis006`, `hrv`, `rgb` … are mapped) – visible readings are
ignored at night. Readings can also be pushed through `POST /api/readings`.

## Classification

The window covers the last `HAW_LIVE_CHECK_PAST_HOURS` (3) and the next
`HAW_LIVE_CHECK_AHEAD_HOURS` (3) hours. For every hour the forecast that was
valid **at that time** is used, so a later correction of the providers does
not hide a wrong forecast.

| `failure_type` | When | `failure_level` |
| --- | --- | --- |
| `ok` | observations match | none (0) |
| `delayed` | predicted rain has not arrived but clouds are building / it is cloudy but still dry / rain still ahead; or the rain came earlier than forecast | low (1) |
| `unexpected` | clear sky predicted but clouds are coming up or it rains | medium (2) |
| `unexpected` | clear sky predicted but thunderstorm clouds / lightning | high (3) |
| `missed` | rain predicted, sky stays clear (or gauge stays dry) | medium (2) |
| `missed` | thunderstorm predicted (condition or CAPE ≥ 1000 J/kg), sky stays clear | high (3) |
| `temperature_drift` | corrected thermometer ≥ 3 K / 5 K / 8 K off the forecast in all recent readings | low / medium / high |

* A failure needs `HAW_LIVE_CHECK_CONFIRMATIONS` (3) readings in a row.
  Thunderstorms are short lived, so 2 convective readings (lightning or
  cloud tops below −40 °C) among those last readings are enough.
* A raised failure is kept for `HAW_LIVE_CHECK_HOLD_MINUTES` (120) after it was
  last seen (`held: true`) so the flag does not flap on a single cloud.
* `confidence` (0..1) drops when the satellite or thermometer is missing or
  older than `HAW_LIVE_CHECK_STALE_MINUTES` (60), or when only visible-light
  images are available at night.
* The thermometer offset is the median of `sensor − forecast` over the last
  7 days (at least 6 samples, clamped to ±6 K).

Every raised failure is stored in the `failure_events` table (one row per
episode, `last_seen_at` is updated while it lasts).

## Impact per consumer

The failure level says *how wrong* the forecast is, the impact says *how much
it hurts* the decisions that depend on it:

```
score = adjustment × severity × (1 − 0.5 × coverage)   # harmful direction
score = 0                                             # safe direction
impact = high ≥ 0.66 > medium ≥ 0.33 > low
```

* `adjustment` – how much the forecast reduced the consumer (0..1). Home
  Assistant can report it (`adjustments` in the push, valid 24 h), otherwise it
  is estimated: `(forecast − baseline) / full_adjustment`.
* `severity` – `|expected − forecast| / full_error`.
* `coverage` – how much of the need is covered anyway (e.g. it still rained).
* The expected value is projected from the window: today's forecast rain ×
  (observed / predicted rain so far), today's mean temperature + temperature
  error.

| Example | Result |
| --- | --- |
| watering lowered for 10 mm rain, the day stays sunny | high |
| heating lowered for a warm 14 °C day, a winter storm brings −2 °C | high |
| heating lowered a little (6 °C), temperature stays as forecast | low |
| watering lowered for 20 mm heavy rain, 8 mm normal rain falls | medium |
| more rain / warmer than forecast (safe direction) | low |

Default profiles (override with `HAW_CONSUMERS`, JSON list):

```json
[
  {"name": "garden_watering", "driver": "precipitation", "payload_key": "watering_impact",
   "baseline": 0, "full_adjustment": 10, "full_error": 10,
   "reduces_when": "higher", "harmful_error": "less"},
  {"name": "heating", "driver": "temperature", "payload_key": "heating_impact",
   "baseline": 5, "full_adjustment": 10, "full_error": 8,
   "reduces_when": "higher", "harmful_error": "less"}
]
```

## Pushing readings from Home Assistant

```
POST /api/readings/vienna
{"temperature": 17.4, "precipitation_mm": 0.2,
 "adjustments": {"garden_watering": 0.8, "heating": 0.3}}
```

`observed_at` is optional (now), naive times are UTC. `precipitation_mm` is the
rain since the previous push, **not** the daily total. Batches use
`{"readings": [...], "satellite": [...]}`. See
[home-assistant.md](home-assistant.md) for the `rest_command` and automations.
