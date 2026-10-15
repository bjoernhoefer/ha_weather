# Feature Specification: Measurement history layout

**Feature Branch**: `copilot/update-measurements-overview`
**Created**: 2026-10-15
**Status**: Approved visual direction
**Input**: User approved desktop/mobile previews: “Das gefällt mir sehr gut.
das können wir so nehmen und ausrollen!”

## User Scenarios & Testing

### User Story 1 - Read recent measurements (Priority: P1)

As a user I want a balanced, readable history below each sensor rather than
a numbered list inside its action column.

**Why this priority**: Expanding history must not stretch the metadata row.
**Independent Test**: Expand a sensor's history and read its two-column table.

**Acceptance Scenarios**:

1. Given a configured sensor, when history opens, then a separate full-width
   box below its compact metadata displays the rolling last 24 hours.
2. Given unsorted readings, when shown, then date/time in UTC precedes
   temperature in Celsius, oldest first, without numbering.
3. Given unavailable recorded states, when shown, then explicit gaps replace
   invented temperatures; the source remains identified as HA Recorder.

### User Story 2 - Inspect a lightweight temperature trend (Priority: P2)

As a user I can request a temperature trend without slowing initial page loading.

**Why this priority**: A plot helps interpretation but must remain optional.
**Independent Test**: Open history, then separately request the chart.

**Acceptance Scenarios**:

1. Given collapsed history, when the page loads, then no history is requested.
2. Given loaded history, when no chart is requested, then no plot is generated.
3. Given a chart request, then it uses the same readings and time window,
   never joins across recorded gaps, and needs no additional data download.
4. Given a narrow screen, then table and plot stack without page overflow.

### Edge Cases

- Empty history, request failure and retry, refresh after a rendered chart.
- Carried readings, invalid timestamps/numbers and out-of-window records.
- One reading, equal temperatures, negative temperatures and duplicate timestamps.
- Sensor removed or configuration re-rendered while a request is pending.

## Requirements

### Functional Requirements

- **FR-001**: Each sensor MUST retain its existing Test/Edit/Delete behavior and
  have an independently collapsible, labelled history beneath its metadata.
- **FR-002**: The history MUST display a chronological unnumbered date/time and
  temperature table, with UTC and Celsius explicit.
- **FR-003**: History MUST load only when opened, with refresh/retry and clear
  loading, empty and error states.
- **FR-004**: The optional chart MUST appear only after an explicit request,
  using recorded times proportionally, with no curve across recorded gaps.
- **FR-005**: Refresh MUST clear stale data/plots, including on failure.
- **FR-006**: Desktop history MUST use balanced columns and mobile MUST stack
  panels; keyboard disclosure and table reading MUST remain available.
- **FR-007**: Temporary approval images MUST be removed before a pull request.
- **FR-008**: Existing API, configuration, storage and scoring MUST not change.

### Key Entities

- Measurement: existing sensor identity, name, instance and location.
- History: rolling time window, recorded Celsius values and timestamped gaps.
- Plot: optional presentation of the same filtered history, not extra readings.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every displayed reading has a date/time and temperature column,
  with zero ordinal-number columns.
- **SC-002**: Initial page loading issues zero per-sensor history requests and
  displays zero per-sensor plots.
- **SC-003**: At 390 px and desktop width, history remains readable without
  horizontal page overflow.
- **SC-004**: All explicit gap events interrupt the temperature curve.
- **SC-005**: Both preview PNGs are absent from the final branch tree.

## Assumptions

- The approved visual direction is sufficient; no further preview gate required.
- The existing English UI remains English; paired guides are updated in DE/EN.
- Existing Home Assistant Recorder access and retention determine availability.
- Preparing tested changes does not imply a live deployment has occurred.

## Affected Surfaces and Compatibility

- **Surfaces**: Responsive static web UI, tests, paired user documentation.
- **Compatibility**: No changes to HA REST payloads, backend, persistence,
  credentials, forecast interpretation or release/deployment configuration.
- **Localization**: Update paired measurement guides in German and English.
