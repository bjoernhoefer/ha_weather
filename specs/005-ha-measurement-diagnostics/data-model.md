# Data Model

## Home Assistant instance

Existing ID, name, URL and write-only token gain nullable `location_id`. The location must exist when explicitly paired. Stored instances persist the field; environment instances remain read-only. A legacy instance may resolve to its sole existing valid measurement location without changing sensor records.

## Measurement

Retain persisted ID, instance ID, effective location, entity ID, scope and name. Input location becomes optional for paired instances and must match if supplied. Unpaired legacy inputs still need an explicit location. Existing uniqueness and per-location/scope limits apply.

Pairing changes cannot silently move existing measurements or relabel historical observations. Deleting locations must not leave a dangling instance pairing.

## Diagnostic result

Read-only entity/current-state usability result: finite Celsius value when valid, available timestamp and fixed reason when unusable. Upstream exceptions remain sanitized.

## Recorder history

Read-only response with bounded start/end, timestamped finite Celsius samples and explicit recorder provenance. Invalid/nonfinite/unsupported entries are not temperatures. Do not fabricate a new sample at the window boundary from an older recorded state.
