"""Add security.user_portal_preferences

Revision ID: 109_user_portal_preferences
Revises: 108_ios_consumed_by_index
Create Date: 2026-10-03 09:00:00.000000

Purpose:
    Phase 13 navigation and settings redesign (docs/UI_DESIGN.md §4.7). Stores
    the two durable, user-scoped portal navigation values the authenticated
    landing resolver needs: the campaign a user chose to always open at
    sign-in (`preferred_campaign_id`) and the campaign they most recently
    entered (`last_visited_campaign_id`). Both belong to the platform user, not
    to a browser or `security.browser_sessions` row, so they follow the user
    across browsers and survive logout.

    Neither column grants, implies, or caches access. Writers store a
    campaign ID only after re-verifying current membership, and readers
    (the session bootstrap) return a stored ID only while it is still in the
    caller's authorized campaign set. The portal theme is deliberately not
    stored here -- it stays client-side so it can apply before authentication.

Forward migration:
    `security.user_portal_preferences`:
      - `user_portal_preference_id UUID PK`
      - `user_id UUID NOT NULL REFERENCES security.users ON DELETE CASCADE`,
        unique -- at most one row per user, created lazily by the first
        preference write (upsert on `user_id`).
      - `preferred_campaign_id UUID NULL REFERENCES campaign.campaigns ON
        DELETE SET NULL` -- non-null means "Always open this campaign"; null
        means "Resume my last visited campaign". No mode column or lookup
        table: the mode is fully determined by this column.
      - `last_visited_campaign_id UUID NULL REFERENCES campaign.campaigns ON
        DELETE SET NULL`.
      - `created_at` / `updated_at` with the shared `updated_at` trigger.
      - Partial foreign-key indexes for both campaign columns (`user_id` is
        covered by its unique constraint).

Rollback:
    Supported. Drops the table. This discards only non-authoritative
    presentation state; no canon, permission, or audit data is affected.

Data implications:
    New, empty table; no backfill. Users without a row resolve to "resume last
    visited" with no stored campaign.

Locking considerations:
    Creating a new table with foreign keys briefly takes `SHARE ROW
    EXCLUSIVE` on `security.users` and `campaign.campaigns`; negligible, and
    matches revision 107's identical new-table shape.

See: docs/UI_DESIGN.md §4.7
     docs/architecture/DATABASE_MODEL.md §19.1 (`security.user_portal_preferences`)
     src/dnd_ai/persistence/tables/security.py (the matching declared table)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "109_user_portal_preferences"
down_revision = "108_ios_consumed_by_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        CREATE TABLE security.user_portal_preferences (
            user_portal_preference_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                    UUID NOT NULL
                                        REFERENCES security.users(user_id)
                                        ON DELETE CASCADE,
            preferred_campaign_id      UUID
                                        REFERENCES campaign.campaigns(campaign_id)
                                        ON DELETE SET NULL,
            last_visited_campaign_id   UUID
                                        REFERENCES campaign.campaigns(campaign_id)
                                        ON DELETE SET NULL,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_user_portal_preferences_user_id UNIQUE (user_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.user_portal_preferences IS
        'Durable, user-scoped portal navigation preferences: the campaign startup '
        'choice and the last-visited campaign (docs/UI_DESIGN.md §4.7). Belongs to '
        'the platform user, not a browser session. Presentation state only: no '
        'column grants, implies, or caches access, and no role or capability is '
        'copied here.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.user_portal_preferences.preferred_campaign_id IS
        'Non-null means startup mode "Always open this campaign"; null means "Resume '
        'my last visited campaign". Never grants access: readers ignore it unless the '
        'user currently has an active membership in that active campaign.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.user_portal_preferences.last_visited_campaign_id IS
        'The campaign the user most recently entered, recorded only after server-side '
        'campaign authorization succeeded. Never grants access: readers ignore it '
        'unless the user currently has an active membership in that active campaign.';
    """)
    op.execute(
        "CREATE INDEX ix_user_portal_preferences_preferred_campaign_id "
        "ON security.user_portal_preferences (preferred_campaign_id) "
        "WHERE preferred_campaign_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_user_portal_preferences_last_visited_campaign_id "
        "ON security.user_portal_preferences (last_visited_campaign_id) "
        "WHERE last_visited_campaign_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_user_portal_preferences_set_updated_at
        BEFORE UPDATE ON security.user_portal_preferences
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DROP TABLE IF EXISTS security.user_portal_preferences;")
