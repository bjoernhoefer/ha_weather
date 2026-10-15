# Quickstart: Hourly Source Comparison

## Prerequisites

- The application has a location and at least one weather provider that returns hourly temperature forecasts.
- At least one Home Assistant instance has an outdoor Celsius temperature sensor configured for that location.
- Forecast refreshes and Home Assistant history have populated the new archive after the feature is deployed.

## Validate

1. Refresh a location forecast once to archive source-specific hourly forecasts.
2. Request `GET /api/source-comparison/{location_id}?hours=24` using the same API-key setup as other API requests.
3. Confirm response rows preserve provider names and HA sensor identities; compare signed error with forecast minus measured value.
4. Configure a second outdoor sensor and refresh the comparison. Confirm it appears separately and a failed/missing sensor does not erase other rows.
5. Open the dashboard comparison section, switch among 24/48/72 hours and a target hour, and verify the matrix is for the selected hour while the detailed table covers the selected range.
6. Check local time against the location timezone, including two separate hours during a daylight-saving fall-back.

## Automated tests

Run focused tests:

```bash
pytest -q tests/test_storage.py tests/test_observations.py tests/test_service.py tests/test_api.py
```

Run the full suite:

```bash
pytest -q
```

See [the API contract](contracts/source-comparison.md) and [data model](data-model.md) for response and archive semantics.
