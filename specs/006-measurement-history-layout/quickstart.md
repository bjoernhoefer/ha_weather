# Validation

Use existing development dependencies from `requirements-dev.txt` and Node.js.

1. Run `python -m pytest tests/test_measurement_history_ui.py tests/test_home_assistant_measurements.py`.
2. Run `python -m pytest` for regressions.
3. In the configured dashboard, expand Real world measurements. Metadata should
   remain compact; open a sensor's separate history box beneath it.
4. Check sorted UTC date/time and Celsius columns, no numbering, refresh/retry,
   empty history and explicit gaps.
5. Request Show temperature trend. Check the curve and readings agree; recorded
   gaps interrupt it. Refresh must remove the old plot.
6. Inspect at 390 px and desktop width, light/dark mode and keyboard disclosure.
7. Confirm `preview-temporary/` is absent before opening a pull request.

No live release is triggered by these steps.

## Recorded evidence — 2026-10-15

Quality and Documentation specialist ran the final UI revision:

- `python -m pytest -q tests/test_measurement_history_ui.py tests/test_activity_ui.py tests/test_home_assistant_measurements.py`
  — 118 passed, 9.48 seconds.
- `python -m pytest -q` — 341 passed, 19.07 seconds; no failures or skips.
- Both runs have one existing third-party Starlette/AnyIO deprecation warning.
- `git diff --check` — clean.

UI specialist checked the actual page in headless Chrome via CDP at
320/375/640/900/1440/1920 px in light and dark modes: no viewport overflow,
balanced desktop columns, stacked mobile panels, correct pre-plot placeholder,
click-only SVG and refresh/error reset. Browser interaction/layout assertions
passed; this is not a claim of a screenshot-based visual review.

Secret scan: no secrets found. Parallel validation: CodeQL Python analysis
reported zero alerts; automated code-review binary was unavailable. A separate
read-only code-review agent reviewed the implementation and reported no
significant issues. This does not imply JavaScript-specific CodeQL coverage.

Convergence review: all 8 functional requirements, 5 success criteria,
7 acceptance scenarios, 3 design decisions and 6 constitution principles
are satisfied in the bounded implementation. No extra convergence tasks.
Both temporary approval PNGs are removed. No live deployment performed.

Release proposal: **1.2**, a measurement-history presentation feature.
Merge and successful main-branch CI/CD remain required for rollout.
