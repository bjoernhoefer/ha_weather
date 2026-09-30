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
  | `openweathermap` – OpenWeatherMap 5 day | free registration (`HAW_OPENWEATHERMAP_API_KEY`) |
  | `weatherapi` – WeatherAPI.com | free registration (`HAW_WEATHERAPI_API_KEY`) |

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
