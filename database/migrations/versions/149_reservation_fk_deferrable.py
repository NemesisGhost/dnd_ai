"""Make the reservation's campaign foreign key DEFERRABLE INITIALLY IMMEDIATE

Revision ID: 149_reservation_fk_deferrable
Revises: 148_player_profile_provenance
Create Date: 2026-11-14 12:00:00.000000

Purpose:
    R01 S5-C (docs/R01_FRESH_AUTHORIZATION_PLAN_2026-11-12.md section 6.21, J-1'). A keyed
    pre-write request must be able to take its own locks in the access-management order *before* the
    campaign row, but the reservation INSERT checks the campaign foreign key immediately and so takes
    `FOR KEY SHARE` on the campaign row first. Making the constraint deferrable lets a plan opt in to
    deferring that one check to COMMIT (`SET CONSTRAINTS ... DEFERRED`, issued only by the
    authorization plan). The constraint stays `INITIALLY IMMEDIATE`: every request that does not
    opt in behaves exactly as before.

Forward migration:
    `ALTER TABLE security.idempotent_requests ALTER CONSTRAINT idempotent_requests_campaign_id_fkey
    DEFERRABLE INITIALLY IMMEDIATE`. Only the campaign foreign key changes. The account foreign key
    (`idempotent_requests_actor_user_id_fkey`), both referential actions (ON DELETE CASCADE) and
    the immediate default are untouched.

Rollback:
    `ALTER CONSTRAINT ... NOT DEFERRABLE`. Constraint mode is transaction-scoped state, so no row or
    session carries the setting across the migration.

Data implications:
    None. No row is read or rewritten.

Locking considerations:
    `ALTER CONSTRAINT` on a foreign key takes `SHARE ROW EXCLUSIVE` on both
    `security.idempotent_requests` and `campaign.campaigns` for the duration of the statement
    (catalogue update of the constraint and its internal triggers, no validation scan).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "149_reservation_fk_deferrable"
down_revision = "148_player_profile_provenance"
branch_labels = None
depends_on = None

_TABLE = "security.idempotent_requests"
_CONSTRAINT = "idempotent_requests_campaign_id_fkey"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {_TABLE} ALTER CONSTRAINT {_CONSTRAINT} DEFERRABLE INITIALLY IMMEDIATE"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ALTER CONSTRAINT {_CONSTRAINT} NOT DEFERRABLE")
