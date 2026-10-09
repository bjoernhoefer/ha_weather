# Contract: GET /api/logs

Read-only recent activity endpoint using the existing protected dependency.

## Query

| Parameter | Default | Accepted values |
|---|---|---|
| level | INFO | INFO, WARNING, ERROR (case-sensitive minimum severity) |
| limit | 100 | Integer from 1 through 500 |

Snapshot the service buffer, reverse insertion order, filter minimum severity,
then limit. The request neither records an event nor refreshes weather.

## Response

`200 OK`, `Content-Type: application/json`, `Cache-Control: no-store`.
Always a JSON array, including `[]` for empty/no-match:

```json
[
  {
    "timestamp": "2026-10-09T06:30:00+00:00",
    "level": "WARNING",
    "component": "observations.open_meteo",
    "message": "Observation update failed (ReadTimeout)"
  }
]
```

Each entry has exactly timestamp, level, component and message. Timestamp is
ISO 8601 UTC; component/message bounds and safe-event constraints are defined in
[data-model.md](../data-model.md). There is no pagination or shared worker history.

## Authentication and failures

- Local mode: anonymous access, unchanged from other protected routes.
- Public mode: existing X-API-Key or Authorization header credentials; absent/invalid key
  returns existing 401 behavior. Missing configured keys retains existing 500.
- Invalid level, noninteger limit or out-of-range limit: FastAPI validation 422.
- Preserve existing error envelopes; never include buffered raw exceptions.

Authenticated log content must not be cached; the UI fetch also uses `no-store`.
No changes to existing endpoints, Home Assistant payloads or access policy.
