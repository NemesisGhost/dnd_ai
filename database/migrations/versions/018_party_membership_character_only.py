"""Party membership requires a character

Revision ID: 018_party_membership_char
Revises: 017_characters
Create Date: 2026-08-02 15:30:00.000000

Purpose:
    Closes the deferral revision 009 recorded: campaign.party_memberships
    could only reference core.entities directly because character.characters
    did not exist yet, which meant the database could not reject a location
    or other non-character entity as a party member. It can now.

Forward migration:
    - campaign.enforce_party_membership_is_character(), checking that
      member_entity_id has a matching character.characters row
    - a new trigger on campaign.party_memberships enforcing it

Rollback:
    Supported. Drops the trigger and its function; the existing
    world-agreement trigger from revision 009 is untouched.

Data implications:
    No existing party_memberships rows exist to validate retroactively —
    this is a new constraint on future writes only.

Locking considerations:
    None. Adding a trigger does not rewrite the table.

See: docs/PLAN.md Phase 4 first-time obligations ("Close Phase 3's temporary
     party-member reference")
     database/migrations/versions/009_parties_and_memberships.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "018_party_membership_char"
down_revision = "017_characters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # A second BEFORE trigger alongside revision 009's world-agreement one,
    # rather than folding this check into that function: each function has
    # one clear responsibility, and dropping this one on some future
    # relaxation (a companion-only party?) won't touch the world guard.
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_party_membership_is_character()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_is_character BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM character.characters WHERE character_id = NEW.member_entity_id
            ) INTO v_is_character;

            IF NOT v_is_character THEN
                RAISE EXCEPTION
                    'Entity % is not a character and cannot be a party member',
                    NEW.member_entity_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_party_membership_is_character() IS
        'Requires party_memberships.member_entity_id to have a matching '
        'character.characters row. Closes the Phase 3 deferral now that Phase 4 has '
        'created that table.';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_memberships_enforce_is_character
        BEFORE INSERT OR UPDATE ON campaign.party_memberships
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_party_membership_is_character();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_party_memberships_enforce_is_character "
        "ON campaign.party_memberships;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_party_membership_is_character();")
