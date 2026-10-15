# Research: Home Assistant Measurement Diagnostics

## Location ownership

**Decision**: Nullable pairing with unique-location legacy inference; keep ambiguous instances in explicit legacy mode. Reject incompatible changes.

**Rationale**: Existing environment mappings and stored instances support several locations. Automatic reassignment would change scientific attribution.

**Alternatives considered**: Automatically split installations or move sensors; rejected because either duplicates credentials or silently changes data meaning.

## Diagnostic provenance

**Decision**: Request exact current state for Test and source recorder history for recent values. Neither changes stored configuration, scoring or archives.

**Rationale**: Current availability is not proof that Recorder retained data; archived outdoor hourly comparisons are not a raw indoor/outdoor delivery audit.

**Alternatives considered**: Reuse hourly comparison archives or introduce polling history; rejected as misleading or beyond scope.

## Usability and transport

**Decision**: Reuse discovery's finite numeric Celsius temperature-sensor eligibility, URL validation, saved server-side credentials, request timeouts and disabled redirects.

**Rationale**: Consistency avoids presenting Fahrenheit, invalid states or upstream failures as usable temperatures.

**Alternatives considered**: Convert units or expose raw upstream responses; rejected as unnecessary semantic expansion and credential risk.

## Disclosure controls

**Decision**: Hide standard and WebKit markers while preserving native summary focus and toggling.

**Rationale**: Removes the unwanted triangle without replacing accessible native behavior.
