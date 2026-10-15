# Hourly source comparison API

## `GET /api/source-comparison/{location_id}?hours=24`

Returns a bounded provider-by-Home-Assistant-sensor temperature comparison for a configured location. The endpoint uses the same authentication policy as other protected API routes.

### Query parameter

`hours` accepts `24`, `48`, or `72`; the default is `24`. Unsupported values return HTTP 422. The response range is `[start, end)`, where `end` is the current UTC hour boundary.

### Response

```json
{
  "location_id": "vienna",
  "timezone": "Europe/Vienna",
  "generated_at": "2026-10-15T10:00:00Z",
  "start": "2026-10-14T10:00:00Z",
  "end": "2026-10-15T10:00:00Z",
  "hours": [
    {
      "target_time": "2026-10-15T09:00:00Z",
      "comparisons": [
        {
          "provider": "open_meteo",
          "source_id": "home:sensor.garden_temperature",
          "source_name": "Home / Garden",
          "forecast_temperature": 17.5,
          "measured_temperature": 16.5,
          "temperature_error": 1.0,
          "absolute_temperature_error": 1.0,
          "assessment": "good"
        }
      ]
    }
  ]
}
```

Error and assessment are null if either temperature is missing. Rows may identify a provider or sensor even if its counterpart is unavailable.

Provider data comes only from individual-provider hourly forecasts archived during refresh. HA data comes only from separately identified configured outdoor temperature measurements. Matching is by UTC target hour; UI labels use the returned location timezone. No consensus forecast or merged observation is returned as an individual source.

### Failure and empty states

- Unknown locations return HTTP 404, consistent with existing location endpoints.
- Failed HA sensor requests do not fail the endpoint or remove successful sensor data.
- No archived forecasts, configured sensors, or matching values produce an empty or partially populated `hours` list and explicit null/missing values, not fabricated errors.
- The existing `/api/history/{location_id}` response is unchanged.
