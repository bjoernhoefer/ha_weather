# Implementation Plan: Home Assistant Measurement Diagnostics

**Branch**: Current task branch | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

## Summary

Make location an instance-level setting for new UI configurations, preserve legacy mappings, and add read-only current-state diagnostics and lazy rolling recorder history. Hide disclosure markers without replacing native details controls.

## Technical Context

- **Language/Version**: Existing Python 3.11+ and native browser JavaScript.
- **Primary Dependencies**: Existing FastAPI, Pydantic, httpx; no additions.
- **Storage**: Add nullable location pairing to SQLite HA instances through an idempotent additive migration. Preserve measurement IDs and archived locations.
- **Testing**: Existing offline pytest suite; native browser accessibility and responsive checks.
- **Target Platform**: Existing Linux service and responsive web UI.
- **Project Type**: FastAPI web service with embedded static UI.
- **Performance Goals**: On-demand bounded requests using configured timeouts; no history fetch until expansion.
- **Constraints**: No token exposure, upstream redirects, raw exception messages, new scheduler, or forecast/scoring changes.
- **Scale/Scope**: One configured installation/entity per diagnostic request; last 24 hours of recorder data.

## Constitution Check

- Architecture: extend existing config, storage, service, source helper, API and UI.
- Scientific data: current state and recorder events are distinct; unsupported units and invalid values are not usable Celsius observations.
- Compatibility: old unpaired multi-location configurations remain intact; infer only a unique valid location; reject incompatible re-pairing.
- Verification: offline success/failure/migration/auth tests plus browser checks; report only actual outcomes.
- Accessibility: native keyboard-toggleable details and visible focus remain.
- Documentation: align English/German measurement guidance and embedded help.

All gates pass before implementation; verify again during convergence.

## Change Scope and Persona Selection

**Impact tier**: T3 — persisted configuration and cross-layer API/HA workflow change.

**Affected surfaces**: Python configuration/storage/service/source helpers, authenticated API, static settings UI, pytest tests, user documentation.

**Personas consulted**:
- Python architecture: implement and test additive persistence, derived locations and safe diagnostics.
- Home Assistant enthusiast: legacy multi-location compatibility, temperature eligibility, recorder provenance and failure behavior.
- UI/UX developer: implement responsive forms, stale-request handling, per-measurement diagnostics/history and marker-free accessible headers.
- Quality and Documentation: define migration/auth/failure regression evidence and bilingual documentation coverage.

**Personas not consulted**: EUMETSAT — no satellite products or nowcasting change.

**Compatibility and risk notes**: Optional instance location preserves existing explicit-location clients. Paired instances reject explicit mismatches; changes that would silently move existing measurements are rejected. Existing weather/HA forecast payloads, Elasticsearch configuration, archived observation identity and scoring remain unchanged. Diagnostics are read-only and authenticated through the existing API protection. Old databases gain only a nullable column; rollback does not require dropping existing records.

## Project Structure

- `app/config.py`, `app/models.py`: pairing and diagnostic contracts.
- `app/storage.py`: additive migration and pairing persistence.
- `app/service.py`, `app/obs_sources/home_assistant.py`, `app/main.py`: effective locations and safe source requests.
- `app/static/index.html`: instance pairing, Test/history, native summary styling.
- `tests/`: focused backend regressions using existing pytest infrastructure.
- `docs/home-assistant-measurements.{en,de}.md`, `README.md`, `app/static/help.html`: aligned user guidance.
- Feature artifacts: specification, research, data model, contracts, quickstart and tasks in this directory.

**Structure Decision**: Keep the existing modular backend and single static UI, without new frameworks or dependencies.

## Complexity Tracking

No constitution exceptions.
