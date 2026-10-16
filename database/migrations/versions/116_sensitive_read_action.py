"""Add the audit.change_actions code `sensitive_read`

Revision ID: 116_sensitive_read_action
Revises: 115_reporting_role_boundary
Create Date: 2026-10-05 14:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2A-3 (decision D-4, option a). A GM audience preview
    reads what another member would see, so it is a security-relevant read that
    changes no data; none of the existing change actions describe a read. Like
    revision 103's `denied`, it is a new `audit.change_actions` row rather than a
    second audit mechanism. Preview audit rows are metadata only: actor, subject
    membership id, resource kind and id, outcome, correlation id -- never the
    projected response, narrative, or query strings.

    The row is inserted directly (`ON CONFLICT DO NOTHING`), not through
    `database/seeds/audit.change_actions.yaml`, which is revision 007's frozen
    input (docs/DATABASE_CONVENTIONS.md §25.4; see revision 103's docstring).

Rollback:
    Conditional, like revision 103: deletes the row when no `audit.change_log`
    row references it; otherwise raises and changes nothing, because preview
    audit history is never deleted or relabeled to force a downgrade (restore a
    pre-116 backup instead).

Data implications:
    Seeds one row.

Locking considerations:
    None (single-row insert into a small lookup table).
"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "116_sensitive_read_action"
down_revision = "115_reporting_role_boundary"
branch_labels = None
depends_on = None

_DOWNGRADE_BLOCKED = (
    "Cannot downgrade revision 116_sensitive_read_action: durable 'sensitive_read' "
    "audit history exists in audit.change_log. These records will not be deleted or "
    "relabeled to force the downgrade through. Rolling back past this revision requires "
    "restoring a database backup taken before 116_sensitive_read_action was applied."
)


def upgrade() -> None:
    op.execute("""
        INSERT INTO audit.change_actions (code, display_name, description, sort_order, is_active)
        VALUES (
            'sensitive_read',
            'Sensitive Read',
            'A security-relevant read that changes no data, such as a GM previewing what '
            'another member would see. Recorded with metadata only.',
            80,
            true
        )
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade() -> None:
    bind = op.get_bind()
    referenced = bind.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE ca.code = 'sensitive_read'
            )
        """)
    ).scalar()
    if referenced:
        raise RuntimeError(_DOWNGRADE_BLOCKED)
    op.execute("DELETE FROM audit.change_actions WHERE code = 'sensitive_read';")
