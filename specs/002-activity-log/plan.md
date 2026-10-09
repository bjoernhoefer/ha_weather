# Implementation Plan: Recent activity log

**Branch**: Current task branch (unchanged) | **Date**: 2026-10-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-activity-log/spec.md`

## Summary

Add a bounded, service-owned activity buffer, an authenticated read-only endpoint,
and a collapsed Logging panel below General settings. Record only explicit safe
events, not arbitrary Python logs. Preserve weather behavior and existing access
policy; provide aligned English/German README and help guidance.

## Technical Context

**Language/Version**: Python 3.12 (container), existing HTML/CSS/JavaScript.
**Primary Dependencies**: Existing FastAPI, Pydantic and httpx; standard-library deque and lock.
**Storage**: Immutable entries in a locked deque, maximum 500; no SQLite changes.
**Testing**: Existing pytest suite and browser checks.
**Target Platform**: Existing Linux service and responsive desktop/mobile web UI.
**Project Type**: FastAPI web service with static frontend.
**Performance Goals**: Constant-time append/eviction; reads scan at most 500 entries.
**Constraints**: No dependencies, polling, durable audit trail, raw logger capture,
credential disclosure, or weather/authentication changes.
**Scale/Scope**: One buffer per WeatherService/process; one endpoint and one panel.

## Constitution Check

Pre-research and post-design gates pass by design:

- Preserve architecture: one small standard-library module and existing service/UI.
- Preserve scientific semantics: report outcomes without changing aggregation,
  scoring, observation meaning, fallback or provider concurrency.
- Preserve contracts: additive API only; unchanged configuration, authentication,
  SQLite and Home Assistant payloads.
- Verify risk: tasks cover secret sentinels, partial failures, persistence failure,
  boundaries, authentication and regressions; no checks claimed as already run.
- Lightweight access: native details/summary, manual refresh, keyboard controls,
  text-only rendering and 390px viewport validation.
- Documentation: update existing README/help in English and German.

## Change Scope and Persona Selection

**Impact tier**: T3 — cross-layer diagnostics with credential disclosure risk.
**Affected surfaces**: Service/provider and observation failure reporting, additive
API, responsive web UI, pytest and user-facing documentation.
Optional garden/soil and Azure verification catches also report safe failure events:
these already swallow errors, so exposing their categories completes diagnostics
without changing their existing results, fallbacks or scientific meaning.
**Personas consulted**: Python Architecture (ownership, concurrency, safe events and
compatibility); Quality and Documentation (acceptance tests, failure modes and
bilingual guidance). UI Developer is selected to implement/review the panel.
**Personas not consulted**: Home Assistant — sensor payloads/setup unchanged;
EUMETSAT — no satellite products or domain decisions.
**Compatibility and risk notes**: Fixed event templates and allowlisted identifiers
prevent submitted configuration, URLs and exception details entering the buffer.
Report success only after the existing operation completes. Preserve exceptions
and fallback behavior. No schema migration, environment variable or deployment
change. Restart/rollback discards ephemeral history; workers do not share logs.

## Project Structure

### Documentation (this feature)

```text
specs/002-activity-log/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── contracts/logs.md
├── quickstart.md
└── tasks.md
```

### Source Code (repository root)

```text
app/
├── activity.py                 # new bounded safe-event buffer
├── agro.py                     # optional indicator failure reporting
├── azure_foundry.py            # optional verification failure reporting
├── clock.py                    # reuse now_utc
├── service.py                  # buffer ownership and operation outcomes
├── observations.py             # optional safe failure reporting
├── obs_sources/
│   ├── base.py
│   ├── home_assistant.py       # swallowed per-instance failures
│   └── elasticsearch.py        # swallowed per-instance failures
├── main.py                     # GET /api/logs; existing protected dependency
└── static/
    ├── index.html
    └── help.html
tests/
├── test_activity.py            # new buffer tests
├── test_service.py
├── test_api.py
└── test_observations.py
README.md
```

**Structure Decision**: Extend the existing application in place. Thread an optional
failure reporter through observation orchestration/adapters so already swallowed
partial failures are visible without global handlers or changing fetch results.
Wrap provider calls only to record a safe category and re-raise unchanged.

## Complexity Tracking

No constitution violations or additional architecture exceptions.
