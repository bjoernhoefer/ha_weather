# Implementation Plan: Risk-based Development Personas

**Branch**: `bjoernhoefer-add-speckit-personas` | **Date**: 2026-10-08
**Spec**: [spec.md](spec.md)

## Summary

Adopt bundled Spec Kit 1.1.1 for Copilot, define project principles and five
specialist profiles, and route by risk rather than file count. Keep the
application, dependencies, CI permissions, and deployment unchanged.

## Technical Context

- **Language/version**: Markdown instructions; bundled Bash scripts; Python 3.12
  for existing tests and validation.
- **Dependencies**: Existing test requirements; `specify-cli==1.1.1` via uvx
  for development-only CLI validation.
- **Storage**: No runtime storage change. Ignored `.specify/feature.json`
  records the active feature per checkout.
- **Testing**: Existing pytest, YAML/JSON/links validation, shell syntax,
  template resolution, isolated feature/plan/tasks script smoke test, CI.
- **Platform**: Copilot sessions in this repository; current Bash scripts
  target Linux/macOS.
- **Performance/scope**: No runtime impact; avoid subagent overhead for T0/T1.

## Constitution Check

Pass before and after design: no runtime or data-contract changes; reuse
existing architecture/tests; conditional specialists; paired German/English
guides; do not claim deterministic enforcement or unrun reviews.

## Change Scope and Persona Selection

- **Impact tier**: T2, developer workflow/configuration adoption.
- **Affected surfaces**: Repository instructions, Copilot profiles/skills,
  Spec Kit templates and scripts, developer documentation.
- **Personas consulted**: `quality-documentation`, read-only consistency review
  of risk routing, boundaries, and bilingual guides. Two findings were fixed:
  conditional checklist/analyze steps and configuration included in T2 examples.
- **Excluded**: Python architecture (no application Python logic); Home
  Assistant (no payload/setup change); UI (no presentation change); EUMETSAT
  (profile describes domain scope but introduces no satellite product).
- **Inline checks**: Official Spec Kit/Copilot configuration compatibility,
  YAML/JSON validity, scope expansion, delegated-review recursion prevention.
- **Compatibility**: Runtime contracts unchanged. Profile activation can need
  a CLI restart; personal profiles can override repository profiles.

## Project Structure

```text
.github/copilot-instructions.md
.github/agents/*.agent.md
.github/skills/speckit-*/SKILL.md
.specify/memory/constitution.md
.specify/templates/
.specify/scripts/bash/
docs/entwicklung.md
docs/development-workflow.en.md
specs/001-speckit-personas/
```

Use the generated Spec Kit layout; keep project-specific additions reviewable.
Local template/skill customizations must be preserved during upgrades.

## Verification and Delivery

Validate configuration and script outputs without creating a new branch or
touching runtime data. Run the existing tests. Commit on the current branch,
open a PR using the repository template, wait for CI and inspect review state.
Merge only with a clean, current PR head and no blockers, as the user requested.

The assistant-based routing itself is not deterministic; this adoption checks
instructions and tools, not a guarantee of future model behavior.
