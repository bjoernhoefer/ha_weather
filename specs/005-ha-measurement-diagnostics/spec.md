# Feature Specification: Home Assistant Measurement Diagnostics

**Feature Branch**: Current task branch
**Created**: 2026-10-15
**Status**: Accepted for implementation
**Input**: Pair Home Assistant instances with locations, remove redundant measurement location selection, add measurement tests and collapsed recent history, and remove disclosure triangles.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure the location once (Priority: P1)

Users pair an installation with a location and add its sensors without repeating that location.

**Why this priority**: Eliminate redundant settings without silently moving existing observations.
**Independent Test**: Save an instance with a location, then save a measurement without choosing another location.

**Acceptance Scenarios**:
1. **Given** a paired instance, **When** a user adds a sensor, **Then** its location comes from the instance.
2. **Given** an existing installation with sensors at multiple locations, **When** upgrading, **Then** the existing mappings remain unchanged and incompatible pairing changes are explained rather than applied silently.
3. **Given** older configuration or clients, **When** explicit locations are supplied for an unpaired installation, **Then** the existing workflow remains compatible.

### User Story 2 - Test a sensor (Priority: P2)

Users test a selected or manually entered sensor before saving and can retest saved sensors.

**Why this priority**: Quickly distinguish connectivity problems from unusable sensor values.
**Independent Test**: Test a numeric Celsius temperature sensor and an unavailable sensor.

**Acceptance Scenarios**:
1. **Given** a valid temperature sensor, **When** tested, **Then** its current numeric value, unit, timestamp, and usability are shown.
2. **Given** an unavailable, nonnumeric, non-temperature, or unsupported-unit sensor, **When** tested, **Then** it is not described as usable.
3. **Given** an upstream failure, **When** tested, **Then** the user receives a safe error without credentials or upstream response details and no settings are changed.

### User Story 3 - Inspect recent values (Priority: P2)

Users expand a sensor's recent history to inspect values returned by its Home Assistant recorder.

**Why this priority**: Make recent sensor behavior inspectable without cluttering settings.
**Independent Test**: Open history for a sensor with recent records and one without records.

**Acceptance Scenarios**:
1. **Given** a saved sensor, **When** settings load, **Then** its history is collapsed and no history request occurs until expansion.
2. **Given** recent recorder entries, **When** history expands, **Then** timestamped usable Celsius values for the rolling last 24 hours are shown, clearly identified as recorder history rather than a local delivery audit.
3. **Given** missing or failed history, **When** expanded, **Then** a clear empty/error state and retry option are available.

### User Story 4 - Cleaner collapsible headings (Priority: P3)

**Why this priority**: Remove unwanted visual markers while preserving disclosure behavior.
**Independent Test**: Click and keyboard-toggle a heading without a visible triangle.

**Acceptance Scenarios**:
1. **Given** a collapsible section, **When** rendered, **Then** it has no triangle and retains keyboard focus and native toggle behavior.

### Edge Cases

- Upgrade/restart with a pre-existing database; legacy environment instances spanning several locations.
- Invalid/deleted locations, duplicate sensors, existing per-location limits, conflicting pairing changes.
- Missing tokens, redirects, timeouts, upstream failures, malformed state/history, nonfinite values, unsupported units.
- No recorder data; timezone-aware boundaries; state active before the window is not falsely represented as a newly delivered measurement.
- Switching instance/entity during an in-flight test/history request; read-only environment records.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Instance setup MUST offer a location pairing; paired measurements MUST inherit it without a separate selector.
- **FR-002**: Existing stored and environment configurations MUST remain readable and retain their location meaning.
- **FR-003**: Conflicting explicit locations or pairing changes MUST fail without partially modifying settings.
- **FR-004**: Test MUST report current temperature usability and available value/time without saving or changing scoring.
- **FR-005**: Recent history MUST be on demand, collapsed by default, bounded to the last 24 hours, and explicit about its recorder origin.
- **FR-006**: Test/history MUST preserve existing access protection and never expose saved tokens or raw upstream failures.
- **FR-007**: All collapsible headings MUST hide disclosure triangles and retain mouse/keyboard accessibility.
- **FR-008**: English and German guidance MUST explain pairing, legacy handling, Test, history, and its limitations.

### Key Entities

- **Installation**: Saved Home Assistant connection and optional legacy-compatible location pairing.
- **Measurement**: Sensor, installation, indoor/outdoor scope, and effective location.
- **Diagnostic result**: Current usability, value/unit/time, or safe failure reason.
- **Recent sample**: Timestamped temperature from the installation's recorder.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A paired sensor can be saved with zero measurement-level location selections.
- **SC-002**: All upgrade fixtures retain their original measurement locations after restart.
- **SC-003**: Tests distinguish valid Celsius temperatures from unavailable, nonfinite, wrong-class, and unsupported-unit values.
- **SC-004**: History starts collapsed, displays no out-of-window samples, and exposes an empty state when none exist.
- **SC-005**: All collapsible headings remain keyboard-toggleable with zero visible disclosure triangles.

## Assumptions

- Scope is Home Assistant measurements, not Elasticsearch diagnostics or changes to forecast/scoring semantics.
- “Delivered values” means source recorder history available on demand, not a new persistent local polling audit.
- Unpaired legacy multi-location installations remain supported; no destructive automatic reassignment.
- Existing API protection, stored server-side credentials, and outgoing request timeouts are reused.

## Affected Surfaces and Compatibility

- **Surfaces**: Python configuration/service, SQLite, observation-source helpers, authenticated API, responsive static UI, tests, documentation.
- **Compatibility**: Additive storage migration; legacy explicit-location clients/configuration stay usable; paired instances reject conflicting locations. Forecast, scoring, and Home Assistant weather sensor payloads are unchanged.
- **Localization**: Update paired English/German measurement guides and English embedded help.
