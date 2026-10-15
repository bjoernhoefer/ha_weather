# Research: Hourly Source Comparison

## Decisions

### Keep provider forecast values separate

- **Decision**: Archive hourly temperature forecasts per provider, location, and UTC target hour during forecast refresh. Preserve the first stored forecast for each provider/hour and retain rows for up to 72 hours.
- **Rationale**: `ProviderForecast.hours` already holds source-specific values, while `hourly_predictions` stores only the weighted consensus. Provider identity cannot be recovered from consensus data.
- **Alternatives considered**: Reuse consensus history (incorrect attribution); overwrite the first forecast on every refresh (changes lead-time behavior); backfill old history (impossible without inventing provider identity).

### Keep each HA outdoor sensor independent

- **Decision**: Store hourly observations by location, UTC target hour, and stable `(instance_id, entity_id)` source key. Fetch each configured outdoor sensor independently and preserve its display name alongside the identity.
- **Rationale**: Existing observations merge source values per day, and the current hourly helper combines all outdoor entities. Either behavior would conceal which sensor supplied a reading.
- **Alternatives considered**: Reuse merged daily observations (wrong temporal granularity); average sensors together (loses pairwise comparison); use display names as keys (names can change).

### Use bounded time selection and explicit temperature categories

- **Decision**: Support 24, 48, and 72-hour windows; show a matrix for the selected hour and detailed rows for the selected window. Display signed and absolute error separately. Label absolute errors `Good` through 1 °C, `Check` over 1 °C through 2 °C, and `Large` over 2 °C.
- **Rationale**: This meets the requested source matrix and auditable hourly comparison while staying within the existing three-day hourly retention. Temperature is the only measurement available for every configured Home Assistant sensor.
- **Alternatives considered**: Combine temperature and precipitation into one score (incompatible units); use only a generic red/green heatmap (not sufficiently descriptive or accessible); add precipitation comparison (no configured per-source rain readings exist).

### Preserve previous contracts and canonicalize time

- **Decision**: Add a distinct protected comparison endpoint and additive tables. Normalize timestamps to UTC for joins and use the configured location timezone for display, including its timezone name.
- **Rationale**: Existing `/api/history/{location_id}` must continue comparing the consensus forecast with its current measured values. Provider adapters may return timezone-aware or naive local hour stamps; canonical UTC keys prevent false mismatches across offsets and daylight-saving changes.
- **Alternatives considered**: Change the existing history payload (breaks clients); use browser-local time for matching (host dependent); attribute legacy consensus forecasts (not supportable).

## Repository Evidence

- Provider forecasts already contain separate hourly values: `app/models.py:24-42`.
- Refresh currently archives only aggregated hours: `app/service.py:961-969`.
- The existing consensus archive retains three days and is keyed only by location and target hour: `app/storage.py:28-29,121-129,828-895`.
- Configured HA measurements include instance, entity, location, scope, and display name: `app/config.py:44-54`.
- HA hourly history computes per-hour means, but `fetch_hourly` combines outdoor history: `app/obs_sources/home_assistant.py:272-317,434-459`.
- Existing history endpoint and response are a separate consensus comparison: `app/main.py:521-529`, `app/service.py:1057-1146`.
- The UI and user guides are existing surfaces: `app/static/index.html:197-215`, `docs/home-assistant-measurements.de.md`, `docs/home-assistant-measurements.en.md`.

## Validation Notes

- No additional runtime dependencies are needed.
- Test HTTP calls remain offline through `tests/conftest.py`'s `mock_transport`.
- Per-entity history requests must fail independently so one HA sensor does not suppress other comparisons.
- Reject non-finite sensor state values; invalid states must not become forecast errors.
