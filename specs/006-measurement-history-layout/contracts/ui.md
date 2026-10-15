# Measurement history UI contract

- Existing measurement row and action behavior remain intact.
- Immediately following history row spans all seven measurement columns.
- Disclosure requests existing read-only measurement history endpoint only when
  opened. No server/API contract change.
- History table: Date and time (UTC), Temperature (°C), oldest first; gaps
  are readable without a chart. No ordered list or ordinal column.
- Optional Show temperature trend button uses loaded data; SVG uses the
  complete window and never bridges an explicit recorded gap.
- Loading/error/empty states are announced; retry and refresh remain available.
- Equal desktop panels stack at mobile widths with aligned edges.
