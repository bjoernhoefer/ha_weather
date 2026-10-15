# Validation Guide

## Prerequisites

Use the existing development requirements and pytest setup. Automated tests use offline HTTP mocks; manual source checks need a reachable configured Home Assistant installation with a Celsius temperature sensor and Recorder history.

## Backend regression

Run `pytest -q` from the repository root. Focused test commands and real outcomes are recorded in the completion evidence after implementation.

Verify old-database restart, single-/multi-location legacy mappings, instance pairing persistence, derived/mismatched locations, caps, location deletion, exact-entity diagnostics, invalid values/units, malformed history, timeouts, redirects, authentication and no writes from diagnostics.

## Browser acceptance

1. Create an instance with a location; add a sensor without selecting the location again.
2. Switch the dashboard location; confirm the sensor still belongs to its instance's location.
3. Test a valid sensor and an unavailable sensor; inspect value/time and safe failure feedback.
4. Confirm history starts collapsed; expand it to see recorder samples or a clear empty state, then refresh.
5. Confirm legacy multi-location records remain visible without silent reassignment.
6. Use Tab and Enter/Space on summary headings; verify toggles work without triangle markers and focus stays visible.
7. Repeat on a narrow viewport; check alignment and usable horizontal tables.

These checks do not change forecast/scoring semantics and must not be described as passing unless actually executed.

## Implementation evidence (2026-10-15)

Specialists ran their own checks; the coordinator did not repeat tests on
specialist-authored changes.

- Backend focused command:
  `/tmp/ha-weather-backend-venv/bin/python -m pytest tests/test_home_assistant_measurements.py tests/test_api.py tests/test_observations.py tests/test_storage.py -q`
  passed 182 tests after environment and upgrade compatibility refinements.
- Full command:
  `/tmp/ha-weather-backend-venv/bin/python -m pytest -q`
  passed 304 tests after typed usability reasons, strict-window corrections,
  environment validation and upgrade compatibility refinements.
- One existing Starlette/anyio dependency deprecation warning was reported.
- UI specialist checked JavaScript syntax, whitespace and isolated Chromium
  DOM/interactions at widths from 320 to 1440 pixels: inherited locations,
  collapsed lazy history, refresh/error/empty states, stale-response isolation,
  hidden markers, visible focus and native keyboard toggling.
- These are offline fixtures, not a live Home Assistant/Recorder smoke test.
  Firefox and WebKit were not exercised.
