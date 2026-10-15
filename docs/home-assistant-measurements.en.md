# Configure Home Assistant temperature measurements

The dashboard can use an outdoor Home Assistant sensor as a real-world
observation source for a location.

## Add an instance and find a sensor

1. Open **Real world measurements → Home Assistant instances**.
2. Choose the instance's **Location**, enter the Home Assistant URL and a long-lived access token, then save the
   instance. The token is stored on the ha_weather server and is never shown
   again.
3. Under **Measurements**, choose the instance. Its paired location is inherited;
   there is no second location selector.
4. Search by part of an entity's display name or entity ID, for example
   `Garten`, then choose an enabled result.
5. Confirm the inherited location and **outdoor** scope, optionally use **Test**,
   then add the measurement.

The search checks Home Assistant's currently available state entities; it does
not list disabled or otherwise unloaded entities from the entity registry.
Matching non-temperature entities are shown but cannot be selected. Discovery
only enables `sensor` entities with the temperature device class, a numeric
current value, and a Celsius unit (`°C` or `C`). During entity discovery, the current state is used
to identify suitable candidates; recorded history supplies the daily
observations.

## Test the instance connection

Use **Test connection** beside an instance to check connectivity from the
ha_weather server and whether Home Assistant accepts its saved long-lived token.
Save URL or token changes first; the test does not use unsaved form values.
Environment-managed instances can also be tested despite being read-only.
The row shows success, denied access, timeout, network failure, or an unexpected
response without revealing credentials. No settings or measurements are changed.
A successful connection does not guarantee usable sensors or Recorder history;
use the separate measurement tests below for those checks.

## Test and inspect recent values

Use **Test** in the measurement form before saving, or beside an existing
measurement, to request its current Home Assistant state. A usable result is a
finite numeric `sensor` value with temperature device class and Celsius units
(`°C` or `C`). The result shows the value and available timestamp; unavailable,
invalid, or unsupported values are not treated as usable temperatures.
Connectivity, authentication and timeout failures are reported without exposing
saved credentials. Testing does not save settings or change provider scores.

Expand **Last 24 hours · HA recorder** in the full-width row below a measurement's
compact metadata and actions to request its rolling last **24 hours** of Home
Assistant Recorder values. This section starts collapsed and loads only when
opened; **Refresh history** requests recent data again.

The unnumbered table lists **Datetime (UTC)** and **Temperature (°C)**, oldest
first. Select **Show temperature trend** to create an optional SVG chart locally
in your browser from the same loaded records; opening the history alone does
not create a chart or request a separate chart service. The table and trend use
two equal-width columns on desktop and stack on narrow screens. Refreshing
clears the previous chart, including if the new request fails; show the trend
again after a successful refresh.

Missing or unusable records are not invented. This is source Recorder
history, **not an audit of values previously delivered to ha_weather**. Recorder
must record this entity and retain data for the requested period; a successful current-state test does not guarantee
recorded history. An empty result can therefore be valid.
Timestamped gaps indicate unusable recorded states, not failed deliveries.
Pre-window states are omitted, including finite values carried from before the
window. Gaps remain visible in the table and break the chart line; they are not
interpolated or replaced with carried values.
This per-sensor history is separate from the dashboard's overall **History**
and **Hourly source comparison** sections.

Section headings remain clickable and keyboard-toggleable with Enter or Space,
without the triangle markers.

## Existing configurations

Existing measurements keep their locations. A legacy instance with measurements
at one valid location can show that location automatically. An instance spanning
several locations stays in legacy mode rather than silently moving its sensors.
Pair it only after resolving conflicting mappings; otherwise the change is
rejected. You can still edit a legacy instance's name, URL or token without
assigning a location. To use the simplified add-measurement form, pair the instance first.
Environment-managed instances remain read-only in the UI. To pair a named
environment instance, set its `location_id` in `HAW_HOME_ASSISTANT_INSTANCES`.
The implicit `environment` instance from URL/token variables continues to use
its legacy per-location mappings. Existing multi-location measurements remain
usable without pairing; use the API with explicit locations to manage legacy
mappings, or configure separate named instances for the simplified UI workflow.
Explicit environment pairings that conflict with configured or persisted
measurement locations prevent startup until corrected; no sensors are silently
reassigned.

Older API clients may still supply an explicit measurement location for unpaired
instances. For a paired instance, omit it or supply the same location; a
conflicting location is rejected. Changing a pairing must not silently move
existing measurements or relabel archived observations.
A paired location cannot be deleted while an instance still references it;
remove the instance or resolve its pairing first.

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
Recorded values carry forward while the sensor state remains unchanged; the
comparison does not impose a separate freshness timeout.

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
