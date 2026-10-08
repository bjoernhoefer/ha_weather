# Tasks: Risk-based Development Personas

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md)
**Tests**: Configuration/script validation and existing regression tests.

## Phase 1: Setup

- [x] T001 Initialize official Spec Kit 1.1.1 Copilot skills in `.github/skills/` and infrastructure in `.specify/`.

## Phase 2: Foundational

- [x] T002 Define architecture, compatibility, testing, and documentation principles in `.specify/memory/constitution.md`.

## Phase 3: US1 - Proportionate Review

**Goal**: Select only necessary review perspectives by impact.
**Independent test**: Review all five routing examples in `quickstart.md`.

- [x] T003 [US1] Define T0-T3 coordinator routing, scope reassessment, and no recursive delegation in `.github/copilot-instructions.md`.
- [x] T004 [P] [US1] Define five scoped profiles with inherited instructions in `.github/agents/*.agent.md`.
- [x] T005 [US1] Validate YAML/frontmatter and routing examples against `.github/copilot-instructions.md` and `quickstart.md`.

## Phase 4: US2 - Traceable Feature Delivery

**Goal**: Use proportionate feature artifacts and compatible guidance.
**Independent test**: Resolve templates and exercise feature/plan/tasks scripts
in an isolated copy; compare German and English guides.

- [x] T006 [P] [US2] Add risk/persona/compatibility fields and test obligations in `.specify/templates/{spec,plan,tasks}-template.md` and `.github/skills/speckit-tasks/SKILL.md`.
- [x] T007 [P] [US2] Add aligned German/English workflow guides in `docs/entwicklung.md` and `docs/development-workflow.en.md`; link from `README.md`.
- [x] T008 [US2] Record bounded adoption spec, plan, research, and validation scenarios in `specs/001-speckit-personas/`.
- [x] T009 [US2] Verify shell syntax, template resolution, plan/tasks prerequisites, JSON, links, and script workflow in `.specify/` and record results in `quickstart.md`.

## Phase 5: Verification and Delivery

- [x] T010 Consult Quality/Documentation on `.github/` workflow guidance and both language guides; fix actionable findings.
- [x] T011 Run `.venv/bin/python -m pytest -q` and whitespace checks for this change; record exact outcomes in `quickstart.md`.
- [x] T012 Prepare validation evidence and release guidance for the PR in `quickstart.md`, using `.github/pull_request_template.md`.

## Dependencies and Parallel Opportunities

T001 precedes T002 and the script checks. T003/T004 precede T005.
T006/T007/T008 precede T009. T010 reviews the guides and routing before T012;
T011 also precedes T012. US1 and US2 can progress independently after setup
and principles. Profile drafting (T004) can run alongside routing (T003);
template updates (T006) and documentation (T007) can run in parallel.

## Implementation Strategy

Deliver routing/profiles first, then traceable feature templates and guides.
Preserve runtime behavior, validate the tools and existing tests, then commit
and require green PR CI before the user-authorized merge.

Commit, PR creation, CI monitoring, and merge are delivery operations, not
implementation acceptance criteria; check their live status on GitHub.
