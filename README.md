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
  a manual rank or disabling a provider per location. The page is organised in
  foldable sections: *Forecast* (next 24 hours open; history of the last 24
  hours with prediction accuracy, next 48 hours and days 3–7 folded),
  *Seasons*, *Providers*, *Source control*, *Real world measurements* and
  *General settings* (add/remove locations, API key).
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
version **1.1**. For each subsequent change, propose a new version number and
a one- or two-sentence release description in the pull request. When releasing,
set `version` to the proposed number and prepend a matching dated entry to
`history` (newest first). Use a minor version for new functionality and a
patch version for fixes.

The Compose file pulls the published image from GHCR. For local changes, build
it yourself with `docker build -t ghcr.io/bjoernhoefer/ha_weather:latest .`
before running `docker compose up -d`.

### Continuous deployment rollout

After CI succeeds for a push to `main`, GitHub Actions publishes `linux/amd64` and
`linux/arm64` images as `ghcr.io/bjoernhoefer/ha_weather:latest` and a
commit-specific tag, then passes the immutable image digest to the deploy job.
The first package must be made **public** in GitHub's
package settings (packages are private by default) so hosts can pull it
without registry credentials.

The deploy job runs on the Raspberry Pi at `192.168.188.13` (Debian 12,
ARM64), using a self-hosted runner with labels `self-hosted`, `linux`,
`ARM64`, and `deploy-weather`. Only successful CI runs for pushes to `main`
can deploy; PRs and forks cannot. Fork PR workflows require manual approval
before running; configure GitHub Actions to require approval for all outside
collaborators. The host job does not check out the repository or run
third-party actions.

Before deployment, the job checks the current `main` SHA with `git ls-remote`
and skips builds that have been superseded. Deployments are serialized in
the `deploy-ha_weather` concurrency group without cancelling an active
deployment, with a 20-minute job timeout. After validating the digest and
commit SHA, the runner calls:

```bash
sudo -n -u bjoern /usr/local/bin/ha-deploy ha_weather "ghcr.io/bjoernhoefer/ha_weather@${DIGEST}" "${HEAD_SHA}"
```

The runner runs as the dedicated user `gh-deploy`, with no Docker access
and permission to invoke only `ha-deploy` via sudo as `bjoern`.
Host setup (runner registration, sudo policy, and the root-owned deployment
script) is performed separately from this repository rollout.

The host script uses a host-wide `flock` lock, pulls the digest-pinned image
and tags it locally as `:latest`. It runs
`docker compose -p ha_weather -f docker-compose.host.yml up -d --no-build --pull never --wait ha_weather`
for only this service, waiting for its healthcheck. If that fails, it rolls
back to the previous image and exits nonzero so the deployment is marked
failed. The Compose project remains `ha_weather`, retaining port 6070 and
the persistent `ha_weather_data` volume.

Both Compose files disable Watchtower updates for `ha_weather` using
`com.centurylinklabs.watchtower.enable=false`. The host's existing Watchtower
runs without a label filter and would otherwise race with GitHub Actions
deployments. Install the updated host Compose file and the deployment script,
and bring the runner online before enabling the rollout; subsequent releases
need no checkout or rebuild on the host.

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
| `HAW_OBSERVATION_SOURCES` | `open_meteo` | comma separated list of enabled real-world observation sources, see [Real world measurements](#real-world-measurements) |
| `HAW_HOME_ASSISTANT_URL` / `HAW_HOME_ASSISTANT_TOKEN` | – | a single Home Assistant instance (shown as the read-only instance `environment`) |
| `HAW_HOME_ASSISTANT_INDOOR_ENTITIES` / `HAW_HOME_ASSISTANT_OUTDOOR_ENTITIES` | `{}` | JSON object: `location_id` → list of entity ids of the `environment` instance |
| `HAW_HOME_ASSISTANT_INSTANCES` | `[]` | JSON list of further instances: `[{"id": "garden", "name": "Garden", "url": "http://ha.local:8123", "token": "..."}]` |
| `HAW_HOME_ASSISTANT_MEASUREMENTS` | `[]` | JSON list of measurements: `[{"instance_id": "garden", "location_id": "vienna", "entity_id": "sensor.outdoor", "scope": "outdoor"}]` |
| `HAW_ELASTICSEARCH_URL` / `HAW_ELASTICSEARCH_API_KEY` / `HAW_ELASTICSEARCH_INDEX` | – | a single Elasticsearch instance (shown as the read-only instance `environment`) |
| `HAW_ELASTICSEARCH_LOCATION_FIELD` | `location_id` | term field used to select a location's documents in the `environment` instance |
| `HAW_ELASTICSEARCH_INDOOR_FIELDS` / `HAW_ELASTICSEARCH_OUTDOOR_FIELDS` | `{}` | JSON object: `location_id` → name of the temperature field of the `environment` instance |
| `HAW_ELASTICSEARCH_INSTANCES` | `[]` | JSON list of further instances: `[{"id": "cloud", "name": "Elastic Cloud", "url": "https://...", "api_key": "...", "index": "weather", "location_field": "location_id"}]` |
| `HAW_ELASTICSEARCH_MEASUREMENTS` | `[]` | JSON list of field mappings: `[{"instance_id": "cloud", "location_id": "vienna", "field": "outdoor_temp", "scope": "outdoor"}]` |

Providers whose (free) API key is missing are simply skipped.

### Real world measurements

(Formerly *Ground truth observations*.) Archived forecasts are compared against measured values to compute the
Top/Low list and the consensus weights (see
[Features](#features)). By default this ground truth comes from
Open-Meteo's `past_days` endpoint (`open_meteo`, public, no registration).
Two additional, pluggable sources can be enabled through
`HAW_OBSERVATION_SOURCES` (comma separated, e.g.
`open_meteo,home_assistant,elasticsearch`) and merged with Open-Meteo:

* **`home_assistant`** – reads sensor history through Home Assistant's REST
  `history/period` API using a
  [long-lived access token](https://www.home-assistant.io/docs/authentication/#your-account-profile)
  per instance. Any number of Home Assistant instances can be added in the
  web UI (**Real world measurements → Home Assistant instances**) or through
  `HAW_HOME_ASSISTANT_INSTANCES`; the classic `HAW_HOME_ASSISTANT_URL` /
  `HAW_HOME_ASSISTANT_TOKEN` pair stays supported as the read-only instance
  `environment`. Each **measurement** couples one numeric temperature entity
  of an instance with a location and a scope (indoor/outdoor); maintain the
  list in the UI (add, edit, delete) or via `HAW_HOME_ASSISTANT_MEASUREMENTS`.
  Each day's minimum/maximum sensor state becomes one observation; adding a
  measurement in the UI enables the `home_assistant` source automatically.
  Tokens are stored in the database and never returned by the API. Deleting
  an instance or location also deletes its measurements. Previously saved
  single-instance UI settings are migrated to an instance named
  *Home Assistant*.
* **`elasticsearch`** – aggregates a numeric temperature field per day (daily
  `date_histogram` with `min`/`max` sub-aggregations) from any Elasticsearch
  index, including the free Elastic Cloud tier. Like Home Assistant, any
  number of **instances** can be added in the web UI (**Real world
  measurements → Elasticsearch instances**: name, URL, API key - sent as
  `ApiKey <key>` -, index and location field) or through
  `HAW_ELASTICSEARCH_INSTANCES`; the classic `HAW_ELASTICSEARCH_URL` /
  `_API_KEY` / `_INDEX` / `_LOCATION_FIELD` variables stay supported as the
  read-only instance `environment` (with `HAW_ELASTICSEARCH_INDOOR_FIELDS` /
  `HAW_ELASTICSEARCH_OUTDOOR_FIELDS` as its field mappings). Each **field**
  entry couples a numeric temperature field of an instance with a location
  and a scope (indoor/outdoor); maintain the list in the UI or via
  `HAW_ELASTICSEARCH_MEASUREMENTS`. Documents are matched to a location
  through the instance's location field (a term filter on the location id,
  default `location_id`) and must have a `@timestamp` field. Several fields of
  the same location/scope are combined per day (lowest minimum, highest
  maximum); a failing instance is logged and skipped. Adding a field in the
  UI enables the `elasticsearch` source automatically, deleting an instance or
  location deletes its fields, and a previously saved single UI configuration
  is migrated to an instance named *Elasticsearch*.

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
| `GET /api/locations` | configured locations (environment + added in the UI, `custom: true`) |
| `POST /api/locations` | add a location `{"name": "Graz", "latitude": 47.07, "longitude": 15.44}` – without coordinates the name is geocoded via Open-Meteo |
| `DELETE /api/locations/{location}` | remove a location added in the UI (environment locations are read-only) |
| `GET /api/observation-sources` | real world measurement sources, Home Assistant instances and measurements |
| `POST /api/observation-sources/home-assistant/instances` | add a Home Assistant instance `{"name": "Garden", "url": "http://ha.local:8123", "token": "..."}` |
| `PUT /api/observation-sources/home-assistant/instances/{id}` | update name/URL; an empty token keeps the stored one |
| `DELETE /api/observation-sources/home-assistant/instances/{id}` | remove an instance and its measurements |
| `POST /api/observation-sources/home-assistant/measurements` | add a measurement `{"instance_id": "garden", "location_id": "vienna", "entity_id": "sensor.outdoor", "scope": "outdoor", "name": ""}` |
| `PUT /api/observation-sources/home-assistant/measurements/{id}` | update a measurement |
| `DELETE /api/observation-sources/home-assistant/measurements/{id}` | remove a measurement |
| `POST /api/observation-sources/elasticsearch/instances` | add an Elasticsearch instance `{"name": "Elastic Cloud", "url": "https://...", "api_key": "...", "index": "weather", "location_field": "location_id"}` |
| `PUT /api/observation-sources/elasticsearch/instances/{id}` | update an instance; an empty API key keeps the stored one |
| `DELETE /api/observation-sources/elasticsearch/instances/{id}` | remove an instance and its fields |
| `POST /api/observation-sources/elasticsearch/measurements` | add a field mapping `{"instance_id": "elastic_cloud", "location_id": "vienna", "field": "outdoor_temp", "scope": "outdoor", "name": ""}` |
| `PUT /api/observation-sources/elasticsearch/measurements/{id}` | update a field mapping |
| `DELETE /api/observation-sources/elasticsearch/measurements/{id}` | remove a field mapping |
| `GET /api/history/{location}` | last 24 hours: archived hourly prediction vs. measured values, MAE and bias |
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

In the web UI enter the key under **General settings → API key**; it is
stored in the browser and the section opens automatically when a request is
rejected with 401.

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
