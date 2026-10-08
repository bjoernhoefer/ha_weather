# Adoption Validation

From the repository root:

```bash
uvx --from specify-cli==1.1.1 specify version
for script in .specify/scripts/bash/*.sh; do bash -n "$script" || exit; done
.specify/scripts/bash/resolve-template.sh plan-template --json
.specify/scripts/bash/create-new-feature.sh --dry-run --json \
  --short-name speckit-personas "Adopt Spec Kit with risk-based persona selection"
.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
.venv/bin/python -m pytest -q
git diff --check
```

The CLI version should be 1.1.1. Templates should resolve as valid JSON with
persona scope guidance. Dry-run must not change the Git branch or active
feature. Prerequisites must find the adoption spec, plan, and tasks.

Install test dependencies in a local virtual environment if absent:
`uv venv .venv` and
`uv pip install --python .venv/bin/python -r requirements-dev.txt`.

Review profile/skill frontmatter and JSON manifests; check relative links in
new guides and feature artifacts. An isolated copy of `.specify` can exercise
feature creation, setup-plan, setup-tasks, and prerequisite resolution without
changing this checkout.

Review the following expected selections against the routing rules:

| Request | Tier | Expected perspectives |
| --- | --- | --- |
| Internal typo | T0 | Inline editorial check, no agent |
| Bounded internal helper fix without contract changes | T1 | Inline Python check and focused test |
| Visible responsive UI feature | T2 | UI and Quality/Documentation |
| Home Assistant payload contract change | T3 | Python, Home Assistant, Quality/Documentation |
| Satellite-derived nowcasting backend feature | T3 | EUMETSAT, Python, Quality/Documentation; HA/UI only if those surfaces change |

These are rules-review cases, not proof of autonomous model routing. Start a
new Copilot session and check `/agent` to confirm profile discovery; personal
profiles with matching IDs can override repository definitions.

## Recorded adoption evidence (2026-10-08)

- `python3 -m pytest -q`: initially failed because pytest was absent. Restored
  dependencies using the virtual-environment commands above.
- `.venv/bin/python -m pytest -q`: **164 passed, 1 skipped**, one dependency
  deprecation warning.
- `uvx --from specify-cli==1.1.1 specify version`: **passed**, reports 1.1.1.
- Bash syntax loop above: **passed** for all six scripts.
- Template resolution, dry-run feature creation, setup-plan, setup-tasks,
  and prerequisite checks: **passed**. The local feature pointer resolves this
  adoption feature without renaming the current branch.
- `.venv/bin/python -` with an inline validation program: **passed** for all
  five agent profiles and ten skills (YAML), JSON manifests, workflow YAML,
  relative links, and whitespace. Also exercised actual feature creation,
  plan, tasks, and prerequisites in a temporary isolated `.specify` copy;
  the copy was removed afterwards.
- `git diff --check`: **passed**.
- Quality/Documentation review: two guide inconsistencies corrected. Expected
  routing scenarios reviewed directly against the instructions.
- Autonomous Copilot routing and production deployment: **not tested**.
  CI/application container validation is checked separately on the PR.

Release proposal: no application version bump for development-workflow-only
adoption. Preserve `app/static/version.json` until an application release.
