"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Purpose:
    ${message}

Forward migration:
    [Describe what this revision creates, modifies, or removes]

Rollback:
    [Describe downgrade behavior — supported/partial/not-supported and why]

Data implications:
    [Does this change require data migration? Does it affect existing rows?]

Locking considerations:
    [Does this add constraints or indexes to large existing tables?]

See: docs/DATABASE_CONVENTIONS.md §25.2 (Migration files)
"""
from alembic import op
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    """Apply the migration."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Revert the migration."""
    ${downgrades if downgrades else "pass"}
