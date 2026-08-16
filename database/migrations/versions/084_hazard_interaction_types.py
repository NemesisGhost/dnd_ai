"""Add disarm_trap/trigger_trap interaction types

Revision ID: 084_hazard_interaction_types
Revises: 083_schema_usage_grants
Create Date: 2026-08-16 00:00:00.000000

Purpose:
    Phase 10's vertical-slice acceptance scenario (docs/PLAN.md §25 step
    10, "Trigger or disarm the trap") needs a way for
    `dnd_ai.commands.interactions.resolve_check` to distinguish an
    intentional attempt to disarm a hazard from one that (successfully or
    not) sets it off — `interaction.interaction_types`' existing thirteen
    codes (revision 061: move, search, persuade, attack, cast_spell,
    use_item, activate_mechanism, pick_lock, rest, travel,
    read_inscription, converse, other) have no clean fit, the same way
    `pick_lock` itself was added as its own specific code rather than
    folding lock-picking into `use_item`. That table's own seed comment
    already documents it as "an illustrative starter set, extensible" —
    this is exactly that extension point, not a new mechanism.

    `campaign.hazard_statuses` already seeds the `triggered`/`disarmed`
    outcome vocabulary these two interaction types resolve to (revision
    040); this migration adds no new status vocabulary, only the two
    interaction-type codes the command layer dispatches on.

Forward migration:
    - INSERT ('disarm_trap', 'Disarm Trap') and ('trigger_trap', 'Trigger
      Trap') into interaction.interaction_types, continuing that table's
      existing sort_order sequence (13, 14).

Rollback:
    Supported. Deletes exactly the two rows this revision adds, by code —
    never a wildcard, in case a caller with the same codes already existed
    for another reason.

Data implications:
    Two new lookup rows. No existing row is altered, and no interaction
    ever referenced either code before this revision exists, so there is
    nothing to migrate.

Locking considerations:
    None beyond an ordinary short-lived row lock on
    interaction.interaction_types during the two INSERTs.

See: docs/DOMAIN_MODEL.md §16.1
     database/migrations/versions/061_interaction_domain.py (interaction_types)
     database/migrations/versions/040_dungeon_timeline_state.py (hazard_statuses)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "084_hazard_interaction_types"
down_revision = "083_schema_usage_grants"
branch_labels = None
depends_on = None

_NEW_INTERACTION_TYPES = [
    ("disarm_trap", "Disarm Trap", 13),
    ("trigger_trap", "Trigger Trap", 14),
]


def upgrade() -> None:
    """Apply the migration."""

    for code, display_name, sort_order in _NEW_INTERACTION_TYPES:
        op.execute(f"""
            INSERT INTO interaction.interaction_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)


def downgrade() -> None:
    """Revert the migration."""

    for code, _display_name, _sort_order in _NEW_INTERACTION_TYPES:
        op.execute(f"DELETE FROM interaction.interaction_types WHERE code = '{code}';")
