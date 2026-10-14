# Tasks: Home Assistant Entity Discovery and UI Alignment

**Input**: Design documents from `/specs/003-home-assistant-entity-discovery/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Add focused offline API tests for successful search, filtering, authentication, and upstream failures. Use the existing pytest suite and MockTransport; do not introduce new test tools.

**Organization**: Tasks are grouped by user story so discovery and toolbar alignment can be validated independently.

## Phase 1: Setup

**Purpose**: No project initialization is required; extend existing app/test structure.

- [x] T001 Record the T2 impact tier, affected surfaces, and selected/excluded personas in specs/003-home-assistant-entity-discovery/plan.md

## Phase 2: Foundational

**Purpose**: Reuse existing Home Assistant instance configuration, HTTP client, and API authentication; no shared infrastructure or migration is needed.

- [x] T002 Document the discovery result shape and protected endpoint contract in specs/003-home-assistant-entity-discovery/contracts/home-assistant-entities.md

## Phase 3: User Story 1 - Find and select a Home Assistant sensor (Priority: P1) 🎯 MVP

**Goal**: Search a configured Home Assistant instance for named entities and select one in the existing outdoor-measurement workflow.

**Independent Test**: With an offline mock Home Assistant response, query for `Garten`, confirm only case-insensitive friendly-name or entity-ID matches are returned with both ID and name and no token, then create a measurement using a returned ID.

### Tests for User Story 1

- [x] T003 [P] [US1] Add deterministic `/api/states` responses for `homeassistant.local` in tests/conftest.py
- [x] T004 [P] [US1] Add API tests for matching, empty results, token secrecy, missing/unconfigured instances, invalid URL/redirect handling, upstream failures/timeouts, public-mode API-key authentication, and non-temperature/non-numeric/non-Celsius result eligibility in tests/test_api.py

### Implementation for User Story 1

- [x] T005 [US1] Add a Home Assistant entity-result model with `entity_id`, display `name`, nullable `unit`, and a `selectable` eligibility flag in app/models.py
- [x] T006 [US1] Implement on-demand current-state retrieval, case-insensitive friendly-name/entity-ID matching, and temperature-class numeric Celsius eligibility in app/obs_sources/home_assistant.py
- [x] T007 [US1] Resolve an effective configured instance and invoke discovery via the injected HTTP client in app/service.py; distinguish timeout from other upstream errors without changing stored measurements
- [x] T008 [US1] Add the authenticated discovery route and map missing instance (404), missing/invalid instance configuration (409), upstream failure (502), and timeout (504) in app/main.py
- [x] T009 [US1] Add search and result selection to the Home Assistant measurement form in app/static/index.html; selecting a result fills the entity ID and display name while retaining manual entry and existing save behavior
- [x] T010 [P] [US1] Document Home Assistant measurement discovery and selection in the aligned English/German guide pair docs/home-assistant-measurements.en.md and docs/home-assistant-measurements.de.md
- [x] T010a [US1] Update English and German Home Assistant discovery guidance in app/static/help.html and link to the guide pair from README.md

**Checkpoint**: A user can discover and save a Home Assistant outdoor sensor without manually typing its ID; manual entry still works.

## Phase 4: User Story 2 - Keep dashboard controls visually aligned (Priority: P2)

**Goal**: Align the location selector and dashboard actions symmetrically without changing layout behavior of unrelated forms.

**Independent Test**: Inspect the first dashboard row at desktop and narrow mobile widths; selector and buttons align cleanly, wrap without clipping, and cause no horizontal overflow.

### Tests for User Story 2

- [x] T011 [P] [US2] Add a focused served-UI regression assertion for the toolbar-specific alignment hook in tests/test_api.py

### Implementation for User Story 2

- [x] T012 [US2] Add toolbar-scoped layout styles so the location selector and action buttons share a control baseline at desktop and wrap symmetrically on mobile in app/static/index.html

**Checkpoint**: The first row matches the intended symmetry at both wide and narrow viewport sizes without affecting other `.bar` forms.

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Validate both user journeys, documentation, and safety.

- [ ] T013 [P] Run the focused discovery/API tests and full pytest suite; record exact results
- [ ] T014 [P] Verify the English/German discovery guides and quickstart instructions agree in docs/home-assistant-measurements.en.md, docs/home-assistant-measurements.de.md, and specs/003-home-assistant-entity-discovery/quickstart.md
- [ ] T015 Run the quickstart validation and manually inspect the responsive first-row layout at desktop and mobile viewport widths

## Dependencies & Execution Order

### Phase Dependencies

- Setup and Foundational are documentation-only and can be completed first.
- User stories depend on the existing app, client factory, and test fixtures; no new blocking infrastructure is needed.
- User Story 1 and User Story 2 can be implemented independently after baseline context is loaded.
- Polish follows both user stories.

### User Story Dependencies

- **User Story 1 (P1)**: Independent; can deliver the discovery MVP.
- **User Story 2 (P2)**: Independent visual fix; does not depend on discovery logic.

### Parallel Opportunities

- T003 and T004 can be prepared in parallel before the backend implementation (both touch test files but separate test fixture/API test files).
- T006–T008 are sequential because the route uses the service, which calls the observation-source helper.
- T009 and T010 can be developed in parallel with the backend work once the contract is stable.
- T011 and T012 are sequential for the toolbar-specific UI assertion.
- User Story 2 can be done in parallel with backend tasks for User Story 1, but avoid concurrent edits to `app/static/index.html` (combine its search and toolbar changes in one edit).

## Implementation Strategy

### MVP First (User Story 1)

1. Add the offline fixture and contract tests.
2. Implement response mapping, safe instance lookup, HTTP request, and protected route.
3. Add the search/selection workflow, keeping manual ID entry available.
4. Update both language versions of Home Assistant guidance and validate tests.

### Incremental Delivery

1. Validate discovery (US1) independently with mock data and existing measurement creation.
2. Align the dashboard toolbar (US2) and inspect desktop/mobile behavior.
3. Run final tests, secret scan, and review/security validation.
