# Feature Specification: Home Assistant Entity Discovery and UI Alignment

**Feature Branch**: `003-home-assistant-entity-discovery`

**Created**: 2026-10-14

**Status**: Draft

**Input**: User description: "Kannst du im UI schauen - das die erste zeile alle informationen gerade sind - das sieht sonst sehr schlampig aus. Bitte merke dir das symetrie in dem ganzen UI look wichtig ist. Ist es weiters möglich, das ich sobald ich den Longlived token von HomeAssistant eingetragen habe, eine query auf HomeAssistant schicke, das er nach gewissen Resourcen sucht (zb nach dem wort "Garten" und er mir alle Entitäten aufzeigt die im Name "Garten hat) und ich diese dann auswählen kann als Quelle der wirklichen Temperatur zu dienen?"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find and select a Home Assistant sensor (Priority: P1)

A user configures a Home Assistant instance with its URL and long-lived token, searches entity names for a word such as “Garten,” and selects a matching entity as an outdoor measurement for a location.

**Why this priority**: It removes the need to find and manually type entity identifiers and directly addresses selecting a real-world temperature source.

**Independent Test**: With a reachable Home Assistant instance and a matching entity, search by its displayed name, select it, and verify it appears as an outdoor measurement for the chosen location.

**Acceptance Scenarios**:

1. **Given** a saved Home Assistant instance with valid credentials, **When** the user searches for “Garten,” **Then** matching entity names and identifiers are shown without exposing the token.
2. **Given** matching entities are shown, **When** the user selects one and submits it for a location as an outdoor measurement, **Then** it is saved and appears in the measurements list.
3. **Given** no matching entities exist, **When** the search completes, **Then** the user sees a clear empty-result message and can change the search.

---

### User Story 2 - Keep the dashboard controls visually aligned (Priority: P2)

A user opens the weather dashboard and sees the location label, selector, and adjacent action buttons aligned cleanly and consistently, including on narrow screens.

**Why this priority**: A balanced first row improves the overall polish and supports the user's explicit preference for symmetry throughout the UI.

**Independent Test**: Inspect the dashboard at desktop and mobile widths and verify labels, selectors, and buttons share consistent alignment and spacing without clipping or awkward wrapping.

**Acceptance Scenarios**:

1. **Given** a desktop-width viewport, **When** the dashboard loads, **Then** the location control and action buttons align consistently within the same toolbar.
2. **Given** a narrow viewport, **When** the dashboard loads, **Then** controls wrap or stretch in a balanced way and remain usable without horizontal overflow.

### Edge Cases

- The configured instance has no URL or token, or the token is rejected.
- Home Assistant is unreachable or returns an unsuccessful response.
- A search term is empty or only whitespace.
- No entity name matches; matching is case-insensitive.
- Entity names contain non-ASCII characters or punctuation.
- The result list is large or includes entities that are not suitable temperature measurements.
- A user changes the Home Assistant instance after results have been fetched.
- Toolbar labels or button text wrap at small viewport widths.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to search entities belonging to a configured Home Assistant instance by a text term.
- **FR-002**: Search results MUST identify each entity by its Home Assistant entity identifier and display name.
- **FR-003**: Search MUST find case-insensitive occurrences of the term in an entity's display name or identifier.
- **FR-004**: The system MUST use the configured instance credentials for discovery and MUST NOT return or display the long-lived token in the results.
- **FR-005**: Users MUST be able to select a result and use it to create an outdoor measurement for a chosen location using the existing measurement workflow.
- **FR-006**: Discovery failures and empty results MUST be communicated clearly without discarding other saved instance or measurement configuration.
- **FR-007**: The dashboard's first toolbar row MUST present its location control and actions with consistent alignment, spacing, and responsive behavior.
- **FR-008**: Selecting an entity MUST retain the existing ability to enter or edit an entity identifier manually.

### Key Entities *(include if feature involves data)*

- **Home Assistant entity**: A remotely discovered entity identified by its entity ID and user-facing display name.
- **Outdoor measurement**: A selected Home Assistant entity associated with one configured instance and one location, used as a real-world outdoor observation source.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a successful discovery session, users can search for a display-name term and select a matching entity without manually typing its entity ID.
- **SC-002**: All returned search results include both a display name and a selectable entity identifier; no result includes the configured token.
- **SC-003**: An empty search result and a failed Home Assistant request each produce a distinct, understandable user-facing status.
- **SC-004**: The first dashboard toolbar remains fully usable and visually aligned at desktop and mobile viewport widths, with no horizontal overflow introduced by its controls.

## Assumptions

- Home Assistant entity discovery is available only for saved instances with a configured URL and token.
- Users may still enter an entity identifier manually when discovery is unavailable or an entity is not returned.
- Discovery results are used to configure the existing outdoor measurement workflow; this feature does not change how observations are aggregated or scored.
- Search is performed on demand and matches entity display names and identifiers without changing Home Assistant state.
- The visual alignment request refers to the dashboard's first control row shown in the supplied image.

## Affected Surfaces and Compatibility

- **Surfaces**: Backend/Home Assistant integration, protected web API, responsive web UI, and user documentation.
- **Compatibility**: Existing Home Assistant instance and measurement settings, observation behavior, manual entity entry, and public weather/Home Assistant response contracts remain unchanged.
- **Localization**: New user-facing discovery guidance must be reflected consistently in the paired English and German user guides.
