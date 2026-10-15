# Configure Home Assistant temperature measurements

The dashboard can use an outdoor Home Assistant sensor as a real-world
observation source for a location.

## Add an instance and find a sensor

1. Open **Real world measurements → Home Assistant instances**.
2. Enter the Home Assistant URL and a long-lived access token, then save the
   instance. The token is stored on the ha_weather server and is never shown
   again.
3. Under **Measurements**, choose the instance and location.
4. Search by part of an entity's display name or entity ID, for example
   `Garten`, then choose an enabled result.
5. Confirm the location and **outdoor** scope, then add the measurement.

The search checks Home Assistant's currently available state entities; it does
not list disabled or otherwise unloaded entities from the entity registry.
Matching non-temperature entities are shown but cannot be selected. Discovery
only enables `sensor` entities with the temperature device class, a numeric
current value, and a Celsius unit (`°C` or `C`). The current state is used only
to identify suitable candidates; recorded history supplies the daily
observations.

## Compare hourly sources

After forecast refreshes have run, open **Hourly source comparison** in the
dashboard. It compares each archived weather-provider temperature separately
with every configured **outdoor** Home Assistant sensor for the same hour.
Sensors from different instances are kept distinct. The matrix summarizes one
selected hour; the detail table lists every provider/sensor pair in the chosen
24-, 48-, or 72-hour period. Times use the location's timezone.

The deviation is forecast minus measured temperature; the absolute error is
shown separately. Assessments are `Good` up to 1 °C, `Check` above 1 °C through
2 °C, and `Large` above 2 °C. They are descriptive temperature bands, not the
provider ranking score. If either value is missing or the HA history does not
identify a Celsius temperature sensor, the error and assessment are unavailable.
`unavailable` and other invalid states are not treated as measured values.

Only source-specific forecasts collected after this feature is deployed can be
compared. New hourly data is retained for up to 72 hours; existing consensus
history cannot be attributed to individual providers and is not backfilled.

## Troubleshooting

- **No matches**: Try another part of the display name or entity ID. You can
  still enter an entity ID manually.
- **Search fails**: Check that the instance URL and token are valid and that
  ha_weather can reach Home Assistant. Discovery errors do not change saved
  measurements.
- **Public deployment**: Enter the ha_weather API key in the dashboard as well.

Use HTTPS when connecting across an untrusted network. Local Home Assistant
URLs on a trusted private network remain supported.
