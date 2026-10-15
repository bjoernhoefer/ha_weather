# Tasks: Hourly Source Comparison

**Input**: Design documents in `specs/004-hourly-source-comparison/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/source-comparison.md`

**Tests**: Add focused storage, Home Assistant history, service, and API tests. Run the existing `pytest -q` suite after implementation.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Parallelizable only when files and dependencies do not conflict.
- **[Story]**: User story this task implements.
- Every task has an exact repository file path.

## Phase 1: Setup

No project initialization or dependency changes are required; the feature extends the existing FastAPI service, SQLite storage, static UI, and pytest suite.

## Phase 2: Foundational

No shared infrastructure tasks are required. Existing storage initialization, authentication, provider refresh, and observation-source configuration are reused.

## Phase 3: User Story 1 - Compare hourly temperature forecasts (Priority: P1) 🎯 MVP

**Goal**: Show each individual provider forecast against every separately configured outdoor HA temperature sensor, without consensus or source mixing.

**Independent Test**: Seed two providers and two source-identified sensor readings for one UTC hour; verify all four pairs expose accurate values, signed/absolute errors, and rating, while missing data remains null.

### Tests for User Story 1

- [ ] T001 [P] [US1] Add provider-hourly and sensor-hourly archive tests for first-write preservation, UTC keys, 72-hour retention, and round trips in `tests/test_storage.py`.
- [ ] T002 [P] [US1] Add per-entity Home Assistant history tests for source separation, outdoor-only filtering, Celsius validation, non-finite readings, and partial failures in `tests/test_observations.py`.
- [ ] T003 [P] [US1] Add comparison API tests for multi-provider × multi-sensor results, signed/absolute error, rating thresholds, missing values, and unchanged `/api/history` in `tests/test_api.py`.

### Implementation for User Story 1

- [ ] T004 [US1] Add typed provider-source comparison response models in `app/models.py`.
- [ ] T005 [US1] Add additive provider-hourly-forecast and source-hourly-measurement tables, UTC-keyed save/read methods, first-provider-forecast preservation, per-measurement updates, and 72-hour cleanup in `app/storage.py`.
- [ ] T006 [US1] Fetch hourly Home Assistant history independently per configured outdoor entity; preserve stable instance/entity identity, verify Celsius temperature attributes, ignore non-finite states, and isolate individual request failures in `app/obs_sources/home_assistant.py`.
- [ ] T007 [US1] Archive each successful provider's individual hourly forecast during refresh without changing consensus archival in `app/service.py`.
- [ ] T008 [US1] Implement the bounded source-comparison service response, matching timestamps in UTC and computing pairwise error/assessment only when both values exist, in `app/service.py`.
- [ ] T009 [US1] Add the protected `GET /api/source-comparison/{location_id}` route with validated 24/48/72-hour windows in `app/main.py`.
- [ ] T010 [US1] Run focused storage, Home Assistant, service, and API tests and resolve failures in `tests/test_storage.py`, `tests/test_observations.py`, `tests/test_service.py`, and `tests/test_api.py`.

**Checkpoint**: All provider/sensor pairs are independently auditable through the additive API and existing history behavior remains intact.

## Phase 4: User Story 2 - Review a time range (Priority: P2)

**Goal**: Explore recent comparisons through a selected-hour matrix and a detailed hourly table, with readable local times and explicit empty/error states.

**Independent Test**: Select a supported time range and hour; confirm matrix values correspond to that hour, details cover the selected range, local time identifies the location timezone, and missing/empty data is described without relying on color alone.

### Tests for User Story 2

- [ ] T011 [P] [US2] Add API tests for supported period boundaries, timezone metadata, empty archive, and invalid period validation in `tests/test_api.py`.
- [ ] T012 [P] [US2] Add dashboard-serving regression assertions for accessible matrix/table controls and existing history section preservation in `tests/test_api.py`.

### Implementation for User Story 2

- [ ] T013 [US2] Add a responsive accessible source matrix, 24/48/72-hour selector, selected-hour control, detailed rows for the selected period, local timezone formatting, textual error ratings, and distinct loading/empty/error states in `app/static/index.html`.
- [ ] T014 [US2] Document the independent hourly comparison, Celsius requirement, error interpretation, retention, missing data, and source setup in `docs/home-assistant-measurements.de.md`.
- [ ] T015 [US2] Keep the English Home Assistant measurement guide aligned with the feature scope and setup semantics in `docs/home-assistant-measurements.en.md`.
- [ ] T016 [US2] Update the user-facing API/history overview to distinguish provider-specific hourly comparisons from consensus history in `README.md`.
- [ ] T017 [US2] Verify paired documentation consistency, responsive narrow-screen presentation, keyboard operation, and the 24/48/72-hour quickstart in `specs/004-hourly-source-comparison/quickstart.md`.

**Checkpoint**: Users can select a bounded recent period and inspect a clear, usable matrix and detail table on desktop and mobile.

## Phase 5: Polish & Cross-Cutting Concerns

- [ ] T018 [P] Run focused tests and the complete `pytest -q` suite; record actual results in the task summary using `tests/`.
- [ ] T019 [P] Review the implementation against API/data-model contracts and verify changed files for secrets using the repository file paths in the implementation diff.

## Dependencies & Execution Order

### Phase dependencies

- Setup and Foundational do not require code changes for this feature.
- US1 implements the source-separated archive and API; US2 depends on its response and is therefore sequential.
- Polish depends on both user stories.

### User story dependencies

- **US1 (P1)**: Independent MVP; delivers the provider × sensor comparison API.
- **US2 (P2)**: Depends on US1 API and source identities; delivers the dashboard workflow and documentation.

### Parallel opportunities

- T001, T002, and T003 can be authored in parallel because they touch separate test files.
- US1 model/storage and HA adapter tests can be developed independently before service integration.
- T011 and T012 can be authored in parallel because they touch separate test cases in the same file only if coordinated; otherwise perform sequentially to avoid conflicts.
- The German and English guides (T014/T015) may be updated in parallel.

## Implementation Strategy

### MVP First

1. Add tests and implement US1.
2. Validate source identities, UTC matching, null behavior, and unchanged consensus history.
3. Add US2 matrix/table interactions and bilingual user guidance.
4. Run the full test suite and review the feature against the data/API contracts.

### Incremental delivery

- US1 supplies the auditable comparison dataset and endpoint.
- US2 adds the dashboard controls and documentation without changing US1 semantics.

## Notes

- Existing consensus forecasts must never be copied into source-specific rows.
- Treat one Home Assistant instance/entity pair as one source; never average distinct sensors together.
- Keep temperature thresholds explicit: `good` ≤1 °C, `check` >1 °C and ≤2 °C, `large` >2 °C.
- Do not add runtime or test dependencies.
