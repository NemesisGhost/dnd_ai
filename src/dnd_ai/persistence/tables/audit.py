"""Audit tables — audit schema.

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Identity,
    Index,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

from ._shared import (
    _lookup_table,
    metadata,
)

# ---------------------------------------------------------------------------
# audit (revision 007)
# ---------------------------------------------------------------------------

change_actions = _lookup_table(
    "audit",
    "change_actions",
    "change_action_id",
    "What kind of change an audit row records. Covers the operations in "
    "docs/DATABASE_CONVENTIONS.md §24.1.",
)

change_log = Table(
    "change_log",
    metadata,
    Column(
        "change_log_id",
        BigInteger(),
        Identity(always=True),
        primary_key=True,
        comment=(
            "BIGINT identity rather than UUID: high-volume internal append-only data with no "
            "need for globally portable identity (conventions §5.2)."
        ),
    ),
    Column(
        "change_action_id",
        UUID(),
        ForeignKey("audit.change_actions.change_action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("schema_name", Text(), nullable=False),
    Column("table_name", Text(), nullable=False),
    Column(
        "record_id",
        UUID(),
        comment=(
            "Primary key of the changed row, in whatever table schema_name.table_name names. "
            "Unconstrained by design."
        ),
    ),
    Column(
        "entity_id",
        UUID(),
        comment=(
            "The core.entities row this change concerns, when there is one. Denormalized from "
            "record_id so entity history can be queried without knowing which subtype table "
            "the change landed in."
        ),
    ),
    Column("world_id", UUID()),
    Column("previous_status", Text()),
    Column("new_status", Text()),
    Column(
        "actor_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    Column(
        "actor_service",
        Text(),
        comment=(
            "Set instead of actor_user_id when the actor is a service, integration, or AI agent "
            "rather than a person (conventions §24.3). At least one of the two is required."
        ),
    ),
    Column("source_id", UUID(), ForeignKey("core.sources.source_id", ondelete="SET NULL")),
    Column("reason", Text()),
    Column("correlation_id", UUID()),
    Column("causation_id", UUID()),
    Column("command_name", Text()),
    Column(
        "event_id",
        UUID(),
        comment=(
            "The narrative event that caused this change. Nullable for records that have no "
            "causal event."
        ),
    ),
    Column("ai_proposal_id", UUID()),
    Column(
        "changed_fields",
        JSONB(),
        comment=(
            "Field-level diff when one is worth keeping. JSONB here is a deliberate use for "
            "genuinely variable shape, not a substitute for relational modelling (§18)."
        ),
    ),
    Column("recorded_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="audit",
    comment=(
        "Append-only record of who changed what and why. Rows outlive the records they "
        "describe, so the columns identifying those records carry no foreign keys — a "
        "cascade would destroy history and a restrict would block legitimate deletion."
    ),
)

Index("ix_change_log_change_action_id", change_log.c.change_action_id)
Index("ix_change_log_actor_user_id", change_log.c.actor_user_id)
Index("ix_change_log_source_id", change_log.c.source_id)
Index("ix_change_log_correlation_id", change_log.c.correlation_id)
Index(
    "ix_change_log_entity_id_recorded_at",
    change_log.c.entity_id,
    change_log.c.recorded_at.desc(),
)
Index(
    "ix_change_log_world_id_recorded_at",
    change_log.c.world_id,
    change_log.c.recorded_at.desc(),
)
