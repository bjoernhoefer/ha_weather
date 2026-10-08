# Adoption Decisions

## Spec Kit and Copilot integration

**Decision**: Keep the official bundled Spec Kit 1.1.1 Copilot skills and Bash
scripts in the repository; pin CLI commands to the same version.

**Rationale**: Reproducible development tooling without runtime dependencies
or global installation requirements.

**Alternatives**: Handwritten replacement commands (unnecessary maintenance);
unversioned initialization (unreviewed upstream changes).

Sources: [existing-project adoption](https://github.github.com/spec-kit/guides/existing-projects.html),
[Copilot agents](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli).

## Persona boundaries

**Decision**: Risk-based coordinator routing; delegated roles do not recurse.
Include repository instructions in each profile.

**Rationale**: Avoid overhead and accidental review loops while retaining
contract-aware checks for meaningful changes.

**Alternatives**: Every persona for every change (excessive);
file-count-only routing (underestimates one-line contract changes);
mandatory CI routing enforcement (not requested and not provided).

## Satellite scope

**Decision**: Restrict EUMETSAT to explicit satellite/product/nowcasting work,
with product-specific official references.

**Rationale**: Generic weather code does not need satellite review; product
coverage, quality, attribution, and licensing cannot be assumed universally.

Sources: [MTG](https://www.eumetsat.int/meteosat-third-generation),
[NWC SAF](https://www.eumetsat.int/nwc-saf),
[User Portal](https://user.eumetsat.int/).
