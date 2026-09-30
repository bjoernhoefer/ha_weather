# Home Assistant integration

`ha_weather` exposes a flat JSON payload per location that maps 1:1 onto
Home Assistant sensors:

```
GET /api/homeassistant/{location_id}
```

Add the following to `configuration.yaml` (replace the host, and drop the
`headers:` block when the service runs in `local` mode inside your subnet).

```yaml
rest:
  - resource: http://ha-weather.local:8080/api/homeassistant/vienna
    scan_interval: 1800
    # headers:
    #   X-API-Key: !secret ha_weather_api_key
    sensor:
      - name: "Vienna forecast temperature max"
        value_template: "{{ value_json.temperature_max }}"
        unit_of_measurement: "°C"
        device_class: temperature
      - name: "Vienna forecast temperature min"
        value_template: "{{ value_json.temperature_min }}"
        unit_of_measurement: "°C"
        device_class: temperature
      - name: "Vienna forecast precipitation"
        value_template: "{{ value_json.precipitation_mm }}"
        unit_of_measurement: "mm"
      - name: "weather_season"
        value_template: "{{ value_json.weather_season }}"
      - name: "weather_season_from"
        value_template: "{{ value_json.weather_season_from }}"
      - name: "weather_season_to"
        value_template: "{{ value_json.weather_season_to }}"
      - name: "weather_top_provider"
        value_template: "{{ value_json.top_provider }}"
    binary_sensor:
      - name: "upcoming_weather_change"
        value_template: "{{ value_json.upcoming_weather_change }}"
        attributes:
          reason: "{{ value_json.weather_change_reason }}"
          change_date: "{{ value_json.weather_change_date }}"
      - name: "weather_seasonal_change"
        value_template: "{{ value_json.weather_seasonal_change }}"
        attributes:
          days_until: "{{ value_json.days_until_seasonal_change }}"
```

Use `porto_cristo` instead of `vienna` for the second location.

## Example automation

Reduce garden watering when the season turns from summer to autumn:

```yaml
automation:
  - alias: "Reduce watering on seasonal change"
    trigger:
      - platform: state
        entity_id: binary_sensor.weather_seasonal_change
        to: "on"
    condition:
      - condition: state
        entity_id: sensor.weather_season_to
        state: "autumn"
    action:
      - service: input_number.set_value
        target:
          entity_id: input_number.garden_watering_minutes
        data:
          value: 5
```
