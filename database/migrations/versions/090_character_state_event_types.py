"""Add non-combat character-state narrative.event_types

Revision ID: 090_character_state_event_types
Revises: 089_foundry_system_credentials
Create Date: 2026-08-18 22:30:00.000000

Purpose:
    Phase 11 ("Foundry MVP") workstream 6, the last remaining "synchronize
    the minimum required character HP, conditions, resource use" gap:
    `campaign.character_state.current_hit_points` has exactly one writer
    (`dnd_ai.commands.encounters._resolve_combat_turn_impl`, combat-turn
    damage only), and `campaign.character_conditions`/
    `.character_resources` have no writer at all — confirmed by a full
    grep of `src/dnd_ai/commands`. Healing, non-combat HP adjustment
    (falling, a trap, environmental damage), applying/removing a
    condition outside combat, and resource-use tracking (spell slots, ki,
    rage uses, ...) have no command-layer path today.

    `dnd_ai.commands.character_state` (this revision's companion code
    change, no migration of its own — it only writes, never alters
    schema) needs one new `narrative.event_types` code per operation, the
    same "state changes need a causal event" contract every other
    command in this codebase already follows (CLAUDE.md rule 6,
    `dnd_ai.commands.encounters`/`movement`'s own `_insert_event_row`
    calls). None of the four exist in the seed set migrations 057/073/
    076/077/078 already established — confirmed by grepping every
    `INSERT INTO narrative.event_types` in `database/migrations/versions/`.

Forward migration:
    `narrative.event_types`, four new rows (`ON CONFLICT (code) DO
    NOTHING`, matching every prior addition's own idempotent-seed shape):
      - `hit_points_adjusted` (sort_order 120) — one code covers both
        healing and non-combat damage; the direction is already captured
        by `narrative.event_effects.previous_value`/`.new_value` on the
        resulting row, the same way `campaign_id`/`session_id` NULL-vs-set
        already distinguishes campaign-scoped from administrative writes
        elsewhere, so a second `hit_points_reduced`-style code would only
        duplicate information the effect row already carries.
      - `condition_applied` (sort_order 121)
      - `condition_removed` (sort_order 122)
      - `resource_adjusted` (sort_order 123) — same single-code reasoning
        as `hit_points_adjusted`: a resource use vs. a resource restore
        differs only in the sign of the delta, already visible in the
        effect row's `previous_value`/`new_value` pair.

Rollback:
    Supported. Deletes the four rows by code.

Data implications:
    Four new lookup rows. No existing row is altered, and nothing
    references these codes until `dnd_ai.commands.character_state`'s own
    commands run for the first time.

Locking considerations:
    Four single-row inserts into a small, already-existing lookup table.
    No lock on any other table.

See: database/migrations/versions/078_encounter_domain.py
     (`combat_damage_dealt` — the closest existing precedent: one new
     `event_types` row added by a later, focused migration rather than
     the original 057 seed list)
     src/dnd_ai/commands/character_state.py (this migration's only
     consumer)
     src/dnd_ai/commands/encounters.py, src/dnd_ai/commands/movement.py
     (the existing `_insert_event_row` callers this module's own commands
     mirror)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "090_character_state_event_types"
down_revision = "089_foundry_system_credentials"
branch_labels = None
depends_on = None

_NEW_EVENT_TYPES: tuple[tuple[str, str, int], ...] = (
    ("hit_points_adjusted", "Hit Points Adjusted", 120),
    ("condition_applied", "Condition Applied", 121),
    ("condition_removed", "Condition Removed", 122),
    ("resource_adjusted", "Resource Adjusted", 123),
)


def upgrade() -> None:
    """Apply the migration."""

    for code, display_name, sort_order in _NEW_EVENT_TYPES:
        op.execute(f"""
            INSERT INTO narrative.event_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)


def downgrade() -> None:
    """Revert the migration."""

    codes = ", ".join(f"'{code}'" for code, _, _ in _NEW_EVENT_TYPES)
    op.execute(f"DELETE FROM narrative.event_types WHERE code IN ({codes});")
