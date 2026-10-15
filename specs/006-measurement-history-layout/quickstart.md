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
