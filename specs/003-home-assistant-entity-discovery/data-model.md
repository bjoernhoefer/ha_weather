# Data Model: Home Assistant Entity Discovery and UI Alignment

## Home Assistant entity result

Transient read-only result returned from the configured Home Assistant instance.

| Field | Type | Rules |
| --- | --- | --- |
| `entity_id` | string | Home Assistant entity identifier; selected ID is validated by the existing measurement input rules. |
| `name` | string | Friendly name from entity attributes, falling back to the entity ID if absent. |
| `unit` | string or null | Home Assistant unit of measurement, when available. |
| `device_class` | string or null | Home Assistant device class, when available. |
| `selectable` | boolean | True only for a `sensor` entity with `device_class="temperature"`, a numeric current state, and a Celsius (`°C` or `C`) unit. |

Results are not persisted. The configured token and current entity state are not part of the result.

## Search

| Field | Type | Rules |
| --- | --- | --- |
| `instance_id` | string | Must resolve to a configured effective Home Assistant instance with URL and token. |
| `search` | string | Required non-empty trimmed substring of at most 100 characters; case-insensitive match against display name or entity ID. |

## Existing outdoor measurement

No schema change. A selected entity is entered as the existing `Measurement` with `instance_id`, `location_id`, `entity_id`, `scope="outdoor"`, and optional display `name`; its established uniqueness and count validation continue to apply.
