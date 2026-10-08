# Development Workflow and Persona Triage

## Purpose

This project uses GitHub Spec Kit to make requirements, plans, and tasks
traceable for substantial changes. Five Copilot agent profiles provide focused
expert perspectives. They are not five mandatory approval stages: involve
only the roles relevant to the change's scope and risk.

The profiles live in [`.github/agents/`](../.github/agents/). They are
instructions for AI agents, not a replacement for maintainer decisions or
review by actual meteorology or Home Assistant domain experts.

## Automatic triage

Copilot classifies each implementation request by behavioral and operational
risk, not just by the number of files changed. The rules are in
[`.github/copilot-instructions.md`](../.github/copilot-instructions.md).

| Tier | Examples | Workflow |
| --- | --- | --- |
| **T0 — editorial** | Typo or formatting with no runtime/user impact | No persona; check content and links directly. |
| **T1 — small/local** | Bounded change with no API, data, provider, or surface impact | Apply the relevant checklist inline; do not start a subagent for a trivial change. |
| **T2 — meaningful** | Multi-file feature, non-trivial logic, or API, provider, Home Assistant, UI, configuration, or user-doc change | Consult only relevant specialists; include Quality and Documentation review. Use Spec Kit when requirements or compatibility need explicit tracking. |
| **T3 — high impact** | Forecast/scoring semantics, data/API contract, persistence, authentication, deployment, or cross-layer change | Use full Spec Kit artifacts and all relevant roles; explicitly review tests, compatibility, and unresolved risks. |

When impact is ambiguous, classify conservatively. Ask the maintainer only if
the ambiguity could change a product decision, compatibility, or meaningful
risk. Never claim that an agent was consulted unless it actually was. The
completion summary states the tier and whether personas were invoked or handled
inline.

Selection is an AI decision guided by repository instructions, not a
technically enforced CI gate. Reassess when scope expands; higher risk takes
precedence over file count. Delegated personas stay within their assigned
task and do not start further persona reviews.

## Profiles and routing

| Profile | Use when ... | Usually skip when ... |
| --- | --- | --- |
| [EUMETSAT specialist](../.github/agents/eumetsat-specialist.agent.md) | EUMETSAT products/services, Meteosat/MTG, satellite observations, or satellite-based nowcasting are involved. | The change concerns generic weather providers or application code without a satellite-data connection. |
| [Python architecture](../.github/agents/python-architecture.agent.md) | Python backend, providers, API/service, configuration, scoring, or storage change. | Only copy, UI, or Home Assistant examples change without Python behavior. |
| [Home Assistant enthusiast](../.github/agents/home-assistant-enthusiast.agent.md) | REST sensors, payloads, units, entity examples, setup, or automations are affected. | Only independent web UI or provider internals change. |
| [UI/UX developer](../.github/agents/ui-ux-developer.agent.md) | Web presentation, responsive behavior, accessibility, or UI states change. | Only a backend/Home Assistant contract changes, with no presentation impact. |
| [Quality and Documentation](../.github/agents/quality-documentation.agent.md) | Tier T2/T3 or a user contract, behavior, operational step, or related documentation is affected. | T0 or an uncomplicated T1 change has no behavior/documentation effect. |

A profile may be invoked as a subagent for a bounded planning or review
question. Handle small changes without extra agents and apply the relevant
expert checklist inline. Keep new and already bilingual user guides aligned in
German and English; internal notes do not need translation.

## Spec Kit workflow

The [project constitution](../.specify/memory/constitution.md) records the
standing rules. For meaningful new features:

1. `/speckit-specify` — user outcome, acceptance criteria, and affected surfaces.
2. `/speckit-clarify` — resolve open decisions when needed.
3. `/speckit-plan` — architecture, compatibility, triage tier, and selected
   personas.
4. `/speckit-checklist` when ambiguity or higher risk warrants it; then
   `/speckit-tasks` — derive actionable work, tests, and documentation.
5. `/speckit-analyze` when uncertainty, higher risk, or cross-artifact
   consistency warrants it — find inconsistencies across spec, plan, and tasks.
6. `/speckit-implement` and `/speckit-converge` — implement and check for gaps
   until the work converges.

An isolated low-risk fix does not need a feature spec: inspect, make a bounded
change, and run the relevant check. Tests and persona consultations remain
risk-based even when Spec Kit is used.

## Setup and maintenance

The committed skills and scripts come from Spec Kit **1.1.1**; using them does
not require a global installation. For CLI commands:

```bash
uvx --from specify-cli==1.1.1 specify version
```

New Copilot sessions load repository instructions and agent profiles. The CLI
may need a restart; use `/agent` to check that the five profiles are offered.
Personal profiles with the same ID can override repository profiles.
Automatic agent selection has not been demonstrated through an unattended
end-to-end Copilot run.

Before upgrades, back up local constitution/template customizations and
review the resulting diff. `.specify/feature.json` is an ignored, checkout-local
pointer to the active feature, not a shared project setting.

## EUMETSAT domain sources

The EUMETSAT role verifies the specific product using official references and
distinguishes observations, derived products, and model forecasts. Useful
starting points:

- [Meteosat Third Generation](https://www.eumetsat.int/meteosat-third-generation)
- [Nowcasting SAF](https://www.eumetsat.int/nwc-saf)
- [EUMETSAT User Portal and product documentation](https://user.eumetsat.int/)

Coverage, latency, resolution, quality, licensing, and attribution must be
verified for the actual product in use.
