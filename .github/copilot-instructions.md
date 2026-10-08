# Repository instructions

## Project context

`ha_weather` is a Python/FastAPI weather aggregation service with weather and
observation providers, SQLite persistence, a responsive static web UI, and a
Home Assistant REST API. The repository's current mobile experience is the
responsive web UI; do not assume a separate native mobile application exists.
Use the established `pytest` suite and inspect the relevant code and docs
before proposing changes.

## Automatic change triage

These routing rules apply to the coordinating agent. A delegated specialist
works only on its assigned question, reports out-of-scope impacts to the
coordinator, and must not start further persona reviews or repeat the full
Spec Kit workflow.

At the start of each implementation request, silently classify its actual
behavioral and operational risk, not just its file count. Select only the
personas whose expertise is relevant. If the change is clearly small, proceed
without invoking extra agents; apply the relevant checks inline. Do not ask the
user to choose personas. If scope or impact is genuinely ambiguous, state the
uncertainty and ask only when it could change behavior, compatibility, or risk.
When scope expands, reassess the tier before continuing. Higher-risk
indicators take precedence over lower-risk ones; a one-line contract or
authentication change is not a small/local change.

| Tier | Indicators | Persona handling |
| --- | --- | --- |
| **T0 — editorial** | Typo, formatting, or internal-only documentation change; no runtime, user workflow, contract, or configuration behavior changes. | No separate persona. Check links and rendered meaning inline. |
| **T1 — small/local** | One bounded concern with obvious behavior and no cross-surface effects, public contract change, persistence change, provider semantics, or elevated failure risk. | No subagent by default. Use the single relevant persona's checklist inline; run a focused check if executable behavior changed. |
| **T2 — meaningful** | Multi-file feature, non-trivial logic, or a change to a public API, provider, Home Assistant workflow, web UI, configuration, or user-facing documentation. | Consult each directly relevant specialist before or during implementation; consult Quality and Documentation for test scope and final evidence. Use Spec Kit artifacts when acceptance criteria, dependencies, or compatibility need to be tracked. |
| **T3 — high impact** | Forecast/scoring semantics, provider/data contract, stored-data format or migration, authentication, deployment, cross-layer contract, operational safety, or uncertainty with meaningful impact. | Use full Spec Kit flow and all relevant specialists. Quality and Documentation review is required. Verify compatibility and failure modes explicitly; surface unresolved domain/product decisions for maintainer input. |

### Persona routing

- **EUMETSAT specialist** — only for EUMETSAT products/services, satellite
  observations, satellite-derived weather/nowcasting, or a request that
  explicitly needs this domain. Not a default reviewer for ordinary forecast
  providers or generic weather logic.
- **Python architecture developer** — Python backend, provider/observation
  adapters, configuration, service/API logic, scoring, or storage.
- **Home Assistant enthusiast** — Home Assistant REST payloads, sensor meaning,
  entity examples, setup, or user workflows in Home Assistant.
- **UI developer** — `app/static/` presentation or interactions, responsive
  web behavior, accessibility, or UI states. Do not treat the REST sensor
  contract as a UI change unless the web UI is also affected.
- **Quality and Documentation** — mandatory consultation at T2/T3; also use
  for changed user-visible behavior, API/configuration guidance, or bilingual
  user documentation. Skip for T0 and uncomplicated T1 changes.

If a request has several affected surfaces, include the owners of those
surfaces, not every persona. For T2/T3, use custom agents as focused reviewers
when useful and available; give each a bounded question. For T0/T1, avoid
subagent overhead. Do not claim a custom agent ran unless it actually did.
Agent feedback is advisory; verify recommendations against source code,
official documentation, and executable tests.

### Required triage outcome

For every implementation request, report a concise triage outcome in the final
summary: impact tier, whether any personas were invoked, and which relevant
perspectives were handled inline. For T2/T3 work, also record the tier, affected
surfaces, selected personas, and any excluded relevant-looking personas in the
Spec Kit plan. Keep T0/T1 work itself lightweight; reporting the tier must not
create extra review work.

## Spec Kit use

Use `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` for meaningful new
features; use `/speckit-clarify`, `/speckit-checklist`, and `/speckit-analyze`
when uncertainty, impact, or cross-artifact consistency warrants them. Run
`/speckit-implement` and `/speckit-converge` for work tracked by feature
artifacts. For isolated low-risk fixes, normal inspect → change → test is
preferred over creating a feature spec.

Read `.specify/memory/constitution.md` and the active feature artifacts. Keep
feature scope bounded; do not write a specification for the whole legacy
application. Include only tests, persona reviews, and documentation tasks
appropriate to the triaged tier.

## Completion and documentation

Run checks that cover the changed behavior. State exact commands and their
real outcomes; never report unrun checks as passing. Update user-facing docs
for behavior, configuration, API, deployment, or Home Assistant changes.
Keep new or already paired user guides aligned in German and English. Avoid
creating translations for editorial/internal-only changes. Preserve the
repository's release proposal convention in `.github/pull_request_template.md`.
