# ha_weather Constitution

## Core Principles

### I. Preserve the Existing Architecture
Build on the current FastAPI service, provider and observation adapters,
service layer, SQLite storage, static web UI, and Home Assistant REST contract.
Keep changes focused and modular. Add dependencies or abstractions only when
they solve a demonstrated need; do not introduce a second application or
framework for a small feature.

### II. Treat Weather Data as Scientific Data
Keep source identity, units, timestamps, time zones, forecast versus
observation semantics, coverage, and uncertainty explicit. Do not present
model-derived or satellite-derived information as a direct observation.
Handle provider failures and incomplete data without silently fabricating
values or allowing one source failure to break unrelated sources.

### III. Protect Existing Contracts and Configuration
Preserve public API response behavior, persisted data compatibility, existing
environment-variable configuration, and documented Home Assistant use unless
a specification explicitly authorizes a change. Identify migration, fallback,
and compatibility impacts before implementation; document breaking changes.

### IV. Verify Behavior at the Right Risk Level
Derive tests from acceptance criteria and changed behavior. For behavior
changes, cover the relevant success path, boundaries, and failure modes using
the repository's pytest suite and established CI checks. Run the narrowest
meaningful checks while iterating, then run the full relevant suite before
reporting completion. Never describe an unrun check as passing.

### V. Keep the Experience Lightweight and Accessible
Prefer the existing lightweight web UI and responsive HTML/CSS/JavaScript.
Treat mobile as responsive web unless a native application is explicitly
specified. Keep interactions fast, clear, keyboard accessible, and usable at
small viewport sizes. Ensure Home Assistant examples use accurate entity
semantics, values, units, and authentication guidance.

### VI. Keep User Documentation Understandable
Update user-facing documentation when behavior, configuration, API contracts,
deployment, or Home Assistant usage changes. For newly added or already
paired user guides, keep German and English versions aligned. Do not create
translation work for internal-only changes or claim translations are complete
without reviewing both versions.

## Development Constraints

- Runtime: Python and FastAPI; tests: pytest; persistence: SQLite.
- Follow established typing, validation, async, error-handling, and testing
  patterns in the affected modules.
- Do not add a native mobile client or frontend framework without an explicit
  feature requirement and an approved plan.
- EUMETSAT-specific decisions must cite authoritative product or service
  documentation and distinguish measured, derived, and forecast data.
- Feature artifacts belong under `specs/`; do not write a retroactive
  specification for the entire existing application.

## Workflow and Governance

- Classify each request using the risk-based persona triage in
  `.github/copilot-instructions.md`. Use only relevant personas; a persona is
  an AI review perspective, not a substitute for a human domain expert.
- Use the full Spec Kit path for meaningful, ambiguous, cross-surface, or
  high-risk features. Keep isolated low-risk fixes lightweight.
- Plans must identify affected surfaces, compatibility concerns, and persona
  selection (including why other personas are not needed).
- Tasks for behavior changes must include focused tests and appropriate
  documentation work. Review feature artifacts against implementation before
  declaring the work complete.
- A human maintainer decides product behavior, accepts domain risk, and
  approves releases. Do not infer approval from an agent review or a green test.

**Version**: 1.0.0 | **Ratified**: 2026-10-06 | **Last Amended**: 2026-10-06
