# Implementation Plan: Home Assistant Entity Discovery and UI Alignment

**Branch**: `003-home-assistant-entity-discovery` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-home-assistant-entity-discovery/spec.md`

## Summary

Let users search Home Assistant entity friendly names and IDs after configuring an instance, select a result for the existing outdoor measurement workflow, and retain manual ID entry. Correct the first dashboard toolbar so its location selector and action buttons align consistently on desktop and mobile. No observation aggregation, scoring, persisted measurement, or existing weather contract changes.

## Technical Context

**Language/Version**: Python 3.11+ and browser-native HTML/CSS/JavaScript

**Primary Dependencies**: Existing FastAPI, Pydantic, httpx, static UI; no new dependencies

**Storage**: Existing SQLite instance and measurement storage; discovery results are transient

**Testing**: pytest using existing offline HTTPX MockTransport fixtures

**Target Platform**: Existing Linux-hosted FastAPI service and responsive web UI

**Project Type**: Web service with embedded static UI

**Performance Goals**: On-demand discovery completes within the configured outgoing-request timeout; entity search results remain responsive for ordinary Home Assistant installations.

**Constraints**: Use the saved instance credentials only on the server; require existing API authentication in public mode; validate HTTP(S) URLs without embedded credentials, allow local/private hosts, and do not follow redirects; don't return secrets or raw upstream error details; only mark numeric `sensor` entities with temperature device class and Celsius (`°C` or `C`) units selectable; preserve manual entry and existing measurement semantics.

**Scale/Scope**: One on-demand search request against one configured Home Assistant instance; no new storage or background process.

## Constitution Check

- **Architecture**: Pass. Reuse the current service, Home Assistant REST integration, FastAPI routes, and static UI.
- **Scientific data and contracts**: Pass. Selected entities use existing outdoor measurement and history semantics; no measurements are fabricated and existing forecast/REST payloads stay unchanged.
- **Configuration and persistence**: Pass. Discovery is transient and does not alter settings or SQLite schema.
- **Verification**: Pass. Add offline tests for result mapping, matching, errors, auth, and registration behavior; visually validate desktop/mobile toolbar changes.
- **Experience and accessibility**: Pass. Keep native form controls, keyboard-accessible selection, status feedback, responsive alignment, and existing manual entry.
- **Documentation**: Pass. Add aligned English and German instructions for entity discovery and source selection.

## Change Scope and Persona Selection

**Impact tier**: T2 — meaningful, cross-surface change to Home Assistant workflow, backend/API, responsive UI, and user documentation.

**Affected surfaces**: FastAPI/service and Home Assistant entity listing; authenticated web API; measurement form and dashboard toolbar; English and German Home Assistant guidance; offline tests.

**Personas consulted**:
- UI/UX developer — desktop/mobile toolbar symmetry, measurement-form integration, and accessibility.
- Home Assistant enthusiast — entity discovery, result usability, and Home Assistant failure behavior.
- Python architecture developer — backend layering, API errors, timeout handling, and offline tests.
- Quality and Documentation — regression coverage and bilingual user guidance.

**Personas not consulted**:
- EUMETSAT specialist — no satellite product, observation, or nowcasting behavior is affected.

**Compatibility and risk notes**: Existing measurement records, instance configuration, API key protection, weather forecasts, and `/api/homeassistant/{location_id}` are unchanged. Discovery uses Home Assistant's currently available states, not its full entity registry. Because history values are interpreted as Celsius without unit conversion, discovery must visibly distinguish and only enable numeric temperature-class sensor entities with Celsius units; other matching entities remain inspectable but cannot be selected. Validate the stored URL (HTTP(S), no embedded credentials), permit local/private hosts, and do not follow redirects so the bearer token is sent only to the configured endpoint. Discovery must not reveal long-lived tokens or upstream response bodies and must fail without modifying stored measurements.

## Project Structure

### Documentation (this feature)

```text
specs/003-home-assistant-entity-discovery/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── home-assistant-entities.md
└── tasks.md
```

### Source Code (repository root)

```text
app/
├── main.py                         # authenticated discovery route
├── models.py                       # entity result response model
├── service.py                      # stored instance lookup and HA request
├── static/index.html               # search/select flow and toolbar layout
└── obs_sources/home_assistant.py   # HA entity request/matching helper
docs/
├── home-assistant-measurements.en.md # English discovery instructions
└── home-assistant-measurements.de.md # German discovery instructions
tests/
├── conftest.py                     # deterministic HA entity API response
└── test_api.py                     # discovery contract and failure cases
```

**Structure Decision**: Extend the existing FastAPI service and embedded static UI; no separate application, frontend framework, or new storage abstraction.

## Complexity Tracking

No constitution violations.
