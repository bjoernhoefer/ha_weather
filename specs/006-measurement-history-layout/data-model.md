# Presentation data

Existing measurement payload and Recorder response are unchanged.

- Window: `start`, `end` timestamps.
- Samples: timestamp, finite Celsius `value`, optional `carried` flag.
- Gaps: timestamped unusable states.
- Presentation entries: non-carried samples and gaps inside the window,
  chronologically ordered. No persisted representation is added.
- State: collapsed/unloaded → loading → loaded or error; refresh invalidates
  existing plot; plot is generated only by an explicit button request.

Detached views ignore pending results.
