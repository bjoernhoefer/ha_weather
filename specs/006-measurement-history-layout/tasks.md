# Tasks: Measurement history layout

**Input**: [plan.md](plan.md), [spec.md](spec.md), supporting design artifacts.

## Phase 1: Setup

- [x] T001 Record human approval and bounded T2 scope in specs/006-measurement-history-layout/spec.md and plan.md.

## Phase 2: Foundation

- [x] T002 Verify existing lazy history and validation behavior in app/static/index.html.

## Phase 3: US1 — Read recent measurements (P1)

**Independent test**: Expand history; metadata stays compact and a separate
full-width chronological UTC/Celsius table appears.

- [x] T003 [US1] Add separate history row, accessible unnumbered table and mobile styles in app/static/index.html.
- [x] T004 [P] [US1] Cover lazy fetch, chronological filtering, gaps, errors and detached results in tests/test_measurement_history_ui.py.

## Phase 4: US2 — Optional trend (P2)

**Independent test**: Loaded table generates no SVG until requested; chart uses
the same window/data and breaks at gaps.

- [x] T005 [US2] Add on-click SVG with finite single/constant/negative data handling and refresh reset in app/static/index.html.
- [x] T006 [P] [US2] Test lazy chart, gap segmentation and stale-chart reset in tests/test_measurement_history_ui.py.

## Phase 5: Completion

- [x] T007 [P] Update paired docs/home-assistant-measurements.de.md and docs/home-assistant-measurements.en.md.
- [x] T008 Remove preview-temporary/measurements-desktop.png and preview-temporary/measurements-mobile.png.
- [x] T009 Run relevant and full existing pytest suite; record evidence in specs/006-measurement-history-layout/quickstart.md.
- [x] T010 Scan changed files and run code/security review; check convergence against specs/006-measurement-history-layout/spec.md.

## Dependencies and strategy

T001 → T002 → T003 → T005. Tests T004/T006 and documentation T007 can be
prepared in parallel in separate files; final execution follows UI readiness.
T008 is independent; T009/T010 follow implementation. Table-only US1 is the
MVP, but both approved stories are delivered together. No deployment or
additional API/provider/storage work.
