"""Add the character.assign_control capability and campaign-scoped assign-control delegations

Revision ID: 151_assign_control_delegations
Revises: 150_control_assignments
Create Date: 2026-11-26 12:00:00.000000

Purpose:
    P15-C11-S02-T02 (docs/delivery/p15-c11-s02-control-changes-plan.md section 3.2, ADR 0021 OD-4a).
    `character.assign_control` is the authority to assign, replace and revoke the control of a character in one
    campaign. It has exactly three sources: a live built-in `campaign_owner` assignment, a live built-in `gm`
    assignment, and a delegation from such an owner or GM to a member who holds the built-in `assistant_gm` role.
    It is never carried by a custom role, a relationship type, a resource grant or a control assignment, and
    `access.manage`, `canon.edit` and the clock confer none of it. A delegated holder cannot delegate it further.

Forward migration:
    1. Inserts the `security.capabilities` row by explicit idempotent INSERT (the seed file is frozen, docs/
       DATABASE_CONVENTIONS.md section 25.4). The row is vocabulary only: authority is resolved from the sources
       above, never from `role_capabilities`, `character_relationship_type_capabilities` or `resource_grants`.
    2. Creates `security.character_assign_control_delegations`, one row per grant, bound to the grantee's specific
       built-in `assistant_gm` assignment (`assistant_gm_membership_role_id`). Closing a row records when and why
       (`end_reason`). One live row per grantee (partial unique index). Structural columns are immutable and a scope
       trigger keeps the campaign, the grantee's membership, the bound assignment (which must be the built-in
       `assistant_gm` template's) and both actors in one campaign.
    3. Adds a trigger to `role_capabilities`, `character_relationship_type_capabilities` and `resource_grants` that
       refuses any row naming `character.assign_control` (a local integrity rule, docs/DATABASE_CONVENTIONS.md
       section 20.4).

Rollback:
    Supported but lossy. Drops the delegation table (every delegation and its history is lost; no other table
    references it), the triggers and functions, and the capability row. After a downgrade nobody holds delegated
    assignment authority; owners and GMs keep their own. Reveal delegations are untouched.

Data implications:
    No backfill, no existing row changes. Nobody holds a delegation after the upgrade.

Locking considerations:
    DDL on a new table plus row-level INSERT on a small lookup table. Creating the triggers takes a brief SHARE ROW
    EXCLUSIVE lock on the three tables they guard; no table rewrite.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "151_assign_control_delegations"
down_revision = "150_control_assignments"
branch_labels = None
depends_on = None

_CAPABILITY = "character.assign_control"
_TABLE = "security.character_assign_control_delegations"

# (table, trigger name stem): the relationship-type table's full name would push the trigger name past PostgreSQL's
# 63-byte identifier limit.
_GUARDED_TABLES = (
    ("role_capabilities", "role_capabilities"),
    ("character_relationship_type_capabilities", "relationship_type_capabilities"),
    ("resource_grants", "resource_grants"),
)

_END_REASONS = ("revoked", "assistant_gm_assignment_lapsed")


def upgrade() -> None:
    """Apply the migration."""
    # Sort order 160 follows character.reveal (150).
    op.execute(f"""
        INSERT INTO security.capabilities (code, display_name, sort_order, is_active)
        VALUES ('{_CAPABILITY}', 'Assign character control', 160, true)
        ON CONFLICT (code) DO NOTHING;
    """)

    end_reasons = ", ".join(f"'{reason}'" for reason in _END_REASONS)
    op.execute(f"""
        CREATE TABLE {_TABLE} (
            character_assign_control_delegation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id                    UUID NOT NULL
                                            REFERENCES campaign.campaigns(campaign_id)
                                            ON DELETE CASCADE,
            grantee_campaign_membership_id UUID NOT NULL
                                            REFERENCES security.campaign_memberships(
                                                campaign_membership_id) ON DELETE CASCADE,
            assistant_gm_membership_role_id UUID NOT NULL
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
            CONSTRAINT ck_assign_control_delegations_reason
                CHECK (char_length(reason) BETWEEN 1 AND 1000),
            CONSTRAINT ck_assign_control_delegations_revocation_reason
                CHECK (revocation_reason IS NULL OR char_length(revocation_reason) BETWEEN 1 AND 1000),
            CONSTRAINT ck_assign_control_delegations_revoked_after_granted
                CHECK (revoked_at IS NULL OR revoked_at >= granted_at),
            CONSTRAINT ck_assign_control_delegations_end_reason_values
                CHECK (end_reason IS NULL OR end_reason IN ({end_reasons})),
            CONSTRAINT ck_assign_control_delegations_closure_consistent CHECK (
                (revoked_at IS NULL AND end_reason IS NULL
                    AND revoked_by_membership_id IS NULL AND revocation_reason IS NULL)
                OR (revoked_at IS NOT NULL AND end_reason IS NOT NULL)
            ),
            CONSTRAINT ck_assign_control_delegations_revoker_only_when_revoked CHECK (
                end_reason = 'revoked'
                OR (revoked_by_membership_id IS NULL AND revocation_reason IS NULL)
            ),
            CONSTRAINT ck_assign_control_delegations_revoked_has_reason CHECK (
                end_reason IS DISTINCT FROM 'revoked' OR revocation_reason IS NOT NULL
            )
        );
    """)
    op.execute(f"""
        COMMENT ON TABLE {_TABLE} IS
        'A campaign owner''s or GM''s delegation of character.assign_control to a member holding the '
        'built-in assistant_gm role (P15-C11-S02 OD-4a). Bound to the grantee''s specific assistant_gm '
        'assignment (assistant_gm_membership_role_id): it authorizes only while that assignment is live, '
        'and losing it, ending the membership or regaining assistant GM status later leaves it not in '
        'force, which needs a fresh row. Closed rows are kept as history (never deleted by commands). '
        'One live row per grantee. Not a reveal delegation (security.character_reveal_delegations).';
    """)
    op.execute(f"""
        COMMENT ON COLUMN {_TABLE}.assistant_gm_membership_role_id IS
        'The grantee''s built-in assistant_gm assignment this delegation is bound to. Immutable; the '
        'delegation authorizes only while this exact row is live.';
    """)
    op.execute(f"""
        COMMENT ON COLUMN {_TABLE}.granted_by_membership_id IS
        'The owner or GM membership that granted it. Provenance, not authority: the delegation survives '
        'the grantor losing the role. NULL only if that membership row was physically deleted.';
    """)
    op.execute(f"""
        COMMENT ON COLUMN {_TABLE}.end_reason IS
        'Why the row was closed; NULL while it is live. revoked is an explicit revocation '
        '(revoked_by_membership_id and revocation_reason set); assistant_gm_assignment_lapsed is a '
        'later grant that found the bound assistant_gm assignment no longer live and closed the row.';
    """)
    op.execute(
        "CREATE INDEX ix_character_assign_control_delegations_campaign_id "
        f"ON {_TABLE} (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_assign_control_delegations_grantee "
        f"ON {_TABLE} (grantee_campaign_membership_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_assign_control_delegations_assistant_role "
        f"ON {_TABLE} (assistant_gm_membership_role_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_assign_control_delegations_granted_by "
        f"ON {_TABLE} (granted_by_membership_id) "
        "WHERE granted_by_membership_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_character_assign_control_delegations_revoked_by "
        f"ON {_TABLE} (revoked_by_membership_id) "
        "WHERE revoked_by_membership_id IS NOT NULL;"
    )
    op.execute(f"""
        CREATE UNIQUE INDEX ux_character_assign_control_delegations_live
        ON {_TABLE} (grantee_campaign_membership_id)
        WHERE revoked_at IS NULL;
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_assign_control_delegations_set_updated_at
        BEFORE UPDATE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_assign_control_delegations_enforce_immutable
        BEFORE UPDATE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns(
            'campaign_id', 'grantee_campaign_membership_id', 'assistant_gm_membership_role_id',
            'granted_at', 'reason'
        );
    """)

    op.execute("""
        CREATE FUNCTION security.enforce_character_assign_control_delegation_scope()
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
            WHERE mr.membership_role_id = NEW.assistant_gm_membership_role_id;
            IF v_bound_membership IS DISTINCT FROM NEW.grantee_campaign_membership_id
               OR v_bound_role_campaign IS NOT NULL
               OR v_bound_role_code IS DISTINCT FROM 'assistant_gm' THEN
                RAISE EXCEPTION
                    'Assignment % is not the built-in assistant_gm assignment of membership %',
                    NEW.assistant_gm_membership_role_id, NEW.grantee_campaign_membership_id
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
        COMMENT ON FUNCTION security.enforce_character_assign_control_delegation_scope() IS
        'An assign-control delegation names one campaign: the grantee membership, the bound built-in '
        'assistant_gm assignment (which must belong to that membership) and both acting memberships must '
        'belong to it.';
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_assign_control_delegations_enforce_scope
        BEFORE INSERT OR UPDATE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION security.enforce_character_assign_control_delegation_scope();
    """)

    op.execute(f"""
        CREATE FUNCTION security.reject_character_assign_control_capability_row()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM security.capabilities
                WHERE capability_id = NEW.capability_id AND code = '{_CAPABILITY}'
            ) THEN
                RAISE EXCEPTION
                    '{_CAPABILITY} comes only from a built-in owner or gm assignment or an assign-control '
                    'delegation, not from %', TG_TABLE_NAME
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute(f"""
        COMMENT ON FUNCTION security.reject_character_assign_control_capability_row() IS
        'Refuses a role capability, relationship-type capability or resource grant naming '
        '{_CAPABILITY}: its only sources are the built-in campaign owner and gm roles and an assign-control '
        'delegation (security.character_assign_control_delegations).';
    """)
    for table, trigger_stem in _GUARDED_TABLES:
        op.execute(f"""
            CREATE TRIGGER tr_{trigger_stem}_reject_assign_control
            BEFORE INSERT OR UPDATE ON security.{table}
            FOR EACH ROW EXECUTE FUNCTION security.reject_character_assign_control_capability_row();
        """)


def downgrade() -> None:
    """Revert the migration (lossy: every delegation and its history is dropped)."""
    for table, trigger_stem in _GUARDED_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS tr_{trigger_stem}_reject_assign_control ON security.{table};"
        )
    op.execute("DROP FUNCTION IF EXISTS security.reject_character_assign_control_capability_row();")
    op.execute(f"DROP TABLE IF EXISTS {_TABLE};")
    op.execute(
        "DROP FUNCTION IF EXISTS security.enforce_character_assign_control_delegation_scope();"
    )
    op.execute("DELETE FROM security.capabilities WHERE code = '" + _CAPABILITY + "'")
