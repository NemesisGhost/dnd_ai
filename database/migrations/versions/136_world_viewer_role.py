"""Add the read-only world_viewer world role

Revision ID: 136_world_viewer_role
Revises: 135_scrub_narrative_text
Create Date: 2026-10-06 20:00:00.000000

Purpose:
    Explicit read-only access to a world outside any campaign
    (docs/adr/0019-world-visibility-and-viewer-role.md). Until now
    `security.world_roles` held only `world_owner`, so the only way to see a
    world through `/worlds` was to be able to author it. `world_viewer`
    carries `world.view` and nothing else; the closed role -> capability
    mapping lives in `dnd_ai.domain.world_authority.WORLD_ROLE_CAPABILITIES`,
    exactly like `world_owner`'s (revision 110).

Forward migration:
    One explicit, idempotent INSERT of the `world_viewer` lookup row
    (`ON CONFLICT (code) DO NOTHING`). `database/seeds/security.world_roles.yaml`
    is revision 110's frozen input and is deliberately not edited
    (docs/DATABASE_CONVENTIONS.md §25.4); the row's content is frozen here.
    The table comment is updated to stop saying "currently world_owner".

    No grant changes: `security.world_roles` already carries the reporting
    and application grants from revisions 110/115, which are per-table, not
    per-row.

Rollback:
    Supported but destructive to viewer history: deletes every
    `security.world_memberships` row naming `world_viewer` (open or closed),
    then the role row. A viewer row is never an active owner, so the deferred
    owner-retention trigger has nothing to reject; its queued firings are
    drained immediately (§25.7) so a longer downgrade chain can still drop
    the table in revision 110.

Data implications:
    None for existing rows: no membership is created, changed, or ended. In
    particular no existing world_owner row is touched — remediation of a
    historical, pre-ADR-0018 owner is an explicit operator action
    (`scripts/manage_world_membership.py`), never a migration side effect.

Locking considerations:
    A single-row INSERT into a small lookup table.

See: docs/adr/0019-world-visibility-and-viewer-role.md
     src/dnd_ai/domain/world_authority.py (WORLD_ROLE_CAPABILITIES)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "136_world_viewer_role"
down_revision = "135_scrub_narrative_text"
branch_labels = None
depends_on = None

_TABLE_COMMENT_UPGRADED = (
    "Roles a user can hold on a world (world_owner, world_viewer). Capabilities are a "
    "closed mapping in application code (dnd_ai.domain.world_authority), not rows in "
    "security.capabilities, which is assignable to campaign roles "
    "(docs/adr/0014-world-authoring-authority.md, "
    "docs/adr/0019-world-visibility-and-viewer-role.md)."
)
_TABLE_COMMENT_PREVIOUS = (
    "Roles a user can hold on a world (currently world_owner). Capabilities are a "
    "closed mapping in application code (dnd_ai.domain.world_authority), not rows in "
    "security.capabilities, which is assignable to campaign roles "
    "(docs/adr/0014-world-authoring-authority.md)."
)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        INSERT INTO security.world_roles (code, display_name, description, sort_order, is_active)
        VALUES (
            'world_viewer',
            'World viewer',
            'May view the world, its timelines, and its calendars. Grants no authoring, '
            'archival, timeline, or campaign-creation authority.',
            20,
            true
        )
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute(f"COMMENT ON TABLE security.world_roles IS {_quote(_TABLE_COMMENT_UPGRADED)};")


def downgrade() -> None:
    """Revert the migration."""
    op.execute("""
        DELETE FROM security.world_memberships wm
        USING security.world_roles wr
        WHERE wr.world_role_id = wm.world_role_id AND wr.code = 'world_viewer';
    """)
    op.execute("SET CONSTRAINTS security.tr_world_memberships_retain_owner IMMEDIATE;")
    op.execute("DELETE FROM security.world_roles WHERE code = 'world_viewer';")
    op.execute(f"COMMENT ON TABLE security.world_roles IS {_quote(_TABLE_COMMENT_PREVIOUS)};")
