"""Immutable parent-scope identity columns

Revision ID: 030_parent_scope_immutable
Revises: 029_character_corrections
Create Date: 2026-08-02 21:30:00.000000

Purpose:
    Corrective revision (Phase 4 corrections review). Every same-world/
    same-scope trigger this project has built so far (sessions, party
    memberships, character timeline state, campaign ruleset allowance, ...)
    validates on INSERT and UPDATE of the *child* row. None of them re-run
    when the *parent* row's own scope changes out from under already-valid
    children: nothing stopped an UPDATE changing core.world_times.sort_key
    (invalidating every derived range built from it), core.entities.world_id
    (moving an entity, and every subtype/timeline-state row hanging off it,
    to a different world than its dependents expect), campaign.timelines
    .world_id, campaign.parties.world_id, or campaign.campaigns.timeline_id.

    None of these columns represent a legitimate "move" operation — a
    world_time's position in fictional chronology, an entity's owning world,
    a timeline's world, a party's world, and a campaign's timeline are all
    identity, not configuration. The fix is to make each immutable once set,
    per the corrections review's own stated preference, rather than build a
    transactional revalidate-and-rebuild path for a change that should not
    happen in the first place. One shared trigger function generalizes
    core.enforce_entity_subtype()'s "reusable function, per-table trigger
    argument" shape to an arbitrary list of protected columns.

Forward migration:
    - core.enforce_immutable_columns(), a generic BEFORE UPDATE trigger
      function taking one or more column names as trigger arguments
    - Attached to: core.world_times (world_id, sort_key), core.entities
      (world_id), campaign.timelines (world_id), campaign.parties
      (world_id), campaign.campaigns (timeline_id)

Rollback:
    Supported. Drops all five triggers and the shared function.

Data implications:
    Creates no rows. No test fixture in this project updates any of these
    columns after insert (grepped before writing this revision), so nothing
    existing breaks.

Locking considerations:
    Adding a trigger does not rewrite a table.

See: docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency)
     docs/architecture/DATABASE_MODEL.md §22 (required invariant 3: entity
     and subtype world ownership agree)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "030_parent_scope_immutable"
down_revision = "029_character_corrections"
branch_labels = None
depends_on = None

# (schema, table, trigger_name, [protected columns])
PROTECTED: list[tuple[str, str, str, list[str]]] = [
    ("core", "world_times", "tr_world_times_enforce_immutable", ["world_id", "sort_key"]),
    ("core", "entities", "tr_entities_enforce_immutable", ["world_id"]),
    ("campaign", "timelines", "tr_timelines_enforce_immutable", ["world_id"]),
    ("campaign", "parties", "tr_parties_enforce_immutable", ["world_id"]),
    ("campaign", "campaigns", "tr_campaigns_enforce_immutable", ["timeline_id"]),
]


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_immutable_columns()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_old  JSONB := to_jsonb(OLD);
            v_new  JSONB := to_jsonb(NEW);
            v_col  TEXT;
        BEGIN
            FOR i IN 0 .. TG_NARGS - 1 LOOP
                v_col := TG_ARGV[i];
                IF v_old -> v_col IS DISTINCT FROM v_new -> v_col THEN
                    RAISE EXCEPTION
                        '%.% is immutable on %.% and cannot be changed once set',
                        TG_TABLE_NAME, v_col, TG_TABLE_SCHEMA, TG_TABLE_NAME
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_immutable_columns() IS
        'Generic guard rejecting UPDATEs that change any of the columns named in the '
        'trigger''s arguments. Attach with the protected column names as trigger '
        'arguments, the same shape as core.enforce_entity_subtype(''<pk_column>'').';
    """)

    for schema, table, trigger_name, columns in PROTECTED:
        args = ", ".join(f"'{c}'" for c in columns)
        op.execute(f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns({args});
        """)


def downgrade() -> None:
    """Revert the migration."""

    for schema, table, trigger_name, _columns in reversed(PROTECTED):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {schema}.{table};")

    op.execute("DROP FUNCTION IF EXISTS core.enforce_immutable_columns();")
