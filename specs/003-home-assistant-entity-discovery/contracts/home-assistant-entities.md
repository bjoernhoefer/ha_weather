# Home Assistant Entity Discovery Contract

## Request

`GET /api/observation-sources/home-assistant/instances/{instance_id}/entities?search={text}`

- Uses the configured Home Assistant URL and stored long-lived token for that instance.
- Requires the same authentication as other configuration endpoints in public deployment mode.
- `search` is required; leading/trailing whitespace is ignored and matching is case-insensitive.
- Queries current entities on demand and returns entities whose friendly name or entity ID contains the search text.

## Successful response

HTTP `200 OK`:

```json
[
  {
    "entity_id": "sensor.garden_temperature",
    "name": "Garden temperature",
    "unit": "°C",
    "selectable": true
  }
]
```

The response contains no token or upstream state value. `name` falls back to `entity_id` if Home Assistant omits the friendly name. All matching entities are returned; `selectable` is true only for a `sensor` entity with a numeric current state and Celsius (`°C` or `C`) units. Other matching entities may be inspected but cannot be selected from discovery.

## Failure responses

- `401 Unauthorized`: public deployment request lacks a valid service API key.
- `404 Not Found`: the instance does not exist or is not configured with a URL and token.
- `422 Unprocessable Entity`: missing/blank search query.
- `502 Bad Gateway`: Home Assistant request failed; the response does not contain upstream response content or credentials.
