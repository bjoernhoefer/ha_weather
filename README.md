# ha_weather

Multi source weather prediction for **Home Assistant** – used to alter
garden watering, heating or cooling. It predicts the weather for
**Vienna** and **Porto Cristo** (any other location can be configured),
verifies how accurate every source actually was and exposes a
**Top/Low provider list** plus **meteorological season sensors**.

## Features

* **Several prediction sources** – queried in parallel, one failing source never
  breaks the result:

  | Provider | Access |
  | --- | --- |
  | `open_meteo` – Open-Meteo best match blend | public, no registration |
  | `dwd_icon` – DWD ICON via Open-Meteo | public, no registration |
  | `noaa_gfs` – NOAA GFS via Open-Meteo | public, no registration |
  | `met_no` – MET Norway Locationforecast 2.0 | public, no registration |
  | `ecmwf_ifs` – ECMWF IFS 0.25° via Open-Meteo | public, no registration |
  | `meteofrance` – Météo-France ARPEGE/AROME via Open-Meteo | public, no registration |
  | `ukmo` – UK Met Office Unified Model via Open-Meteo | public, no registration |
  | `gem` – Environment Canada GEM via Open-Meteo | public, no registration |
  | `openweathermap` – OpenWeatherMap 5 day | free registration (`HAW_OPENWEATHERMAP_API_KEY`) |
  | `weatherapi` – WeatherAPI.com | free registration (`HAW_WEATHERAPI_API_KEY`) |

* **Source control** – every source can be switched on/off globally in the web
  UI, and additional keyless sources (any Open-Meteo weather model) can be
  added and removed at runtime, see [Source control](#source-control).
* **Weighted consensus forecast** – accurate providers count more.
* **Accuracy verification** – every forecast is archived in SQLite and compared
  with the measured values of the following days (mean absolute error for
  temperature and precipitation) which produces the **Top/Low list**.
* **Azure AI Foundry review** – the accuracy statistics are additionally weighted
  by an LLM deployment, see [docs/azure-foundry.md](docs/azure-foundry.md).
* **Manually alterable ranking** – a small web UI (served at `/`) allows setting
  a manual rank or disabling a provider per location.
* **Meteorological point of view** – season change detection
  (`weather_season`, `weather_season_from`, `weather_season_to`,
  `weather_seasonal_change`) plus regime changes such as a pronounced cool down
  or a much wetter pattern (`upcoming_weather_change`).
* **Docker runtime** – anonymous in a local subnet, API key protected when
  published (e.g. Azure Container Instances).

## Quick start

```bash
cp .env.example .env          # optional: add API keys
docker compose up --build
```

Open <http://localhost:8080/> for the web UI or
<http://localhost:8080/docs> for the OpenAPI documentation.

Without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8080
```

## Configuration

All settings are environment variables prefixed with `HAW_`
(see [.env.example](.env.example)).

| Variable | Default | Meaning |
| --- | --- | --- |
| `HAW_DEPLOYMENT_MODE` | `local` | `local` = anonymous (private subnet), `public` = API key required for **every** request |
| `HAW_API_KEYS` | – | comma separated keys, mandatory in `public` mode |
| `HAW_LOCATIONS` | Vienna + Porto Cristo | JSON list of `{id,name,latitude,longitude,timezone}` |
| `HAW_FORECAST_DAYS` | `7` | forecast horizon |
| `HAW_CACHE_TTL_SECONDS` | `1800` | age at which a cached forecast is refetched |
| `HAW_DATABASE_PATH` | `data/ha_weather.sqlite3` | forecast/observation archive |
| `HAW_OPENWEATHERMAP_API_KEY` | – | enables the OpenWeatherMap provider |
| `HAW_WEATHERAPI_API_KEY` | – | enables the WeatherAPI.com provider |
| `HAW_AZURE_FOUNDRY_*` | – | Azure AI Foundry verification, see the docs |

Providers whose (free) API key is missing are simply skipped.

## API

| Method & path | Description |
| --- | --- |
| `GET /health` | liveness probe, never authenticated |
| `GET /api/locations` | configured locations |
| `GET /api/providers` | registered providers and their availability |
| `GET /api/sources` | source control: all built-in and custom sources with their state |
| `GET /api/sources/catalog` | suggested keyless Open-Meteo models for custom sources |
| `POST /api/sources` | add a custom source `{"name": "icon_d2", "model": "icon_d2", "description": ""}` |
| `PUT /api/sources/{name}` | switch a source on/off for all locations `{"enabled": false}` |
| `DELETE /api/sources/{name}` | remove a custom source (built-in sources can only be disabled) |
| `GET /api/forecast/{location}` | consensus + per provider forecast, ranking and season |
| `POST /api/forecast/{location}/refresh` | force a new query of all providers |
| `GET /api/ranking/{location}` | Top/Low provider list |
| `PUT /api/ranking/{location}/{provider}` | manual override `{"manual_rank": 1, "enabled": true}` |
| `DELETE /api/ranking/{location}/{provider}` | remove the manual override |
| `GET /api/season/{location}` | meteorological season sensors |
| `POST /api/verify/{location}` | Azure AI Foundry assessment of the accuracy |
| `GET /api/homeassistant/{location}` | flat payload for the Home Assistant REST sensors |

In `public` mode send the key as `X-API-Key: <key>` or
`Authorization: Bearer <key>`.

## Source control

The **Source control** section of the web UI lists every weather source with
its type (built-in/custom), API key state and a global *Enabled* switch.
Disabled sources are not queried at all and disappear from the consensus and
the Top/Low list (their archived forecasts are kept). The switches are stored
in the SQLite database and survive restarts.

New sources that need **no API key** can be added as custom sources: pick an
id and an [Open-Meteo weather model](https://open-meteo.com/en/docs) (the UI
suggests the models from `GET /api/sources/catalog`, e.g. `icon_d2`,
`meteofrance_arome_france_hd`, `knmi_seamless`, `italia_meteo_arpae_icon_2i`).
For security reasons only the model name is user controlled – requests always
go to `api.open-meteo.com`, arbitrary URLs cannot be configured.

### Evaluated sources

| Source | API key | Status |
| --- | --- | --- |
| ECMWF IFS, Météo-France, UK Met Office, Environment Canada GEM (Open-Meteo) | no | **added** as built-in providers |
| Further Open-Meteo models (ICON-D2/EU, AROME HD, KNMI, DMI, JMA, MET Nordic, ItaliaMeteo ICON-2I, MeteoSwiss ICON-CH2, CMA, BoM, ECMWF AIFS, …) | no | available as **custom sources** via the source control |
| GeoSphere Austria (dataset.api.hub.geosphere.at) | no | candidate – very good for Vienna, needs an own parser (hourly NWP time series) |
| Bright Sky (DWD MOSMIX/observations) | no | candidate – Germany centric, little value for Vienna/Porto Cristo |
| wttr.in | no | not added – only 3 days, rate limited, no stable SLA |
| 7Timer! | no | not added – coarse resolution, no daily precipitation totals |
| US National Weather Service (api.weather.gov) | no | not applicable – US locations only |
| AEMET OpenData (Spain) | free key | candidate for Porto Cristo, requires registration |
| Tomorrow.io, Visual Crossing, Pirate Weather, Meteoblue, AccuWeather | free key | possible future providers, require registration |
| `openweathermap`, `weatherapi` | free key | already supported |

## Home Assistant

Ready to copy `configuration.yaml` snippets (including the
`upcoming_weather_change` / `weather_seasonal_change` binary sensors) are in
[docs/home-assistant.md](docs/home-assistant.md).

## How the Top/Low list is built

1. Every provider forecast is archived with its issue date.
2. Once a forecast day is over, the measured values (Open-Meteo, past days) are
   stored as observations.
3. The mean absolute error over the last 30 days is turned into a score:
   `100 − 8 × temperature MAE − 4 × precipitation MAE`, clamped to `0…100`.
4. Providers are ordered by manual rank first, then by score; the better half
   becomes **Top**, the rest (and everything disabled) becomes **Low**.
5. The score is also the weight of the provider in the consensus forecast.

## Tests

All tests run offline (the HTTP calls are mocked) and are executed by GitHub
Actions for every pull request before merging.

```bash
pytest -q
```
