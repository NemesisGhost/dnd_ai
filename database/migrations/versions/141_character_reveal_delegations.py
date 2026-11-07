"""Add the character.reveal capability and campaign-scoped reveal delegations

Revision ID: 141_character_reveal_delegations
Revises: 140_clock_advance_details
Create Date: 2026-11-07 09:00:00.000000

Purpose:
    P03-A slice A1 (docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md section 1,
    docs/PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md). `character.reveal` is the
    authority to publish a character's public profile to an audience. It has exactly two sources:
    a live built-in `campaign_owner` assignment, and a delegation from such an owner to a member
    who holds the built-in `gm` role. It is never carried by a custom role, a relationship type or
    a resource grant, and `access.manage`, `canon.edit` and assistant-GM status confer none of it.

Forward migration:
    1. Inserts the `security.capabilities` row by explicit idempotent INSERT. The seed file is
       frozen (docs/DATABASE_CONVENTIONS.md section 25.4), so it is not edited. The row is
       vocabulary only: authority is resolved from the two sources above, never from
       `role_capabilities`, `character_relationship_type_capabilities` or `resource_grants`.
    2. Creates `security.character_reveal_delegations`, one row per grant, bound to the grantee's
       specific `gm` assignment (`gm_membership_role_id`). Closing a row records when and why
       (`end_reason`). One live row per grantee (partial unique index). Structural columns are
       immutable and a scope trigger keeps the campaign, the grantee's membership, the bound
       assignment (which must be the built-in `gm` template's) and both actors in one campaign.
    3. Adds a trigger to `role_capabilities`, `character_relationship_type_capabilities` and
       `resource_grants` that refuses any row naming `character.reveal` (a local integrity rule,
       docs/DATABASE_CONVENTIONS.md section 20.4).

Rollback:
    Supported but lossy. Drops the delegation table (every delegation and its history is lost; no
    other table references it), the triggers and functions, and the capability row. After a
    downgrade nobody holds delegated reveal authority.

Data implications:
    No backfill, no existing row changes. Nobody holds a delegation after the upgrade; owners have
    direct authority from their existing assignment.

Locking considerations:
    DDL on a new table plus row-level INSERT on a small lookup table. Creating the triggers takes a
    brief SHARE ROW EXCLUSIVE lock on the three tables they guard; no table rewrite.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "141_character_reveal_delegations"
down_revision = "140_clock_advance_details"
branch_labels = None
depends_on = None

_CAPABILITY = "character.reveal"

# (table, trigger name stem): the relationship-type table's full name would push the trigger name
# past PostgreSQL's 63-byte identifier limit.
_GUARDED_TABLES = (
    ("role_capabilities", "role_capabilities"),
    ("character_relationship_type_capabilities", "relationship_type_capabilities"),
    ("resource_grants", "resource_grants"),
)

_END_REASONS = (
    "revoked_by_owner",
    "gm_role_revoked",
    "gm_role_changed",
    "gm_assignment_lapsed",
    "membership_ended",
    "membership_status_changed",
)


def upgrade() -> None:
    """Apply the migration."""
    # Sort order 150 follows character.control (140).
    op.execute(f"""
        INSERT INTO security.capabilities (code, display_name, sort_order, is_active)
        VALUES ('{_CAPABILITY}', 'Reveal characters', 150, true)
        ON CONFLICT (code) DO NOTHING;
    """)

    end_reasons = ", ".join(f"'{reason}'" for reason in _END_REASONS)
    op.execute(f"""
        CREATE TABLE security.character_reveal_delegations (
            character_reveal_delegation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id                    UUID NOT NULL
                                            REFERENCES campaign.campaigns(campaign_id)
                                            ON DELETE CASCADE,
            grantee_campaign_membership_id UUID NOT NULL
                                            REFERENCES security.campaign_memberships(
                                                campaign_membership_id) ON DELETE CASCADE,
            gm_membership_role_id          UUID NOT NULL
                                            REFERENCES security.membership_roles(
                                                membership_role_id) ON DELETE CASCADE,
            granted_by_membership_id       UUID
                                            REFERENCES security.campaign_memberships(
                                                campaign_membership_id) ON DELETE SET NULL,
            granted_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason                         TEXT NOT NULL,
            revoked_at                     TIMESTAMPTZ,
            revoked_by_membership_id       UUID
                                            REFERENCES security.campaign_memberships(
                                                campaign_membership_id) ON DELETE SET NULL,
            revocation_reason              TEXT,
            end_reason                     TEXT,
            created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_character_reveal_delegations_reason
                CHECK (char_length(reason) BETWEEN 1 AND 1000),
            CONSTRAINT ck_character_reveal_delegations_revocation_reason
                CHECK (revocation_reason IS NULL OR char_length(revocation_reason) BETWEEN 1 AND 1000),
            CONSTRAINT ck_character_reveal_delegations_revoked_after_granted
                CHECK (revoked_at IS NULL OR revoked_at >= granted_at),
            CONSTRAINT ck_character_reveal_delegations_end_reason_values
                CHECK (end_reason IS NULL OR end_reason IN ({end_reasons})),
            CONSTRAINT ck_character_reveal_delegations_closure_consistent CHECK (
                (revoked_at IS NULL AND end_reason IS NULL
                    AND revoked_by_membership_id IS NULL AND revocation_reason IS NULL)
                OR (revoked_at IS NOT NULL AND end_reason IS NOT NULL)
            ),
            CONSTRAINT ck_character_reveal_delegations_revoker_only_for_owner_revocation CHECK (
                end_reason = 'revoked_by_owner'
                OR (revoked_by_membership_id IS NULL AND revocation_reason IS NULL)
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.character_reveal_delegations IS
        'A campaign owner''s delegation of character.reveal to a member holding the built-in gm '
        'role (P03-A A1). Bound to the grantee''s specific gm assignment (gm_membership_role_id): '
        'it authorizes only while that assignment is live, and losing it, ending the membership '
        'or regaining GM status later ends the grant, which needs a fresh row. Closed rows are '
        'kept as history (never deleted by commands). One live row per grantee.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.character_reveal_delegations.gm_membership_role_id IS
        'The grantee''s built-in gm assignment this delegation is bound to. Immutable; the '
        'delegation authorizes only while this exact row is live.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.character_reveal_delegations.granted_by_membership_id IS
        'The owner membership that granted it. Provenance, not authority: the delegation survives '
        'the grantor losing ownership. NULL only if that membership row was physically deleted.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.character_reveal_delegations.end_reason IS
        'Why the row was closed; NULL while it is live. revoked_by_owner is an explicit revocation '
        '(revoked_by_membership_id and revocation_reason set); the others are closed by the '
        'membership and role commands, or by a later grant that found the bound gm assignment '
        'lapsed (gm_assignment_lapsed).';
    """)
    op.execute(
        "CREATE INDEX ix_character_reveal_delegations_campaign_id "
        "ON security.character_reveal_delegations (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_reveal_delegations_grantee "
        "ON security.character_reveal_delegations (grantee_campaign_membership_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_reveal_delegations_gm_membership_role_id "
        "ON security.character_reveal_delegations (gm_membership_role_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_reveal_delegations_granted_by "
        "ON security.character_reveal_delegations (granted_by_membership_id) "
        "WHERE granted_by_membership_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_character_reveal_delegations_revoked_by "
        "ON security.character_reveal_delegations (revoked_by_membership_id) "
        "WHERE revoked_by_membership_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_character_reveal_delegations_live
        ON security.character_reveal_delegations (grantee_campaign_membership_id)
        WHERE revoked_at IS NULL;
    """)
    op.execute("""
        CREATE TRIGGER tr_character_reveal_delegations_set_updated_at
        BEFORE UPDATE ON security.character_reveal_delegations
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_character_reveal_delegations_enforce_immutable
        BEFORE UPDATE ON security.character_reveal_delegations
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns(
            'campaign_id', 'grantee_campaign_membership_id', 'gm_membership_role_id',
            'granted_at', 'reason'
        );
    """)

    op.execute("""
        CREATE FUNCTION security.enforce_character_reveal_delegation_scope()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_campaign UUID;
            v_bound_membership UUID;
            v_bound_role_campaign UUID;
            v_bound_role_code TEXT;
            v_actor_campaign UUID;
        BEGIN
            SELECT campaign_id INTO v_campaign
            FROM security.campaign_memberships
            WHERE campaign_membership_id = NEW.grantee_campaign_membership_id;
            IF v_campaign IS DISTINCT FROM NEW.campaign_id THEN
                RAISE EXCEPTION 'Membership % belongs to campaign %, not delegation campaign %',
                    NEW.grantee_campaign_membership_id, v_campaign, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT mr.campaign_membership_id, r.campaign_id, r.code
            INTO v_bound_membership, v_bound_role_campaign, v_bound_role_code
            FROM security.membership_roles mr
            JOIN security.roles r ON r.role_id = mr.role_id
            WHERE mr.membership_role_id = NEW.gm_membership_role_id;
            IF v_bound_membership IS DISTINCT FROM NEW.grantee_campaign_membership_id
               OR v_bound_role_campaign IS NOT NULL
               OR v_bound_role_code IS DISTINCT FROM 'gm' THEN
                RAISE EXCEPTION
                    'Assignment % is not the built-in gm assignment of membership %',
                    NEW.gm_membership_role_id, NEW.grantee_campaign_membership_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.granted_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_actor_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.granted_by_membership_id;
                IF v_actor_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION 'Granting membership % belongs to campaign %, not %',
                        NEW.granted_by_membership_id, v_actor_campaign, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            IF NEW.revoked_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_actor_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.revoked_by_membership_id;
                IF v_actor_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION 'Revoking membership % belongs to campaign %, not %',
                        NEW.revoked_by_membership_id, v_actor_campaign, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_character_reveal_delegation_scope() IS
        'A reveal delegation names one campaign: the grantee membership, the bound built-in gm '
        'assignment (which must belong to that membership) and both acting memberships must '
        'belong to it.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_reveal_delegations_enforce_scope
        BEFORE INSERT OR UPDATE ON security.character_reveal_delegations
        FOR EACH ROW EXECUTE FUNCTION security.enforce_character_reveal_delegation_scope();
    """)

    op.execute(f"""
        CREATE FUNCTION security.reject_character_reveal_capability_row()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM security.capabilities
                WHERE capability_id = NEW.capability_id AND code = '{_CAPABILITY}'
            ) THEN
                RAISE EXCEPTION
                    '{_CAPABILITY} comes only from a campaign owner or a reveal delegation, not '
                    'from %', TG_TABLE_NAME
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute(f"""
        COMMENT ON FUNCTION security.reject_character_reveal_capability_row() IS
        'Refuses a role capability, relationship-type capability or resource grant naming '
        '{_CAPABILITY}: its only sources are the built-in campaign owner and a reveal delegation '
        '(security.character_reveal_delegations).';
    """)
    for table, trigger_stem in _GUARDED_TABLES:
        op.execute(f"""
            CREATE TRIGGER tr_{trigger_stem}_reject_reveal
            BEFORE INSERT OR UPDATE ON security.{table}
            FOR EACH ROW EXECUTE FUNCTION security.reject_character_reveal_capability_row();
        """)


def downgrade() -> None:
    """Revert the migration (lossy: every delegation and its history is dropped)."""
    for table, trigger_stem in _GUARDED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS tr_{trigger_stem}_reject_reveal ON security.{table};")
    op.execute("DROP FUNCTION IF EXISTS security.reject_character_reveal_capability_row();")
    op.execute("DROP TABLE IF EXISTS security.character_reveal_delegations;")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_character_reveal_delegation_scope();")
    op.execute("DELETE FROM security.capabilities WHERE code = '" + _CAPABILITY + "'")
