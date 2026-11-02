"""Add the character.view_inventory capability and its relationship defaults

Revision ID: 139_inventory_capability
Revises: 138_world_roles_and_use_grants
Create Date: 2026-10-25 12:00:00.000000

Purpose:
    CP-6 / DR-2 (PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md). A character's inventory was
    readable only with the full character view (`character.view_full`), so a `viewer` or
    `observer_approved_viewer` (discover + summary) could never see what a character carries.
    `character.view_inventory` is a narrower, read-only capability: its holder reads the inventory
    through a restricted projection (`dnd_ai.queries.inventory.restrict_inventory_view`) and gains
    no sheet, no mutation and no control. An explicit deny of it wins over `character.view_full`.

Forward migration:
    1. Inserts the `security.capabilities` row with an explicit idempotent INSERT. The seed file
       `database/seeds/security.capabilities.yaml` was consumed by revision 080 and is frozen
       (docs/DATABASE_CONVENTIONS.md section 25.4), so it is not edited.
    2. Reconciles `security.character_relationship_type_capabilities` for the new capability only,
       following revision 114's pattern: removes any built-in-type mapping of
       `character.view_inventory` outside the matrix below (a developer database may hold a
       hand-added row) and inserts every missing matrix pair, `ON CONFLICT DO NOTHING`.

Matrix (type -> gains character.view_inventory):
    owner, primary_controller, co_controller, portrayer   (listed for explicitness; they already
                                                           hold character.view_full)
    viewer, observer_approved_viewer                      (the point of the revision)
    former_controller                                     (never: continued access needs a
                                                           separate active relationship)
    `dnd_ai.domain.access.BUILTIN_RELATIONSHIP_CAPABILITIES` holds the same matrix in code and a
    mapping row is authorization-effective only if both agree; a test asserts they do.

Rollback:
    Supported but lossy. Deletes the capability's relationship-type mappings, every
    `security.role_capabilities` row naming it, every `security.resource_grants` row (allow *and*
    deny) naming it, and the capability row. Explicit grants and denies of the capability are
    therefore lost, and after a downgrade a viewer again cannot read a character's inventory.

Data implications:
    No backfill. Existing owners, controllers and portrayers lose and gain nothing (they already
    read the inventory through `character.view_full`); existing viewers and observer-approved
    viewers gain the restricted inventory read, which is the intended change. No existing explicit
    grant or deny is altered.

Locking considerations:
    Row-level INSERT/DELETE on small lookup and mapping tables inside the migration transaction.
    No table rewrite.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "139_inventory_capability"
down_revision = "138_world_roles_and_use_grants"
branch_labels = None
depends_on = None

_CAPABILITY = "character.view_inventory"
_TYPES_WITH_CAPABILITY = (
    "owner",
    "primary_controller",
    "co_controller",
    "portrayer",
    "viewer",
    "observer_approved_viewer",
)
_BUILTIN_TYPES = (*_TYPES_WITH_CAPABILITY, "former_controller")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    """Apply the migration."""
    # Sort order 85 sits between view_full (80) and view_private (90).
    op.execute(f"""
        INSERT INTO security.capabilities (code, display_name, sort_order, is_active)
        VALUES ('{_CAPABILITY}', 'View inventory', 85, true)
        ON CONFLICT (code) DO NOTHING;
    """)
    # Reconcile this capability's built-in mappings (not other capabilities').
    op.execute(f"""
        DELETE FROM security.character_relationship_type_capabilities rtc
        USING security.character_relationship_types rt, security.capabilities cap
        WHERE rt.character_relationship_type_id = rtc.character_relationship_type_id
          AND cap.capability_id = rtc.capability_id
          AND cap.code = '{_CAPABILITY}'
          AND rt.code IN ({_quoted(_BUILTIN_TYPES)})
          AND rt.code NOT IN ({_quoted(_TYPES_WITH_CAPABILITY)});
    """)
    op.execute(f"""
        INSERT INTO security.character_relationship_type_capabilities
            (character_relationship_type_id, capability_id)
        SELECT rt.character_relationship_type_id, cap.capability_id
        FROM security.character_relationship_types rt
        JOIN security.capabilities cap ON cap.code = '{_CAPABILITY}'
        WHERE rt.code IN ({_quoted(_TYPES_WITH_CAPABILITY)})
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    """Revert the migration (lossy: explicit grants/denies of the capability are deleted)."""
    for statement in (
        "DELETE FROM security.character_relationship_type_capabilities WHERE capability_id IN "
        "(SELECT capability_id FROM security.capabilities WHERE code = '{c}')",
        "DELETE FROM security.role_capabilities WHERE capability_id IN "
        "(SELECT capability_id FROM security.capabilities WHERE code = '{c}')",
        "DELETE FROM security.resource_grants WHERE capability_id IN "
        "(SELECT capability_id FROM security.capabilities WHERE code = '{c}')",
        "DELETE FROM security.capabilities WHERE code = '{c}'",
    ):
        op.execute(statement.format(c=_CAPABILITY))
