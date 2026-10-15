# Design decisions

- **Decision**: Keep history in a separate table row spanning seven columns.
  **Rationale**: Avoid stretching metadata/actions and match approved mock.
  **Alternative**: Entire sensor-card redesign rejected as unnecessary scope.
- **Decision**: Native table plus browser SVG on explicit click.
  **Rationale**: Accessible values remain useful without graph computation;
  no library download. **Alternative**: Chart library rejected for load cost.
- **Decision**: UTC chronological timestamps and gap-separated polylines.
  **Rationale**: Preserve existing Recorder semantics and avoid inventing data.
  **Alternative**: Hourly averaging or gap interpolation rejected.

No unresolved research questions or new contracts.
