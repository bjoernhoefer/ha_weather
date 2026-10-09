# Research: Recent activity log

## Related-project inspiration

Previously inspected
[ha_satellite/logbuffer.py](https://github.com/bjoernhoefer/ha_satellite/blob/main/src/ha_satellite/logbuffer.py):
bounded timestamped entries are suitable for recent, ephemeral diagnostics.
Previously inspected e2proxy.py maintenance panel: manual refresh and severity
selection provide sufficient visibility. Adopt these interaction ideas, not
third-party logger capture or a new frontend framework.

## Decisions and alternatives

- **Ownership/concurrency**: WeatherService owns a deque(maxlen=500) of frozen
  entries protected by a threading lock. Append and snapshot share the lock;
  filtering/serialization use the snapshot outside it. This supports synchronous
  mutations and concurrent async operations without module-global cross-service
  leakage. SQLite/file history is unnecessary and outside scope.
- **Clock/order**: Reuse `app.clock.now_utc`; return newest insertion first,
  including equal timestamps. Avoid sorting by wall time.
- **Safety**: Emit fixed event templates. Component labels use developer-owned
  registry identifiers or generic fallback labels for custom sources. Known
  exception types map to safe class names; unknown/custom types map to `Exception`.
  Character filtering alone cannot remove secrets from a custom class name.
  Never interpolate names, IDs, configuration, URLs, request values, exception
  text, tracebacks or third-party log records.
- **Events**: Forecast completion follows persistence and cache update; failures
  record safe categories then preserve current exceptions. Provider failures are
  ERROR; tolerated observation failures are WARNING; completed operations and
  successful configuration mutations are INFO. Cached reads and log reads emit
  nothing. Failed persistence cannot emit completion.
- **Partial observations**: Existing `observations._fetch_one` and Home Assistant/
  Elasticsearch per-instance catches can hide failures while returning healthy
  data. Use an optional failure reporter attached/passed through these paths,
  preserving existing method contracts for callers without reporting and existing
  merge/fallback behavior. Report only the source category, never instance data.
- **API**: Reuse `require_api_key` through the existing protected dependency.
  Local mode remains anonymous; public mode requires its current credentials.
  Validate minimum level and limit, filter before limiting, and disable caching.
- **UI**: Native collapsed details below General settings, fetch on first open
  and manual refresh thereafter; use existing authenticated fetch helper. No
  background polling. Loading, empty/no-match and generic error states are
  independent of weather controls. All dynamic text uses textContent.

No new dependency, schema, weather algorithm or authentication policy is needed.
