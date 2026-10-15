# Tasks: Home Assistant Measurement Diagnostics

**Input**: [plan.md](plan.md), [spec.md](spec.md), research, data model and contracts.
**Tests**: Existing offline pytest and native-browser checks appropriate to T3.

## Phase 1: Setup

- [x] T001 Inspect constitution and relevant implementation in app/config.py, app/service.py, app/storage.py and app/static/index.html.
- [x] T002 Consult Python, Home Assistant, UI and Quality specialists and record compatibility decisions in specs/005-ha-measurement-diagnostics/plan.md.

## Phase 2: Foundation

- [x] T003 Define read-only diagnostic and legacy pairing contracts in specs/005-ha-measurement-diagnostics/contracts/measurements.md.

## Phase 3: US1 - Configure location once (P1, MVP)

**Independent test**: Save a paired instance and a sensor without a second location; restart old database without losing mappings.

- [x] T004 [US1] Add regression coverage for migration, legacy multi-location, mismatches, caps, restart and deletion in tests/.
- [x] T005 [US1] Add nullable instance location and idempotent persistence in app/config.py, app/models.py and app/storage.py.
- [x] T006 [US1] Derive paired measurement location and reject incompatible changes atomically in app/service.py and app/obs_sources/home_assistant.py.
- [x] T007 [US1] Move location selection to instance form and show inherited measurement location in app/static/index.html.

## Phase 4: US2 - Test sensor (P2)

**Independent test**: Valid Celsius state succeeds; invalid states, units, credentials and upstream failures remain safe and read-only.

- [x] T008 [US2] Add offline diagnostic success/failure/auth/no-write regressions in tests/.
- [x] T009 [US2] Add typed diagnostic model, strict exact-entity request and authenticated route in app/models.py, app/obs_sources/home_assistant.py, app/service.py and app/main.py.
- [x] T010 [US2] Add form/saved/environment sensor Test with independent pending/results and stale-response protection in app/static/index.html.

## Phase 5: US3 - Recent history (P2)

**Independent test**: History starts collapsed, loads only on expansion and shows bounded samples or explicit empty/error states.

- [x] T011 [US3] Add rolling-window, invalid-data and failure/auth history regressions in tests/.
- [x] T012 [US3] Add read-only strict Celsius Recorder history response and route in app/models.py, app/obs_sources/home_assistant.py, app/service.py and app/main.py.
- [x] T013 [US3] Add per-measurement collapsed lazy history, provenance, timestamps and refresh/error states in app/static/index.html.

## Phase 6: US4 - Cleaner headings (P3)

**Independent test**: No disclosure marker; Tab/Enter/Space still toggle native details.

- [x] T014 [US4] Hide standard/WebKit markers and preserve visible native summary focus in app/static/index.html.

## Phase 7: Cross-cutting

- [x] T015 [P] Update paired user guides docs/home-assistant-measurements.en.md and docs/home-assistant-measurements.de.md.
- [x] T016 [P] Update API/setup guidance in README.md and both languages in app/static/help.html.
- [ ] T017 Collect real regression/browser results, scan changed files for secrets and run automated review; record evidence in specs/005-ha-measurement-diagnostics/quickstart.md.
- [ ] T018 Compare implementation with spec/plan/tasks and resolve remaining gaps in specs/005-ha-measurement-diagnostics/tasks.md.

## Dependencies & Parallel Execution

Setup and contracts precede implementation. US1 supplies shared optional-location resolution; US2 and US3 then use it independently. US4 has no backend dependency. Backend and static UI implementation can proceed in parallel after contract agreement; documentation can proceed alongside both. Tasks editing the same source files are serialized within each specialist.

## Implementation Strategy

Deliver lossless pairing as MVP, then read-only Test and Recorder history, then marker polish and aligned documentation. Validate each slice with its narrow existing checks and finish with full relevant regression evidence. No new framework, dependency, polling process or scoring behavior.

## Phase 8: Convergence

- [x] T019 Reject explicit environment measurement locations conflicting with paired instances in app/config.py and cover valid named-environment pairing and multi-location upgrade attribution in tests/test_home_assistant_measurements.py per FR-003, US1/AC2 and Constitution II (partial, HIGH).
- [x] T020 Preserve legacy unpaired mode when editing instance credentials in app/static/index.html so multi-location installations can update tokens without incompatible pairing, per FR-002 and US1/AC2 (partial, MEDIUM; code-review finding).
