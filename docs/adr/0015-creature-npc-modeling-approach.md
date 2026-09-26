# ADR 0015: Creature and NPC modeling approach (open — needs a decision)

- **Status**: Proposed
- **Date**: 2026-09-25

## Context

The proposed product direction (`docs/PRODUCT_DIRECTION.md` §10) depends on a custom creature builder, NPC "detail levels" (narrative-only through fully-simulated), and party-specific encounter analysis. None of these are scheduled or built yet, but the modeling approach underneath them is a foundational decision that later work (and later migrations) would otherwise settle by accident — this ADR exists so that doesn't happen.

Two structurally different approaches were identified and neither has been chosen:

**Option A — Character entities with an explicit simulation/detail level.** Every NPC and creature is a `character.characters` row (the same class-table-inheritance branch player characters use), with a `simulation_level` (or similar) column controlling how much mechanical detail is populated — background/minor/supporting/major/central/fully-simulated, as sketched informally in this README's Character Model section. A tavern patron and a recurring villain are both characters, differing only in how much of the character mechanical model is filled in.

**Option B — Rules-level creature templates plus world-level creature instances.** Mirrors the platform's existing rules-definition/world-instance separation (ADR 0005): a `rules`-schema creature template (e.g. "Goblin") is a reusable mechanical definition, and a `core.entities`-rooted world instance (e.g. "Grik the Gatekeeper") references a template and carries only campaign-specific overrides and narrative attributes, the way `Longsword` (rules definition) and `The Blade of Saint Orra` (world instance) already relate.

## Decision

**Not yet decided.** This ADR intentionally records the alternatives rather than picking one, so that:

- NPC portrayal profiles, the creature builder, and encounter analysis are not implemented against an assumed model.
- The decision is visible to whoever schedules that work, instead of being made implicitly inside an unrelated migration or table-comment.

## Consequences of deferring

- No creature/NPC-detail-level work should begin in `docs/PLAN.md` until this ADR is updated to "Accepted" with a chosen option.
- Whichever option is chosen affects how `character.npcs.simulation_level_id` (present in the domain sketch but not yet backed by a table) and any future `rules`-schema creature-template tables relate to each other — reviewers should treat any migration that adds either as needing to reference this ADR's resolution first.

## References

- `docs/PRODUCT_DIRECTION.md` §10.
- ADR 0005 (separate rules definitions from world instances) — the precedent Option B extends.
- README.md "Character Model" section — the precedent Option A extends.
