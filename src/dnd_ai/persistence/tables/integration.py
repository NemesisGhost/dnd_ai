"""Integration domain tables — integration schema (revision 079).

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.

CHECK constraints and triggers are not declared here — see that same
__init__.py note for why (alembic does not compare them; tests cover them).
"""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

from ._shared import NONNEGATIVE_INTEGER, _timestamps, _uuid_pk, metadata

external_systems = Table(
    "external_systems",
    metadata,
    _uuid_pk("external_system_id"),
    Column(
        "world_id",
        UUID(),
        ForeignKey("core.worlds.world_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("system_type", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("external_reference", Text()),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    Column(
        "system_key_hash",
        Text(),
        comment=(
            "sha256 hex digest of a Foundry-adapter system-level credential "
            "(dnd_ai.domain.access.hash_foundry_system_key). NULL until "
            "dnd_ai.commands.integration.issue_foundry_system_key is called for "
            "this row; issuing a new key overwrites this in place (rotation, not "
            "append) rather than tracking history. Never the raw key itself — see "
            "security.campaign_invitations.invitation_token_hash for the identical "
            "hash-only pattern."
        ),
    ),
    *_timestamps(),
    UniqueConstraint("system_key_hash", name="ux_external_systems_system_key_hash"),
    schema="integration",
    comment=(
        "A configured external system connection for a world — a specific "
        "Foundry world, a specific Discord guild (docs/architecture/"
        "DATABASE_MODEL.md §19). external_reference is that system's own "
        "identifier for the connection (a Foundry world ID, a Discord guild "
        "ID), free-text since it varies by system_type."
    ),
)

Index("ix_external_systems_world_id", external_systems.c.world_id)
Index("ix_external_systems_system_type", external_systems.c.system_type)

external_identifiers = Table(
    "external_identifiers",
    metadata,
    _uuid_pk("external_identifier_id"),
    Column(
        "external_system_id",
        UUID(),
        ForeignKey("integration.external_systems.external_system_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "external_kind",
        Text(),
        nullable=False,
        comment=(
            "The external system's own category for this mapping (actor, "
            "scene, journal, token, ...) — free text, not a CHECK-constrained "
            "set, since the vocabulary varies per system_type (see this "
            "revision's docstring)."
        ),
    ),
    Column("external_id", Text(), nullable=False),
    Column("last_synced_at", TIMESTAMP(timezone=True)),
    *_timestamps(),
    UniqueConstraint(
        "external_system_id",
        "external_kind",
        "external_id",
        name="ux_external_identifiers_system_kind_external",
    ),
    schema="integration",
    comment=(
        "Maps an internal entity to its representation in an external "
        "system — a Foundry actor/scene/journal/token, a Discord user/"
        "channel (docs/architecture/SYSTEM_ARCHITECTURE.md §15.1). External "
        "IDs must never replace internal UUID identity "
        "(docs/architecture/DATABASE_MODEL.md §19) — every other domain "
        "table continues to reference entity_id, never external_id. One "
        "entity may have several rows here (e.g. both an 'actor' and a "
        "'token' mapping in the same system)."
    ),
)

Index("ix_external_identifiers_external_system_id", external_identifiers.c.external_system_id)
Index("ix_external_identifiers_entity_id", external_identifiers.c.entity_id)

sync_jobs = Table(
    "sync_jobs",
    metadata,
    _uuid_pk("sync_job_id"),
    Column(
        "external_system_id",
        UUID(),
        ForeignKey("integration.external_systems.external_system_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("direction", Text(), nullable=False),
    Column("job_type", Text(), nullable=False),
    Column(
        "target_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="SET NULL"),
    ),
    Column(
        "target_encounter_id",
        UUID(),
        ForeignKey("narrative.encounters.encounter_id", ondelete="SET NULL"),
    ),
    Column("status", Text(), nullable=False, server_default=text("'pending'::text")),
    Column(
        "payload_jsonb",
        JSONB(),
        comment=(
            "The request payload used for both replay and idempotency-conflict "
            "comparison — an explicitly acceptable JSONB use (conventions "
            "§5.7). For inbound jobs with an external_operation_id, this is "
            "the canonicalized set of command arguments (not only the raw "
            "external payload) so a replay with a different payload under the "
            "same operation id can be detected. Never the sole record of a "
            "state change: a job that mutates persistent state does so "
            "through the normal command layer (rule 6), which records its own "
            "causal event; resulting_event_id links back to that event when "
            "there was one."
        ),
    ),
    Column("error_message", Text()),
    Column(
        "resulting_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
    ),
    Column(
        "resulting_encounter_turn_id",
        UUID(),
        ForeignKey("narrative.encounter_turns.encounter_turn_id", ondelete="SET NULL"),
        comment=(
            "The narrative.encounter_turns row this job produced, when it "
            "produced one — lets a replayed job (same external_system_id, "
            "external_operation_id) reconstruct its original result "
            "(combat_action_id via the turn, HP change via "
            "narrative.event_effects keyed off resulting_event_id) without "
            "re-executing the domain command."
        ),
    ),
    Column(
        "external_operation_id",
        Text(),
        comment=(
            "A stable idempotency key the external system supplies for an "
            "inbound job (e.g. a Foundry combat-turn operation id) — unique "
            "per external_system_id (ux_sync_jobs_system_operation, below), so "
            "redelivering the same operation is detected as a replay rather "
            "than re-applied. NULL for job types with no external-supplied "
            "operation identity (e.g. outbound jobs this platform itself "
            "initiates)."
        ),
    ),
    *_timestamps(),
    schema="integration",
    comment=(
        "One unit of synchronization work between an external system and "
        "the platform — inbound (a Foundry combat action submitted) or "
        "outbound (pushing updated HP back to Foundry), per "
        "docs/architecture/DATABASE_MODEL.md §19. At most one of "
        "target_entity_id/target_encounter_id is set; a job with neither "
        "is valid (e.g. an initial connection handshake with no single "
        "subject yet)."
    ),
)

Index("ix_sync_jobs_external_system_id", sync_jobs.c.external_system_id)
Index("ix_sync_jobs_status", sync_jobs.c.status)
Index(
    "ix_sync_jobs_target_entity_id",
    sync_jobs.c.target_entity_id,
    postgresql_where=sync_jobs.c.target_entity_id.isnot(None),
)
Index(
    "ix_sync_jobs_target_encounter_id",
    sync_jobs.c.target_encounter_id,
    postgresql_where=sync_jobs.c.target_encounter_id.isnot(None),
)
Index(
    "ix_sync_jobs_resulting_event_id",
    sync_jobs.c.resulting_event_id,
    postgresql_where=sync_jobs.c.resulting_event_id.isnot(None),
)
Index(
    "ix_sync_jobs_resulting_encounter_turn_id",
    sync_jobs.c.resulting_encounter_turn_id,
    postgresql_where=sync_jobs.c.resulting_encounter_turn_id.isnot(None),
)
Index(
    "ux_sync_jobs_system_operation",
    sync_jobs.c.external_system_id,
    sync_jobs.c.external_operation_id,
    unique=True,
    postgresql_where=sync_jobs.c.external_operation_id.isnot(None),
)

sync_state = Table(
    "sync_state",
    metadata,
    _uuid_pk("sync_state_id"),
    Column(
        "external_system_id",
        UUID(),
        ForeignKey("integration.external_systems.external_system_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "target_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
    ),
    Column(
        "target_encounter_id",
        UUID(),
        ForeignKey("narrative.encounters.encounter_id", ondelete="CASCADE"),
    ),
    Column(
        "last_sync_job_id",
        UUID(),
        ForeignKey("integration.sync_jobs.sync_job_id", ondelete="SET NULL"),
    ),
    Column("last_synced_at", TIMESTAMP(timezone=True)),
    Column("sync_status", Text(), nullable=False, server_default=text("'unsynced'::text")),
    *_timestamps(),
    schema="integration",
    comment=(
        "Current synchronization status for one target (an entity or an "
        "encounter) against one external system — distinct from "
        "integration.sync_jobs, which logs each individual unit of work "
        "(docs/architecture/DATABASE_MODEL.md §19). Exactly one of "
        "target_entity_id/target_encounter_id is set, unlike sync_jobs "
        "where neither may be set — a current sync-state row must always "
        "be about something. One current row per (external system, "
        "target) — see the partial unique indexes below."
    ),
)

Index("ix_sync_state_external_system_id", sync_state.c.external_system_id)
Index(
    "ix_sync_state_target_entity_id",
    sync_state.c.target_entity_id,
    postgresql_where=sync_state.c.target_entity_id.isnot(None),
)
Index(
    "ix_sync_state_target_encounter_id",
    sync_state.c.target_encounter_id,
    postgresql_where=sync_state.c.target_encounter_id.isnot(None),
)
Index(
    "ix_sync_state_last_sync_job_id",
    sync_state.c.last_sync_job_id,
    postgresql_where=sync_state.c.last_sync_job_id.isnot(None),
)
Index(
    "ux_sync_state_system_entity",
    sync_state.c.external_system_id,
    sync_state.c.target_entity_id,
    unique=True,
    postgresql_where=sync_state.c.target_entity_id.isnot(None),
)
Index(
    "ux_sync_state_system_encounter",
    sync_state.c.external_system_id,
    sync_state.c.target_encounter_id,
    unique=True,
    postgresql_where=sync_state.c.target_encounter_id.isnot(None),
)

delivery_attempts = Table(
    "delivery_attempts",
    metadata,
    _uuid_pk("delivery_attempt_id"),
    Column(
        "sync_job_id",
        UUID(),
        ForeignKey("integration.sync_jobs.sync_job_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("attempt_number", NONNEGATIVE_INTEGER, nullable=False, server_default=text("1")),
    Column("attempted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("succeeded", Boolean(), nullable=False),
    Column("response_summary", Text()),
    UniqueConstraint("sync_job_id", "attempt_number", name="ux_delivery_attempts_job_attempt"),
    schema="integration",
    comment=(
        "One retry attempt for a sync job — timestamp, success, and a "
        "short response summary (docs/architecture/DATABASE_MODEL.md §19). "
        "Append-only; a sync job that fails and is retried gets a second "
        "row with attempt_number incremented, not an update to the first."
    ),
)

Index("ix_delivery_attempts_sync_job_id", delivery_attempts.c.sync_job_id)
