# Home Assistant Entity Discovery Contract

## Request

`GET /api/observation-sources/home-assistant/instances/{instance_id}/entities?search={text}`

- Uses the configured Home Assistant URL and stored long-lived token for that instance.
- Requires the same authentication as other configuration endpoints in public deployment mode.
- `search` is required; leading/trailing whitespace is ignored and matching is case-insensitive.
- Queries currently available state entities on demand (not the full entity registry) and returns entities whose friendly name or entity ID contains the search text.
- The configured URL must use HTTP(S) and contain no embedded username/password. Local and private-network addresses are supported. Redirects are not followed.

## Successful response

HTTP `200 OK`:

```json
[
  {
    "entity_id": "sensor.garden_temperature",
    "name": "Garden temperature",
    "unit": "°C",
    "device_class": "temperature",
    "selectable": true
  }
]
```

The response contains no token or upstream state value. `name` falls back to `entity_id` if Home Assistant omits the friendly name. All matching entities are returned; `selectable` is true only for a `sensor` entity with `device_class="temperature"`, a numeric current state, and Celsius (`°C` or `C`) units. Other matching entities may be inspected but cannot be selected from discovery.

## Failure responses

- `401 Unauthorized`: public deployment request lacks a valid service API key.
- `404 Not Found`: the instance does not exist.
- `409 Conflict`: the instance has no configured URL/token or has an invalid Home Assistant URL.
- `422 Unprocessable Entity`: missing/blank search query.
- `502 Bad Gateway`: Home Assistant rejected the request or returned an invalid response; the response does not contain upstream response content or credentials.
- `504 Gateway Timeout`: Home Assistant did not respond within the configured request timeout.
