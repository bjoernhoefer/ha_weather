# Research: Home Assistant Entity Discovery and UI Alignment

## Decision 1: Discover the selected instance's current Home Assistant entities on demand

- **Decision**: Use the existing Home Assistant states REST resource through the configured instance URL and long-lived token. Return matching entity IDs, display names, units, and a safe eligibility flag; match case-insensitively against both friendly name and entity ID. Display every match, but enable selection only for sensor entities with a numeric current state and Celsius units.
- **Rationale**: The available states payload already contains the entity ID, current state, and attributes (including `friendly_name`), so the app can filter server-side without a new integration or changing entity state. Querying only after the user asks avoids automatic request traffic.
- **Alternatives considered**: Manually entering entity IDs only (fails the user's discovery request); querying Home Assistant directly from the browser (exposes the long-lived token and introduces cross-origin concerns); persisting every available entity (stale duplicate data and unnecessary schema changes).

## Decision 1a: Avoid selecting non-temperature and non-Celsius states

- **Decision**: Mark as eligible only `sensor` entities with a numeric current state and `unit_of_measurement` of Celsius (`°C` or `C`). Show other matches as not selectable and explain why. Preserve existing free-text entry unchanged.
- **Rationale**: The current HA history path converts states to numbers but does not convert or validate units; selecting humidity, Fahrenheit, or a non-numeric entity would silently pollute temperature observations and scores.
- **Alternatives considered**: Showing every result as selectable (incorrect measurement semantics); converting Fahrenheit in this feature (history API minimal response and persisted measurements do not store units, and this expands observation behavior beyond request); hiding all other matches (does not fulfill the request to see matches).

## Decision 2: Keep discovery on the authenticated service path and reuse the existing HTTP client

- **Decision**: Resolve the instance from existing effective Home Assistant settings, use the injected async HTTP client and configured request timeout, and protect the discovery route with the same API-key dependency used by existing settings routes. Convert upstream failures to a clear gateway error without returning upstream response bodies or credentials.
- **Rationale**: The service already owns access to stored instances, storage, and its mockable client factory. This preserves the existing authentication and request-timeout policy and avoids credential exposure to the browser.
- **Alternatives considered**: New HTTP client or dependency (unneeded); browser-side fetch (credential leak); logging raw upstream errors into user-facing activity logs (can disclose sensitive details).

## Decision 3: Preserve the existing manual measurement form and data semantics

- **Decision**: Provide search, result selection, and a way to fill the existing entity ID/name fields; keep manual identifier entry, location selection, scope selection, and the existing save action.
- **Rationale**: The persisted measurement model and observation source already implement the requested real-world outdoor measurements, and preserving their workflow avoids a schema migration or behavior change.
- **Alternatives considered**: A separate sensor persistence model (duplicates existing measurements); silently auto-saving on selection (skips location/scope confirmation and existing validation).

## Decision 4: Align the toolbar's control bottoms and consistent spacing

- **Decision**: Scope a layout adjustment to the top dashboard toolbar so the location label remains above its selector while the selector and action buttons share a clean control baseline; retain a balanced wrap at mobile widths.
- **Rationale**: The screenshot shows the selector and buttons shifted vertically due to the two-line location label. A toolbar-specific alignment avoids unintended effects on unrelated forms that reuse `.bar`.
- **Alternatives considered**: Globally changing `.bar` alignment (would affect measurement/settings forms); absolutely positioning controls (fragile across text and viewport sizes).

## Validation notes

- Existing tests are offline and use a shared HTTPX MockTransport fixture; add a route for Home Assistant state-list requests there.
- Test matching by friendly name and entity ID, case insensitivity, no-result behavior, token secrecy, inaccessible/unconfigured instances, public-mode auth, and successful measurement creation after selecting a result.
- Test the UI text/structure and inspect responsive toolbar styling; manual browser validation is supplemental to pytest.
- Existing Home Assistant user documentation is in `docs/home-assistant.md`; add a paired German guide so setup instructions remain aligned.
