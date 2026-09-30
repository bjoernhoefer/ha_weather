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
      - name: "forecast_failure_level"
        value_template: "{{ value_json.failure_level }}"
      - name: "watering_impact"
        value_template: "{{ value_json.watering_impact }}"
      - name: "heating_impact"
        value_template: "{{ value_json.heating_impact }}"
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
      - name: "forecast_failure"
        value_template: "{{ value_json.forecast_failure }}"
        attributes:
          failure_level: "{{ value_json.failure_level }}"
          failure_type: "{{ value_json.failure_type }}"
          reason: "{{ value_json.failure_reason }}"
          confidence: "{{ value_json.failure_confidence }}"
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

## Live forecast verification

Push the local thermometer (and rain gauge, if available) every few minutes.
`precipitation_mm` is the rain **since the last push**, not the daily total.
Reporting the adjustments your automations applied (0 = unchanged,
1 = fully reduced) makes the impact exact; otherwise it is estimated.
Details: [forecast-verification.md](forecast-verification.md).

```yaml
rest_command:
  ha_weather_push_vienna:
    url: http://ha-weather.local:8080/api/readings/vienna
    method: POST
    content_type: application/json
    # headers:
    #   X-API-Key: !secret ha_weather_api_key
    payload: >
      {"temperature": {{ states('sensor.garden_temperature') | float(0) }},
       "precipitation_mm": {{ states('sensor.rain_last_5_minutes') | float(0) }},
       "adjustments": {
         "garden_watering": {{ 1 - (states('input_number.garden_watering_minutes') | float(0) / 20) }},
         "heating": {{ states('input_number.heating_reduction') | float(0) }}}}

automation:
  - alias: "Push readings to ha_weather"
    trigger:
      - platform: time_pattern
        minutes: "/5"
    action:
      - service: rest_command.ha_weather_push_vienna

  # the forecast is wrong and it hurts: go back to the normal schedule
  - alias: "Normal watering when the forecast fails"
    trigger:
      - platform: state
        entity_id: sensor.watering_impact
        to: "high"
    condition:
      - condition: state
        entity_id: binary_sensor.forecast_failure
        state: "on"
    action:
      - service: input_number.set_value
        target:
          entity_id: input_number.garden_watering_minutes
        data:
          value: 20

  - alias: "Normal heating when the forecast fails"
    trigger:
      - platform: state
        entity_id: sensor.heating_impact
        to: "high"
    action:
      - service: input_number.set_value
        target:
          entity_id: input_number.heating_reduction
        data:
          value: 0
      - service: notify.notify
        data:
          message: >
            Weather forecast failure ({{ state_attr('binary_sensor.forecast_failure', 'failure_type') }}):
            {{ state_attr('binary_sensor.forecast_failure', 'reason') }}
```
