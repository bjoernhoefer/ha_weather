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
  | `geosphere` – GeoSphere Austria C-LAEF AlpeAdria 1 km (60 h) – **Vienna** | public, no registration |
  | `aemet` – AEMET OpenData municipality forecast – **Porto Cristo** | free registration (`HAW_AEMET_API_KEY`) |

  Regional sources only run for the locations they cover: `geosphere` for
  locations inside its Alpine model domain, `aemet` for locations with an
  `aemet_municipality` code. Other locations don't list them in the ranking.

* **Source control** – every source can be switched on/off globally in the web
  UI, and additional keyless sources (any Open-Meteo weather model) can be
  added and removed at runtime, see [Source control](#source-control).
* **Garden & energy indicators** – evapotranspiration (ET0), water balance,
  a `watering_recommended` hint, sunshine hours, solar radiation and soil
  moisture per day (Open-Meteo, no key), see
  [docs/home-assistant.md](docs/home-assistant.md#garden-and-energy-sensors).
* **Weighted consensus forecast** – accurate providers count more; the next 24
  hours are available hourly, the following 48 hours in 4-hour intervals, and
  days 3–7 as daily values. The forecast cache refreshes hourly by default.
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
docker compose up -d
```

Open <http://localhost:8080/> for the web UI or
<http://localhost:8080/docs> for the OpenAPI documentation.
The **Help** link in the page header explains the controls and shows the
version history.

### Versioning

The current version and its history are kept in
[`app/static/version.json`](app/static/version.json). The help page reads this
file, and FastAPI uses its `version` field for the OpenAPI metadata. This is
version **1.0**. For each subsequent change, propose a new version number and
a one- or two-sentence release description in the pull request. When releasing,
set `version` to the proposed number and prepend a matching dated entry to
`history` (newest first). Use a minor version for new functionality and a
patch version for fixes.

The Compose file pulls the published image from GHCR. For local changes, build
it yourself with `docker build -t ghcr.io/bjoernhoefer/ha_weather:latest .`
before running `docker compose up -d`.

### Automatic Docker updates

After CI succeeds on `main`, GitHub Actions publishes `linux/amd64` and
`linux/arm64` images as `ghcr.io/bjoernhoefer/ha_weather:latest` and a
commit-specific tag. The first package must be made **public** in GitHub's
package settings (packages are private by default) so hosts can pull it
without registry credentials. The server at `192.168.188.13` uses
`docker-compose.host.yml`, which retains port 6070 and the persistent
`ha_weather_data` volume. Its existing Watchtower checks for new images daily
at 04:00 and restarts the container when `latest` changes. Deploy the first
image with `docker compose -f docker-compose.host.yml pull ha_weather` and
`docker compose -f docker-compose.host.yml up -d --no-deps ha_weather`; no
checkout or rebuild is needed for subsequent releases.

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
| `HAW_LOCATIONS` | Vienna + Porto Cristo | JSON list of `{id,name,latitude,longitude,timezone,aemet_municipality}` (`aemet_municipality` = 5 digit INE code, optional, Spain only) |
| `HAW_FORECAST_DAYS` | `7` | forecast horizon |
| `HAW_CACHE_TTL_SECONDS` | `3600` | age at which a cached forecast is refetched |
| `HAW_WATERING_DEFICIT_MM` | `5` | `watering_recommended` turns on when rain − ET0 over 3 days is below −this value |
| `HAW_DATABASE_PATH` | `data/ha_weather.sqlite3` | forecast/observation archive |
| `HAW_OPENWEATHERMAP_API_KEY` | – | enables the OpenWeatherMap provider |
| `HAW_WEATHERAPI_API_KEY` | – | enables the WeatherAPI.com provider |
| `HAW_AEMET_API_KEY` | – | enables the AEMET provider (<https://opendata.aemet.es/centrodedescargas/altaUsuario>) |
| `HAW_AZURE_FOUNDRY_*` | – | Azure AI Foundry verification, see the docs |
| `HAW_OBSERVATION_SOURCES` | `open_meteo` | comma separated list of enabled ground-truth observation sources, see [Ground truth observations](#ground-truth-observations) |
| `HAW_HOME_ASSISTANT_URL` / `HAW_HOME_ASSISTANT_TOKEN` | – | Home Assistant observation source |
| `HAW_HOME_ASSISTANT_INDOOR_ENTITIES` / `HAW_HOME_ASSISTANT_OUTDOOR_ENTITIES` | `{}` | JSON object: `location_id` → list of Home Assistant entity ids |
| `HAW_ELASTICSEARCH_URL` / `HAW_ELASTICSEARCH_API_KEY` / `HAW_ELASTICSEARCH_INDEX` | – | Elasticsearch observation source |
| `HAW_ELASTICSEARCH_LOCATION_FIELD` | `location_id` | term field used to select a location's documents |
| `HAW_ELASTICSEARCH_INDOOR_FIELDS` / `HAW_ELASTICSEARCH_OUTDOOR_FIELDS` | `{}` | JSON object: `location_id` → name of the temperature field |

Providers whose (free) API key is missing are simply skipped.

### Ground truth observations

Archived forecasts are compared against measured values to compute the
Top/Low list and the consensus weights (see
[Features](#features)). By default this ground truth comes from
Open-Meteo's `past_days` endpoint (`open_meteo`, public, no registration).
Two additional, pluggable sources can be enabled through
`HAW_OBSERVATION_SOURCES` (comma separated, e.g.
`open_meteo,home_assistant,elasticsearch`) and merged with Open-Meteo:

* **`home_assistant`** – reads sensor history through Home Assistant's REST
  `history/period` API using a
  [long-lived access token](https://www.home-assistant.io/docs/authentication/#your-account-profile)
  (`HAW_HOME_ASSISTANT_URL`, `HAW_HOME_ASSISTANT_TOKEN`). Map any number of
  numeric temperature sensors per location to `HAW_HOME_ASSISTANT_INDOOR_ENTITIES`
  and `HAW_HOME_ASSISTANT_OUTDOOR_ENTITIES` (JSON object of
  `location_id -> [entity_id, ...]`); each day's minimum/maximum sensor state
  becomes one observation.
* **`elasticsearch`** – aggregates a numeric temperature field per day (daily
  `date_histogram` with `min`/`max` sub-aggregations) from any Elasticsearch
  index, including the free Elastic Cloud tier. Configure `HAW_ELASTICSEARCH_URL`,
  `HAW_ELASTICSEARCH_API_KEY` (sent as `ApiKey <key>`) and
  `HAW_ELASTICSEARCH_INDEX`, then map the indoor/outdoor temperature field name
  per location in `HAW_ELASTICSEARCH_INDOOR_FIELDS`/`HAW_ELASTICSEARCH_OUTDOOR_FIELDS`
  (JSON object of `location_id -> field_name`). Documents are matched to a
  location through `HAW_ELASTICSEARCH_LOCATION_FIELD` (a term filter, default
  `location_id`) and must have a `@timestamp` field.

When more than one source reports the same day/scope, temperature and
precipitation fields are merged (a source's `None`/missing value never
overwrites a value already saved by another source), but when two sources
both report a value for the same field, the **last** source fetched wins –
sources are queried in the order listed in `HAW_OBSERVATION_SOURCES`, so
later entries take precedence over earlier ones for conflicting fields.
`source` itself always reflects every contributing source (e.g.
`home_assistant+open_meteo`).

Indoor and outdoor readings are tracked separately (`Observation.scope`):
only **outdoor** observations are used to score the weather providers, since
indoor sensors are not comparable with an outdoor weather forecast. Indoor
observations are archived alongside them for future home-comfort features. A
failing observation source is logged and skipped - it never blocks the
others or the forecast refresh.

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
| `PUT /api/sources/{name}/api-key` | set/replace the API key of a source `{"api_key": "..."}` – the key is never returned |
| `DELETE /api/sources/{name}/api-key` | remove the key set in the UI (the environment key applies again) |
| `GET /api/forecast/{location}` | consensus (`hourly`, `four_hourly`, `days`) + per provider forecast, ranking and season |
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
| GeoSphere Austria (dataset.api.hub.geosphere.at) | no | **added** as `geosphere` (Vienna) |
| Bright Sky (DWD MOSMIX/observations) | no | candidate – Germany centric, see *German sources* below |
| wttr.in | no | not added – only 3 days, rate limited, no stable SLA |
| 7Timer! | no | not added – coarse resolution, no daily precipitation totals |
| US National Weather Service (api.weather.gov) | no | not applicable – US locations only |
| AEMET OpenData (Spain) | free key | **added** as `aemet` (Porto Cristo) |
| Meteo de les Illes (meteodelesilles.com, Instagram) | – | not usable automatically, see below |
| Tomorrow.io, Visual Crossing, Pirate Weather, Meteoblue, AccuWeather | free key | possible future providers, require registration |
| `openweathermap`, `weatherapi` | free key | already supported |

### API keys in the web UI

Sources that need a key (`aemet`, `openweathermap`, `weatherapi`) have a key
field in the **Source control** table, so a key can be added or replaced
without a restart:

* A key entered in the UI overrides the environment variable. *Remove key*
  deletes it and the environment variable applies again.
* The key column shows only where the key comes from (`set in web UI`,
  `from environment` or `missing`). The API never returns a key.
* UI keys are stored in plain text in the SQLite database
  (`HAW_DATABASE_PATH`). Protect the data volume. In `local` mode everyone in
  the subnet can *replace* keys (but not read them), so use `public` mode if
  that's a concern.

### AEMET (Porto Cristo)

* Enter the key in the web UI (**Source control → API key → Save key**) or
  set `HAW_AEMET_API_KEY`. The key is sent as `api_key` header, never in the URL.
* Porto Cristo belongs to the municipality of **Manacor**, INE code `07033`
  (preconfigured). Other Spanish locations need their own
  `aemet_municipality` in `HAW_LOCATIONS`.
* Temperatures, wind and sky state come from the daily forecast (7 days).
  AEMET publishes daily precipitation only as a *probability*, so the amount
  in mm is summed from the hourly forecast and is only reported for fully
  covered days (usually the next 1–2 days).
* Datasets used: `prediccion/especifica/municipio/diaria/{municipality}` and
  `prediccion/especifica/municipio/horaria/{municipality}`.

### GeoSphere Austria (Vienna)

* Uses the `timeseries/forecast/nwp-v2-1h-1km` dataset with the parameters
  `2t` (temperature), `rain`, `sf` (snowfall), `10u`/`10v` (wind) and `tcc`
  (cloud cover). The model is C-LAEF AlpeAdria (1 km, hourly, runs every
  3 h). The older `nwp-v1-1h-2500m` dataset is shut down by GeoSphere on
  4 Nov 2026 and therefore not used.
* The model runs only 60 h ahead, so GeoSphere contributes to the next ~2
  complete local days. Incomplete days are left out so that min/max values
  are not skewed.
* Data source: GeoSphere Austria – <https://data.hub.geosphere.at> (CC BY 4.0).
  The API allows about 240 requests per hour, far more than one refresh per
  `HAW_CACHE_TTL_SECONDS` needs.

### Meteo de les Illes

[meteodelesilles.com](https://www.meteodelesilles.com/) publishes very good
hand-written forecasts for the Balearic Islands, mainly as text and images on
Instagram. It can't be added as a source:

* There is no public API or machine-readable feed. Scraping the website or
  Instagram would be fragile and breaks Instagram's terms of use, and the
  forecasts are their copyrighted work.
* The forecasts are text for the whole island, so there are no numbers per
  location to score against observations.

If you'd like to use it anyway, ask Meteo de les Illes for permission and
for a feed (e.g. JSON/RSS). A small provider could then be written. Until
then, it works best as a manual cross-check: when they predict something
different, use the manual rank/enable switches in the web UI.

### German sources

| Source | API key | Usefulness for Vienna / Porto Cristo |
| --- | --- | --- |
| DWD ICON, ICON-EU, ICON-D2 (Open-Meteo) | no | already there: `dwd_icon` built-in; `icon_eu`/`icon_d2` as custom sources (ICON-D2 covers Vienna, not Mallorca) |
| DWD ICON-EPS ensemble (Open-Meteo ensemble API) | no | promising – spread of ensemble members = forecast uncertainty; would need a new "uncertainty" field |
| DWD MOSMIX (opendata.dwd.de) | no | **most promising** – statistically corrected point forecasts for ~5,400 stations worldwide, up to 10 days, including Wien Hohe Warte (`11035`) and Palma de Mallorca (`08306`). Needs a KMZ/XML parser and a station id per location |
| Bright Sky (api.brightsky.dev) | no | JSON wrapper around DWD MOSMIX/observations; mainly aimed at Germany, check station coverage before using it |
| DWD warnings (CAP) | no | Germany only – not relevant |
| Kachelmannwetter, wetter.com, Meteomatics | commercial / trial key | good quality, but paid for regular use |

Recommendation: DWD MOSMIX would be the next step. It adds a
station-based, statistically corrected forecast for both locations.

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
