"""Seed and reconcile production character-relationship capability defaults

Revision ID: 114_relationship_defaults
Revises: 113_organization_cycle_guard
Create Date: 2026-10-05 12:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2A-1. `security.character_relationship_type_
    capabilities` (revision 080) shipped with zero rows in every environment,
    so on a clean install no character relationship conferred any capability and
    no character could be selected as a perspective. Development-data scripts
    compensated by granting every `character.*` capability to `owner`; that was
    product security reference data living in a fixture. This revision makes it
    production reference data.

    The matrix below is the **maximum effective policy** for the seven built-in
    relationship types. `dnd_ai.domain.access.BUILTIN_RELATIONSHIP_CAPABILITIES`
    holds the same matrix in code and the resolver requires both a database row
    and permission under the code matrix, so a stray or re-added row is never
    authorization-effective. A test asserts the two copies agree.

    The matrix is a literal here, not a `database/seeds/*.yaml` file: a seed
    file read by `apply_seed` is replayed on every future `upgrade head`, and
    this matrix is a point-in-time decision (docs/DATABASE_CONVENTIONS.md
    §25.4's frozen-seed rule; compare revisions 086 and 103).

Matrix (type -> capabilities):
    owner, primary_controller:  discover, view_summary, view_full,
                                view_knowledge, view_private
    co_controller, portrayer:   discover, view_summary, view_full,
                                view_knowledge
    viewer, observer_approved_viewer:  discover, view_summary
    former_controller:          (none)
    Edit/control/interact capabilities are withheld until Phase 16.

Forward migration (reconciliation, in one transaction):
    1. For the seven built-in types only: DELETE every mapping pair outside the
       matrix (for example the `owner` -> all-`character.*` rows a development
       database may hold). Removed pairs are listed in a NOTICE and, when any
       were removed, recorded in one `audit.change_log` maintenance row
       (`actor_service = 'migration'`).
    2. INSERT every missing matrix pair, `ON CONFLICT DO NOTHING`.
    Rows for custom (non-built-in) types are left in place; they are
    ineffective because the resolver admits only the built-in types.

Rollback:
    Deletes exactly the matrix pairs for the built-in types. Pairs removed by
    the forward reconciliation are not restored (they were development-script
    artefacts; no production database ever held rows). Re-running the forward
    migration after a downgrade re-seeds the matrix.

Data implications:
    Production deployments have no rows, so the upgrade only inserts. Developer
    and test databases may lose extra pairs, all reported in the NOTICE.

Locking considerations:
    Row-level DELETE/INSERT on one small table inside the migration
    transaction. No table rewrite.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "114_relationship_defaults"
down_revision = "113_organization_cycle_guard"
branch_labels = None
depends_on = None

_DISCOVER = "character.discover"
_SUMMARY = "character.view_summary"
_FULL = "character.view_full"
_KNOWLEDGE = "character.view_knowledge"
_PRIVATE = "character.view_private"

_MATRIX: dict[str, tuple[str, ...]] = {
    "owner": (_DISCOVER, _SUMMARY, _FULL, _KNOWLEDGE, _PRIVATE),
    "primary_controller": (_DISCOVER, _SUMMARY, _FULL, _KNOWLEDGE, _PRIVATE),
    "co_controller": (_DISCOVER, _SUMMARY, _FULL, _KNOWLEDGE),
    "portrayer": (_DISCOVER, _SUMMARY, _FULL, _KNOWLEDGE),
    "viewer": (_DISCOVER, _SUMMARY),
    "observer_approved_viewer": (_DISCOVER, _SUMMARY),
    "former_controller": (),
}


def _allowed_values() -> str:
    pairs = [f"('{t}', '{c}')" for t, caps in _MATRIX.items() for c in caps]
    return ", ".join(pairs)


def _builtin_codes() -> str:
    return ", ".join(f"'{t}'" for t in _MATRIX)


def upgrade() -> None:
    allowed = _allowed_values()
    builtin = _builtin_codes()
    op.execute(f"""
        DO $reconcile$
        DECLARE
            removed jsonb;
        BEGIN
            WITH allowed(type_code, cap_code) AS (VALUES {allowed}),
            deleted AS (
                DELETE FROM security.character_relationship_type_capabilities rtc
                USING security.character_relationship_types rt, security.capabilities cap
                WHERE rt.character_relationship_type_id = rtc.character_relationship_type_id
                  AND cap.capability_id = rtc.capability_id
                  AND rt.code IN ({builtin})
                  AND NOT EXISTS (
                      SELECT 1 FROM allowed a
                      WHERE a.type_code = rt.code AND a.cap_code = cap.code
                  )
                RETURNING rt.code AS type_code, cap.code AS cap_code
            )
            SELECT COALESCE(
                       jsonb_agg(
                           jsonb_build_object('type', type_code, 'capability', cap_code)
                           ORDER BY type_code, cap_code
                       ),
                       CAST('[]' AS jsonb)
                   )
            INTO removed
            FROM deleted;

            IF jsonb_array_length(removed) > 0 THEN
                RAISE NOTICE
                    '114_relationship_defaults removed % unsupported built-in relationship capability mapping(s): %',
                    jsonb_array_length(removed), removed;
                INSERT INTO audit.change_log (
                    change_action_id, schema_name, table_name, actor_service,
                    command_name, reason, changed_fields
                )
                VALUES (
                    (SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'),
                    'security', 'character_relationship_type_capabilities', 'migration',
                    'reconcile_relationship_capability_defaults',
                    'Removed built-in relationship capability mappings outside the approved matrix',
                    jsonb_build_object(
                        'revision', '114_relationship_defaults',
                        'removed', removed
                    )
                );
            END IF;
        END
        $reconcile$;
    """)
    op.execute(f"""
        INSERT INTO security.character_relationship_type_capabilities
            (character_relationship_type_id, capability_id)
        SELECT rt.character_relationship_type_id, cap.capability_id
        FROM (VALUES {allowed}) AS allowed(type_code, cap_code)
        JOIN security.character_relationship_types rt ON rt.code = allowed.type_code
        JOIN security.capabilities cap ON cap.code = allowed.cap_code
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    allowed = _allowed_values()
    op.execute(f"""
        DELETE FROM security.character_relationship_type_capabilities rtc
        USING security.character_relationship_types rt, security.capabilities cap
        WHERE rt.character_relationship_type_id = rtc.character_relationship_type_id
          AND cap.capability_id = rtc.capability_id
          AND (rt.code, cap.code) IN (VALUES {allowed})
    """)
