# Measurement Contracts

Existing instance create/update accepts optional `location_id` and instance status exposes the effective pairing. The UI requires a location for new installations; older explicit-location callers stay supported.

Existing measurement create/update accepts omitted `location_id` for paired installations, derives it server-side, and keeps the resolved location in responses. Explicit mismatches fail without writes. Legacy unpaired installations require explicit locations; incompatible pairing changes fail with conflict.

## Read-only diagnostics

- `POST /api/observation-sources/home-assistant/measurements/test`
- `POST /api/observation-sources/home-assistant/measurements/history`

Both accept the existing measurement input shape, with optional inherited location. This works for unsaved, persisted, and environment records without requiring a database ID.

Test returns usability, current numeric Celsius value when valid, timestamp and a fixed reason otherwise. History returns rolling 24-hour bounds and timestamped source Recorder samples. Empty history is valid and does not imply current-state failure.

Both routes use existing public-mode API-key requirements and configured-instance credentials only. Missing instance/location, incompatible location, missing credentials, invalid URLs, upstream timeouts and failures use sanitized existing API error conventions. No secrets, raw upstream bodies, writes, scoring updates or redirects.
