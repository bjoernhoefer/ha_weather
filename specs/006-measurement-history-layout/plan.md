# Implementation Plan: Measurement history layout

**Branch**: `copilot/update-measurements-overview` | **Date**: 2026-10-15
**Spec**: [spec.md](spec.md)

## Summary

Implement the approved separate sensor-history box using the existing HTML,
CSS and JavaScript. Keep lazy Recorder requests; replace the ordered list with
an accessible UTC/Celsius table and an explicitly requested inline SVG.

## Technical Context

- **Language/Version**: Existing browser JavaScript and Python test environment.
- **Primary Dependencies**: Existing FastAPI service; no new dependencies.
- **Storage**: Unchanged SQLite.
- **Testing**: Existing pytest suite and Node subprocess UI test pattern.
- **Target Platform**: Desktop/mobile responsive browsers.
- **Project Type**: Existing service with static web UI.
- **Performance Goals**: Zero history requests or SVG generation initially;
  no chart library, no extra request when plotting.
- **Constraints**: Maintain existing data validation, gap semantics and safe DOM
  rendering; no API or persisted-format changes.
- **Scale/Scope**: Per-sensor rolling 24-hour history only.

## Constitution Check

PASS before and after design: existing architecture retained, Recorder remains
distinct from forecast archives, compatibility preserved, focused offline tests,
accessible lightweight UI and paired documentation. No migration or new library.

## Change Scope and Persona Selection

**Impact tier**: T2 — meaningful UI interaction, no backend contract changes.
**Affected surfaces**: `app/static/index.html`, UI regression tests, DE/EN guides.
**Personas consulted**:

- UI developer: implement approved responsive layout and optional lazy SVG.
- Quality and Documentation: acceptance tests, regression evidence and paired guides.

**Personas not consulted**: Python architecture (no backend change), Home Assistant
enthusiast (Recorder payload and setup unchanged; source semantics checked inline),
EUMETSAT (no satellite products).

**Compatibility and risk notes**: Preserve test/edit/delete, lazy request guards,
finite/in-window/non-carried filtering and explicit gaps. Clear stale chart on
refresh failures; no credential rendering. Remove approval PNGs. Deployment is
not performed or claimed; release proposal only, no version bump without release.

## Project Structure

- Feature artifacts: `specs/006-measurement-history-layout/`.
- Production implementation: `app/static/index.html`.
- Regression tests: `tests/test_measurement_history_ui.py` plus existing suite.
- Guidance: `docs/home-assistant-measurements.de.md` and `.en.md`.

## Execution

1. Record bounded acceptance criteria and human preview approval.
2. Implement table/full-width history and optional chart.
3. In parallel update guides and derive focused tests, then run regression suite.
4. Remove PNGs, scan modified files, commit and run security/code review.

No constitution exceptions.
