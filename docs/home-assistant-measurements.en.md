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

## Troubleshooting

- **No matches**: Try another part of the display name or entity ID. You can
  still enter an entity ID manually.
- **Search fails**: Check that the instance URL and token are valid and that
  ha_weather can reach Home Assistant. Discovery errors do not change saved
  measurements.
- **Public deployment**: Enter the ha_weather API key in the dashboard as well.

Use HTTPS when connecting across an untrusted network. Local Home Assistant
URLs on a trusted private network remain supported.
