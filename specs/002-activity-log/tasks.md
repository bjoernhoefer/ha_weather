# Tasks: Recent activity log

Unchecked tasks represent implementation still to do. Preserve existing weather,
storage and authentication semantics; no dependencies or migration.

## Phase 1: Setup

Context, contract and risk review are complete; no project initialization needed.

## Phase 2: Backend foundation and API

- [ ] T001 Implement `app/activity.py`: frozen entry, fixed safe templates/labels,
  allowlisted exception categories, enforced 64/240-character bounds, UTC clock,
  locked deque(maxlen=500), immutable snapshot and filter-before-limit retrieval.
- [ ] T002 Add `tests/test_activity.py` for empty state, bounds, UTC timestamps,
  equal-timestamp insertion order, 501st-entry eviction, severity filtering before
  limit, immutable entries, concurrent append/read safety and service isolation.
- [ ] T003 Add WeatherService buffer ownership and GET `/api/logs` in `app/main.py`
  with existing protected auth, validated level/limit defaults, JSON array and
  `Cache-Control: no-store`; test in `tests/test_api.py` including 1/500 limits,
  invalid enum/noninteger/0/501, local access, public absent/invalid/valid header
  and Authorization credentials and side-effect-free reads.

## Phase 3: See recent updates — US1 (P1)

Independent test: refresh a forecast and change configuration; inspect safe timestamped outcomes.

- [ ] T004 [US1] Instrument `app/service.py` refresh/provider calls with fixed completion/failure
  events. Emit completion after persistence/cache update only; record safe causes
  and preserve existing exceptions, concurrency and fallback behavior.
- [ ] T005 [US2] Add optional safe failure reporting through `app/observations.py` and
  observation adapters, including swallowed Home Assistant/Elasticsearch
  per-instance and relevant hourly-history failures. Keep healthy results and
  existing callers compatible; never include instance IDs or requests.
- [ ] T006 [US1] In `app/service.py`, record successful configuration mutation categories listed in
  `data-model.md`, only after completion; skip rejected changes/no-op deletions
  and never interpolate submitted values.
- [ ] T007 [US1] Extend `tests/test_service.py` and `tests/test_observations.py` coverage for completed refresh,
  provider failure, overall failure, partial observation success, persistence
  failure without completion, each successful mutation category and rejected
  changes. Assert cached forecast/log reads add nothing.
## Phase 4: Diagnose failures — US2 (P1)

Independent test: fail one source; retrieve WARNING/ERROR activity without exposing sentinel secrets or losing healthy results. T005 supplies source-level instrumentation.

- [ ] T008 [US2] Add adversarial sentinel tests in `tests/test_activity.py` and `tests/test_api.py` across all serialized fields: submitted
  names/IDs, API keys, tokens, URLs, request/response bodies, exception strings
  and custom exception class names; unknown types must use a safe fallback.

## Shared responsive UI

- [ ] T009 [P] [US1] UI Developer implements collapsed Logging directly below General
  settings in `app/static/index.html`: first-open fetch, manual refresh,
  minimum-level select, bounded newest-first entries via authenticated helper,
  no-store fetch, loading/empty/no-match/generic error states and textContent.
- [ ] T010 [US2] Perform browser checks of `app/static/index.html` at desktop and 390px: initial collapse,
  first-open/manual refresh and filters, keyboard controls, readable layout,
  hostile content as text, failed fetch isolation, no hidden polling and existing
  public-auth workflow. Record evidence and fix regressions.

## Final phase: Documentation and completion

- [ ] T011 Update existing `README.md` and `app/static/help.html` with aligned
  English/German Logging guidance, safe summaries, severity/filter behavior,
  defaults/cap, authentication and restart/per-worker ephemeral limitations.
- [ ] T012 Run focused pytest command from `quickstart.md`, then full relevant
  regression suite; record exact commands/outcomes and resolve failures.
- [ ] T013 Python Architecture and Quality/Documentation review `app/activity.py`, `app/service.py` and `app/static/help.html` for final safety,
  compatibility, coverage and bilingual guidance; incorporate UI evidence.
  Run final code/security validation and resolve findings.
- [ ] T014 Converge `specs/002-activity-log/tasks.md` against FR-001–FR-007 and SC-001–SC-004,
  update completed tasks and any remaining work; report T3/persona selection
  and retain `.github/pull_request_template.md` release proposal convention.

## Dependencies

T001 → T002/T003/T004; T004 → T005/T006 → T007/T008.
T003 → T009 → T010. T011 may proceed alongside UI implementation after API/event
decisions are stable. T002/T003/T007/T008/T010/T011 → T012 → T013 → T014.
Backend and UI work can proceed independently after the API contract is fixed.

## Implementation strategy and parallel examples

Deliver the safe buffer/API and US1 update events first, then US2 source-failure coverage. After the contract is fixed, backend work in `app/` can run alongside UI work in `app/static/index.html`; documentation in README/help can proceed independently. Finish with shared tests, browser evidence and review.

## Phase 5: Convergence

- [ ] T015 Update `specs/002-activity-log/quickstart.md` to include `tests/test_activity_backend.py` and `tests/test_activity_ui.py` in focused verification per T012 and plan: testing (partial).
- [ ] T016 Review and justify safe garden/soil/Azure failure reporting in `app/agro.py` and `app/azure_foundry.py`; align `specs/002-activity-log/spec.md`, `plan.md`, `data-model.md` and README/help with the accepted diagnostic scope per plan: named touch-points (unrequested).
