# Feature Specification: Recent activity log

**Feature Branch**: Current task branch (unchanged)
**Created**: 2026-10-09
**Status**: Accepted for implementation
**Input**: Add logging below General settings to see recent updates and error causes; inspect related account projects.

## User Scenarios & Testing

### User Story 1 - See recent updates (Priority: P1)

Users open Logging below General settings to see recent successful updates and configuration changes.

**Why this priority**: Makes operation visible without container access.
**Independent Test**: Refresh a forecast, open Logging and find its outcome.
**Acceptance Scenarios**:
1. Given completed updates, when Logging opens, then timestamps, severity, component and safe summaries appear newest first.
2. Given successful configuration changes, when logs refresh, then the changes appear without submitted values.

### User Story 2 - Diagnose failures (Priority: P1)

Users filter recent activity to warnings or errors to identify failing components.

**Why this priority**: Partial failures must remain visible without breaking healthy sources.
**Independent Test**: Fail one provider and inspect warning/error activity.
**Acceptance Scenarios**:
1. Given a failing provider or observation source, when an update finishes, then a safe cause category identifies the failing component.
2. Given secret-bearing exception details, when logs are read, then credentials, URLs, bodies and tracebacks are absent.
3. Given public deployment, when an unauthenticated reader requests logs, then existing authentication rejects access.

### Edge Cases

- Empty buffer and no matching severity have explicit empty states.
- Failed log retrieval does not block forecast controls.
- Old entries are evicted; restart loses history; separate workers have separate histories.
- Failed persistence must not claim a completed update; cached reads are not updates.
- Untrusted content renders as text, not HTML.

## Requirements

### Functional Requirements

- **FR-001**: Provide a collapsed Logging section directly below General settings, with manual refresh and minimum severity filtering.
- **FR-002**: Retain at most 500 recent entries per service process, newest first; show at most 100 by default.
- **FR-003**: Entries contain UTC timestamp, INFO/WARNING/ERROR severity, component and a bounded safe summary.
- **FR-004**: Record completed forecast/configuration updates and provider/observation failures, including partial failures; also identify failed optional garden/soil updates and Azure verification. Preserve existing fallback behavior.
- **FR-005**: Never expose credentials, raw exceptions, request values or raw third-party logs.
- **FR-006**: Reuse existing local/public access policy; reject invalid severity and limits outside 1–500.
- **FR-007**: Log reads do not create entries or trigger weather updates.

### Key Entities

- **Activity entry**: Timestamp, severity, component and sanitized summary of an operational event.
- **Recent activity**: Bounded, ephemeral collection belonging to one service.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every tested refresh outcome and successful mutation category is visible after one log refresh.
- **SC-002**: All tested credential sentinels are absent from every log field.
- **SC-003**: Entry 501 evicts the oldest; filtering precedes limiting.
- **SC-004**: Logging remains readable and keyboard-operable at desktop and 390px mobile widths.

## Assumptions

- This is diagnostic activity, not a durable audit trail; no storage migration or new dependencies.
- Safe exception class names are sufficient cause categories; raw details remain in existing server diagnostics.
- Manual refresh is sufficient; optional live polling is not required.
- Related-project inspiration: ha_satellite uses bounded timestamped entries; e2proxy uses a maintenance log panel with refresh and severity selection. Preserve this project's existing visual design.

## Affected Surfaces and Compatibility

- **Surfaces**: Python service/adapters, optional garden/soil and Azure diagnostics, additive read-only API, responsive web UI, tests and help/README.
- **Compatibility**: Preserve all weather/provider/scoring, Home Assistant payloads, existing authentication and SQLite behavior.
- **Localization**: English and German logging guidance in existing README/help.
