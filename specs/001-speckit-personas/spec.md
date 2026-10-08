# Feature Specification: Risk-based Development Personas

**Feature Branch**: `bjoernhoefer-add-speckit-personas`
**Created**: 2026-10-08
**Status**: Accepted for implementation
**Input**: Adopt Spec Kit and five specialist perspectives; automatically select
only necessary personas according to change size and risk.

## User Scenarios & Testing

### User Story 1 - Proportionate review (Priority: P1)

A maintainer requests a change without having to manually select specialists.

**Why this priority**: Avoid unnecessary review overhead without overlooking
high-impact behavior.

**Independent Test**: Review routing for a typo, local internal fix, visible
UI feature, Home Assistant payload change, and satellite-data feature.

**Acceptance Scenarios**:

1. **Given** an editorial typo, **when** the request is assessed, **then**
   no separate persona is required.
2. **Given** a one-line persisted-data or authentication change, **when**
   assessed, **then** risk overrides its small size.
3. **Given** an ordinary provider change without satellite data, **when**
   selecting roles, **then** EUMETSAT is not a default reviewer.

### User Story 2 - Traceable feature delivery (Priority: P2)

A maintainer can follow requirements, planning, tasks, and evidence for a
bounded feature and see which specialist perspectives were used.

**Why this priority**: Keep meaningful changes understandable and reviewable.

**Independent Test**: Follow the documented workflow and confirm that the
plan records affected surfaces, compatibility, and selected roles.

**Acceptance Scenarios**:

1. **Given** a meaningful cross-surface feature, **when** planned, **then**
   applicable specialists and quality review are recorded.
2. **Given** a small low-risk fix, **when** implemented, **then** a feature
   specification is not required merely to fix it.

### Edge Cases

- Ambiguous or expanded scope requires reassessment rather than silent
  low-risk classification.
- Unavailable specialist tooling must not be represented as a completed review.
- Delegated specialists must not recursively create further reviews.
- Personal agent profiles may override repository profiles.

## Requirements

### Functional Requirements

- **FR-001**: The workflow MUST define editorial, local, meaningful, and
  high-impact risk levels, with higher-risk indicators taking precedence.
- **FR-002**: The workflow MUST define five specialist profiles with explicit
  scope, exclusions, review criteria, and expected evidence.
- **FR-003**: Low-risk work MUST avoid unnecessary separate specialist reviews;
  meaningful/high-impact work MUST include applicable specialists and quality.
- **FR-004**: Feature plans MUST record risk, surfaces, compatibility, and
  consulted/excluded roles.
- **FR-005**: German and English workflow guidance MUST agree and explain
  activation and the limits of instruction-based automation.
- **FR-006**: Existing application behavior MUST remain unchanged by adoption.
- **FR-007**: Completion reports MUST distinguish invoked roles, inline
  perspectives, executed tests, and unverified behavior.

## Success Criteria

### Measurable Outcomes

- **SC-001**: All five profiles have distinct responsibilities and exclusions.
- **SC-002**: All five representative scenarios in User Story 1's independent
  test have an unambiguous expected review scope in the documented rules.
- **SC-003**: Both language guides describe the same four risk levels and
  conditional review steps.
- **SC-004**: Adoption changes no application, runtime dependency, API,
  stored-data, or deployment behavior.

## Assumptions

- The maintainer uses a coding assistant capable of reading repository
  instructions and invoking specialist profiles.
- Selection is assistant-guided, not deterministically enforced by CI.
- No native mobile application or satellite provider is introduced.

## Affected Surfaces and Compatibility

- **Surfaces**: Development tooling, instructions, templates, documentation.
- **Compatibility**: Runtime and existing integrations remain unchanged.
- **Localization**: New development guide is provided in German and English.
