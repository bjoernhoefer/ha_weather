# Data model: Recent activity

## ActivityEntry

Immutable internal value; serialized as:

| Field | Type | Constraint |
|---|---|---|
| timestamp | UTC datetime | From `clock.now_utc`; ISO 8601 with UTC offset |
| level | string enum | INFO, WARNING or ERROR |
| component | string | Fixed safe label, 1–64 characters |
| message | string | Fixed event summary, 1–240 characters |

Only developer-owned templates/labels and allowlisted safe exception categories
may produce entries. Unknown exception classes become `Exception`; custom source
labels become a generic component. Bounds are enforced at construction.
No request, configuration, location/instance names, URLs or exception details
are stored. No entry ID or persistence model is required.

## RecentActivity

One locked deque(maxlen=500) per WeatherService. Append immutable entries under
the lock, automatically evicting the oldest. Copy a snapshot under the same lock;
reverse insertion order, filter by level rank (INFO < WARNING < ERROR), then
apply the validated limit. Concurrent readers never mutate retained entries.
Construction/restart produces an empty buffer; workers/services are isolated.

## Event transitions

| Operation/outcome | Level | Safe summary example |
|---|---|---|
| Forecast refresh completes after persistence/cache update | INFO | Forecast update completed |
| Forecast refresh raises, including persistence failure | ERROR | Forecast update failed (OperationalError) |
| Provider fetch raises | ERROR | Provider update failed (ReadTimeout) |
| Observation source or per-instance fetch fails but fallback continues | WARNING | Observation update failed (HTTPStatusError) |
| Optional garden/soil update fails | WARNING | Garden indicators update failed (ReadTimeout) |
| Optional Azure verification fails | WARNING | Azure verification failed (HTTPStatusError) |
| Successful configuration mutation | INFO | Provider API key updated |

Mutation categories cover location add/delete; provider enable/disable, API key
set/delete and custom source add/delete; Home Assistant/Elasticsearch instance and
measurement add/update/delete; provider override set/delete. Use fixed action
summaries without submitted values. Failed/rejected mutations and no-op deletions
must not claim a completed change. Provider and overall forecast failure entries
may coexist because they describe different outcomes.
