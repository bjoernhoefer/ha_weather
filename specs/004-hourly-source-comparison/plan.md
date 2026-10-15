# Implementation Plan: Hourly Source Comparison

**Branch**: `004-hourly-source-comparison` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification in `specs/004-hourly-source-comparison/spec.md`

## Summary

Compare separately archived hourly forecasts from each weather provider with hourly readings from each configured outdoor Home Assistant temperature sensor. Keep source identities distinct, match in UTC, display local times using the location timezone, and retain up to 72 hours without changing existing consensus history or daily ranking behavior.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Existing FastAPI, Pydantic, httpx, SQLite, static HTML/CSS/JavaScript

**Storage**: SQLite; additive hourly provider forecast and hourly Home Assistant measurement tables

**Testing**: pytest, including existing offline HTTP mocks

**Target Platform**: Existing Python web service and responsive browser UI

**Project Type**: FastAPI web service with static web UI

**Performance Goals**: A 24/48/72-hour comparison uses bounded archived rows and at most one Home Assistant history request per configured outdoor sensor.

**Constraints**: No dependency additions; preserve current API/history behavior; never infer provider attribution from archived consensus; isolate individual sensor failures; use UTC for matching and location timezone for display.

**Scale/Scope**: At most 72 hours, current weather providers, and the existing configured-measurement limit per location; temperature only.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Preserve Existing Architecture**: PASS — extend existing provider/service/storage/API and static UI.
- **II. Treat Weather Data as Scientific Data**: PASS — persist provider and sensor identity, units, timestamps, forecast versus observation semantics, coverage, and missingness.
- **III. Protect Existing Contracts and Configuration**: PASS — additive tables and endpoint; leave existing history and scoring data unchanged; no synthetic backfill.
- **IV. Verify Behavior at the Right Risk Level**: PASS — tests cover persistence, matching, source isolation, timestamps, partial failures, and old contract compatibility.
- **V. Keep the Experience Lightweight and Accessible**: PASS — use existing static UI, semantic tables, accessible controls, textual ratings, and responsive layout.
- **VI. Keep User Documentation Understandable**: PASS — update the paired German and English Home Assistant measurement guides.

No constitution violations identified.

### Post-design check

- Separate forecast and observation histories avoid presenting a consensus as an individual provider or a merged sensor as an individual measurement.
- Existing consensus archive and `/api/history/{location_id}` remain untouched.
- Fresh provider-specific history is available after deployment; old consensus rows cannot be safely attributed and are not migrated.
- Retention remains bounded at 72 hours to match the existing hourly archive.

## Change Scope and Persona Selection

**Impact tier**: T3 — new time-series persistence and a source-specific verification contract cross storage, provider refresh, Home Assistant history, API, and UI.

**Affected surfaces**: Provider refresh and hourly forecast archival, SQLite storage, comparison API, Home Assistant history reads, responsive web UI, paired German/English documentation, backend/API/storage/UI tests.

**Personas consulted**:
- Python architecture — independent provider forecasts, source identity, UTC/retention, schema compatibility.
- Home Assistant enthusiast — per-entity history and interpretation, unit/hour aggregation, HA failure behavior.
- UI/UX developer — matrix/table information hierarchy, small-screen and accessible interactions.
- Quality and Documentation — acceptance coverage, edge cases, test and bilingual documentation scope.

**Personas not consulted**: EUMETSAT specialist; the feature compares ordinary provider forecasts and Home Assistant sensors and does not involve satellite products or nowcasting.

**Compatibility and risk notes**: Existing `hourly_predictions` stores consensus only and must remain unchanged. Add provider-keyed forecasts and per-sensor measurements; do not attribute legacy rows to providers. Preserve existing history and daily scoring. Convert provider and HA times to UTC for matching, render location-local time with timezone, retain new records for 72 hours, and preserve each HA instance/entity identity. No changes to HA setup/configuration or secrets.

## Project Structure

### Documentation (this feature)

```text
specs/004-hourly-source-comparison/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── source-comparison.md
└── tasks.md
```

### Source Code (repository root)

```text
app/
├── models.py
├── storage.py
├── service.py
├── main.py
├── obs_sources/home_assistant.py
└── static/index.html
tests/
├── test_storage.py
├── test_observations.py
├── test_service.py
└── test_api.py
docs/
├── home-assistant-measurements.de.md
└── home-assistant-measurements.en.md
```

**Structure Decision**: Extend the existing single FastAPI application; use additive SQLite tables, a focused API response model and service method, the current HA history adapter, and the existing static dashboard. Add tests alongside the relevant existing suites and keep user guidance aligned in both languages.

## Complexity Tracking

No constitution violations require justification.
