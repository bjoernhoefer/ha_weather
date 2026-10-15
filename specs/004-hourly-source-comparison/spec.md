# Feature Specification: Hourly Source Comparison

**Feature Branch**: `004-hourly-source-comparison`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User request to compare each internet weather source with each configured Home Assistant outdoor measurement by hour, with a matrix and a detailed table.

## User Scenarios & Testing

### User Story 1 - Compare hourly temperature forecasts (Priority: P1)

As a dashboard user, I want to compare each internet weather source with each configured outdoor Home Assistant temperature sensor, so I can see which forecasts match my measured conditions.

**Why this priority**: This is the core request and makes provider/source differences visible instead of hiding them in a consensus.

**Independent Test**: Archive hourly values from two weather providers and provide observations from two separately configured Home Assistant sensors. Open the comparison for one location and verify each provider/sensor pair has its own measured value and error.

**Acceptance Scenarios**:

1. **Given** at least one archived provider forecast and two configured outdoor Home Assistant sensors, **When** the user opens the comparison, **Then** the view identifies each sensor separately and does not merge their readings.
2. **Given** two providers and two sensors with values for the same hour, **When** the user views that hour, **Then** all four provider/sensor combinations show forecast temperature, observed temperature, signed deviation, absolute error, and a temperature-specific assessment.
3. **Given** a provider or sensor has no value for an hour, **When** the user views the comparison, **Then** the missing value is shown as unavailable and no error or assessment is fabricated.
4. **Given** the user changes the selected hour, **When** the matrix updates, **Then** its values and detailed rows refer to that same hour.

---

### User Story 2 - Review a time range (Priority: P2)

As a dashboard user, I want to choose a recent time range and inspect hour-by-hour comparison rows, so I can understand how a source pair performed over time.

**Why this priority**: A single hour provides a snapshot; a bounded recent history makes repeated differences apparent.

**Independent Test**: Provide archived data for multiple recent hours, select a range and an hour, and verify the matrix and detail table are restricted to the selected range and hour.

**Acceptance Scenarios**:

1. **Given** recent archived data, **When** the user selects a supported period, **Then** only hours inside that period are offered and shown.
2. **Given** the selected period contains no archived forecast, **When** the user opens the view, **Then** a helpful empty state explains that forecasts are archived during refreshes.
3. **Given** the user's location has a non-UTC timezone, **When** the user reads an hour, **Then** the displayed local time is unambiguous while comparisons use the same absolute hour.

## Edge Cases

- No outdoor Home Assistant temperature sensors are configured, or the Home Assistant source is disabled or unavailable.
- An individual sensor has no retained history, invalid/non-numeric states, or a failed Home Assistant request.
- A provider has no hourly forecast coverage for a target hour or failed during refresh.
- Daylight-saving transitions contain repeated or skipped local times.
- Forecast and observation values are both missing; neither error nor rating should be inferred.
- A location or source is removed after forecasts have been archived.
- A configured sensor is indoor-only and must not be compared with outdoor weather forecasts.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST retain hourly forecasts separately for each internet weather provider and target hour; it MUST NOT substitute the provider consensus for a provider-specific forecast.
- **FR-002**: The dashboard MUST compare provider forecasts only with configured outdoor Home Assistant temperature sensors, preserving instance and sensor identity.
- **FR-003**: The dashboard MUST provide a compact matrix for a selected hour, with Home Assistant sensors as rows and internet sources as columns.
- **FR-004**: Each populated comparison MUST show the forecast value, measured value, signed deviation (forecast minus measured), absolute error, and a temperature-specific assessment.
- **FR-005**: The dashboard MUST provide a detailed table for the selected hour and selected recent time range, with one row per hour, internet source, and Home Assistant sensor combination.
- **FR-006**: Users MUST be able to select a supported recent time range and an hour within it; matrix and detail table MUST remain synchronized.
- **FR-007**: Missing forecasts or measurements MUST be clearly represented without inventing an error or rating.
- **FR-008**: Assessment MUST be based on absolute temperature error, in Celsius, and MUST NOT combine temperature with precipitation or other unlike units.
- **FR-009**: The comparison MUST remain usable on narrow screens and with keyboard navigation.
- **FR-010**: Existing consensus history, provider ranking, Home Assistant REST payloads, and configured source behavior MUST remain compatible.

### Key Entities

- **Provider hourly forecast**: A weather source's predicted temperature for a location and target hour, including its forecast issue time.
- **Outdoor measurement**: One configured Home Assistant sensor's measured hourly temperature, identified by its Home Assistant instance and entity.
- **Hourly comparison**: The pairing of a provider forecast and one outdoor measurement for the same location and absolute target hour, with signed deviation, absolute error, and assessment.
- **Comparison period**: A bounded recent interval of archived forecasts and measurements selected by the dashboard user.

## Success Criteria

### Measurable Outcomes

- **SC-001**: With two providers and three configured outdoor Home Assistant sensors, users can see all six source pairings for an hour in the matrix and in the detailed rows.
- **SC-002**: For every pair with both values present, the shown signed deviation equals forecast minus measurement and the absolute error equals its magnitude.
- **SC-003**: For any pair missing either value, the view shows an unavailable state and no numeric error or assessment.
- **SC-004**: Users can select a recent time range and hour and see matching source-pair data in both views.
- **SC-005**: Existing forecast, ranking, and consensus-history workflows continue to return their previous response shapes and behavior.

## Assumptions

- V1 compares temperature only because configured Home Assistant measurements are numeric temperature sensors; precipitation observations are not available per sensor.
- Each configured outdoor Home Assistant entity is a distinct comparison source. Values from different entities or instances are never averaged together.
- The existing hourly sensor aggregation rule is used per entity: state values in an hour, including the carried-forward state, determine that hour's mean.
- Comparisons use absolute UTC hours; the UI formats timestamps in the configured location timezone and includes the timezone context.
- The initial supported comparison window is limited to the existing hourly archive retention (up to 72 hours); only forecasts recorded after this feature is deployed are available.
- Temperature assessments use three explicit absolute-error bands: up to 1 °C, over 1 °C through 2 °C, and over 2 °C. These are display categories, not a provider ranking score.
- The page continues using the existing English UI; paired German and English documentation will describe the feature.

## Affected Surfaces and Compatibility

- **Surfaces**: Provider forecast archival, SQLite storage, comparison API, Home Assistant history reads, responsive web UI, German and English user documentation, focused tests.
- **Compatibility**: Additive storage and API behavior; retain the current consensus history API/UI, daily provider scoring, existing configuration, and Home Assistant REST contracts.
- **Localization**: Add paired German and English user documentation. Match the existing English dashboard labels and keep assessment units explicit.
