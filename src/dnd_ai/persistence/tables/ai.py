"""AI domain tables — ai schema.

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
093_ai_domain, 094_reference_corpus, and 098_ai_domain_fk_indexes exactly.
`core.source_documents` (094_reference_corpus) lives in tables/core.py
instead, alongside its sources/source_types siblings — see that module's
own comment.
"""

from sqlalchemy import (
    REAL,
    Boolean,
    Column,
    Computed,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, TSVECTOR, UUID
from sqlalchemy.types import Integer

from ._shared import _timestamps, _uuid_pk, metadata

# ---------------------------------------------------------------------------
# ai — agent/prompt/context/proposal apparatus (revision 093_ai_domain)
# ---------------------------------------------------------------------------

agent_roles = Table(
    "agent_roles",
    metadata,
    _uuid_pk("agent_role_id"),
    # Deliberately not _lookup_table() (conventions §11): 093_ai_domain's
    # own CREATE TABLE predates that shape converging to include created_at/
    # updated_at and a code comment — code has no COMMENT ON COLUMN and
    # sort_order is a plain INTEGER, not the nonnegative_integer domain.
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("sort_order", Integer(), nullable=False, server_default=text("0")),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    UniqueConstraint("code", name="ux_agent_roles_code"),
    schema="ai",
    comment=(
        "The eight initial AI agent roles PLAN.md §18 names (npc portrayal, "
        "dungeon state, quest manager, rules assistant, world state manager, "
        "lore consistency checker, session summarizer, rumor propagation). "
        "A lookup, not a CTI hierarchy — a role has no behavior of its own "
        "beyond naming which ai.agents rows exist for it."
    ),
)

agents = Table(
    "agents",
    metadata,
    _uuid_pk("agent_id"),
    Column(
        "agent_role_id",
        UUID(),
        ForeignKey("ai.agent_roles.agent_role_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("display_name", Text(), nullable=False),
    # No column-level comment — provider's own meaning is documented in the
    # table's COMMENT below, not a separate COMMENT ON COLUMN statement.
    Column("provider", Text(), nullable=False),
    Column("model_identifier", Text(), nullable=False),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    schema="ai",
    comment=(
        "One configured agent instance — a role plus a provider/model pin "
        "(docs/architecture/DATABASE_MODEL.md §18). provider/model_identifier "
        "are free text, not a CHECK-constrained set: unlike this codebase's "
        "own closed vocabularies (event types, capability codes, ...), which "
        "provider and model exist is decided by the AI vendor landscape, not "
        "this schema, and genuinely changes over time."
    ),
)

Index("ix_agents_agent_role_id", agents.c.agent_role_id)

agent_assignments = Table(
    "agent_assignments",
    metadata,
    _uuid_pk("agent_assignment_id"),
    Column(
        "agent_id", UUID(), ForeignKey("ai.agents.agent_id", ondelete="CASCADE"), nullable=False
    ),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    # No column-level comment — entity_id's own meaning (including the
    # revision 096_campaign_scoped_agents NULL case) is documented in the
    # table's COMMENT below, not a separate COMMENT ON COLUMN statement.
    Column("entity_id", UUID(), ForeignKey("core.entities.entity_id", ondelete="CASCADE")),
    Column("assigned_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column(
        "assigned_by_user_id", UUID(), ForeignKey("security.users.user_id", ondelete="SET NULL")
    ),
    Column("ended_at", TIMESTAMP(timezone=True)),
    schema="ai",
    comment=(
        "Assigns one ai.agents row to portray/manage one entity within one "
        "campaign — for this phase's only wired role (npc_portrayal), the "
        'NPC entity_id an agent speaks as. ended_at IS NULL is "currently '
        'assigned" (the same current-record pattern DATABASE_MODEL.md §12.4 '
        "already establishes elsewhere), enforced unique below."
    ),
)

Index("ix_agent_assignments_agent_id", agent_assignments.c.agent_id)
Index("ix_agent_assignments_campaign_id", agent_assignments.c.campaign_id)
Index(
    "ux_agent_assignments_current",
    agent_assignments.c.campaign_id,
    agent_assignments.c.entity_id,
    unique=True,
    postgresql_where=agent_assignments.c.ended_at.is_(None),
)
# 098_ai_domain_fk_indexes: same-phase correction pass adding the FK
# indexes 093_ai_domain/094_reference_corpus omitted (conventions §19.1).
Index("ix_agent_assignments_entity_id", agent_assignments.c.entity_id)
Index(
    "ix_agent_assignments_assigned_by_user_id",
    agent_assignments.c.assigned_by_user_id,
    postgresql_where=agent_assignments.c.assigned_by_user_id.isnot(None),
)

prompt_fragments = Table(
    "prompt_fragments",
    metadata,
    _uuid_pk("prompt_fragment_id"),
    Column("fragment_key", Text(), nullable=False),
    Column("content", Text(), nullable=False),
    Column("description", Text()),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    UniqueConstraint("fragment_key", name="ux_prompt_fragments_key"),
    schema="ai",
    comment=(
        "A reusable, independently editable block of prompt text (a system "
        "persona, a safety constraint, ...) a prompt_templates row composes "
        "by key — never inlined per-template, so a shared constraint can be "
        "edited once (docs/architecture/DATABASE_MODEL.md §18). Composition "
        "itself is application code (dnd_ai.domain.context_assembly), not a "
        "database concern."
    ),
)

prompt_templates = Table(
    "prompt_templates",
    metadata,
    _uuid_pk("prompt_template_id"),
    Column(
        "agent_role_id",
        UUID(),
        ForeignKey("ai.agent_roles.agent_role_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("template_text", Text(), nullable=False),
    Column("version", Integer(), nullable=False, server_default=text("1")),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    UniqueConstraint("agent_role_id", "code", name="ux_prompt_templates_role_code"),
    schema="ai",
    comment=(
        "One versioned prompt layout for one agent role — may reference "
        "ai.prompt_fragments by key; composition is application code, not "
        "enforced by this schema."
    ),
)

context_requests = Table(
    "context_requests",
    metadata,
    _uuid_pk("context_request_id"),
    Column(
        "agent_assignment_id",
        UUID(),
        ForeignKey("ai.agent_assignments.agent_assignment_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("requesting_user_id", UUID(), ForeignKey("security.users.user_id", ondelete="SET NULL")),
    # No column-level comment: the migration documents this column's
    # meaning inside the table's own COMMENT ON TABLE text below, not a
    # separate COMMENT ON COLUMN statement.
    Column(
        "requesting_character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="SET NULL"),
    ),
    Column("request_kind", Text(), nullable=False),
    Column("input_text", Text(), nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="ai",
    comment=(
        "One attempt to assemble deterministic, audience-filtered context "
        "for an agent invocation (docs/architecture/DATABASE_MODEL.md §18). "
        "requesting_character_id is the perspective the context was filtered "
        "through (dnd_ai.domain.context_assembly) — NULL for a GM-perspective "
        "request (e.g. a gm_brief), set for a player/character-perspective "
        "one."
    ),
)

Index("ix_context_requests_agent_assignment_id", context_requests.c.agent_assignment_id)
Index(
    "ix_context_requests_requesting_character_id",
    context_requests.c.requesting_character_id,
    postgresql_where=context_requests.c.requesting_character_id.isnot(None),
)
# 098_ai_domain_fk_indexes
Index(
    "ix_context_requests_requesting_user_id",
    context_requests.c.requesting_user_id,
    postgresql_where=context_requests.c.requesting_user_id.isnot(None),
)

context_snapshots = Table(
    "context_snapshots",
    metadata,
    _uuid_pk("context_snapshot_id"),
    Column(
        "context_request_id",
        UUID(),
        ForeignKey("ai.context_requests.context_request_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("assembled_context", JSONB(), nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("context_request_id", name="ux_context_snapshots_request"),
    schema="ai",
    comment=(
        "The assembled context actually sent for a request, retained for "
        "reproducibility and debugging — distinct from the request itself "
        "(docs/architecture/DATABASE_MODEL.md §18). JSONB is an explicitly "
        "acceptable use here (conventions §5.7): an external-request payload "
        "snapshot, never queried by field, one row per context_requests row. "
        "A retry gets a new context_requests row and its own snapshot, never "
        "a second snapshot layered onto an existing request."
    ),
)

generated_outputs = Table(
    "generated_outputs",
    metadata,
    _uuid_pk("generated_output_id"),
    Column(
        "context_request_id",
        UUID(),
        ForeignKey("ai.context_requests.context_request_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("provider", Text(), nullable=False),
    Column("model_identifier", Text(), nullable=False),
    Column("raw_response", Text()),
    Column("structured_output", JSONB()),
    Column("finish_reason", Text()),
    Column("latency_ms", Integer()),
    Column("error_message", Text()),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="ai",
    comment=(
        "The provider response for one context request — recorded whether "
        "the call succeeded or failed (error_message set, raw_response/"
        "structured_output NULL, on failure), so a failed call is still "
        "auditable (docs/architecture/DATABASE_MODEL.md §18). "
        "structured_output is the parsed/schema-validated result a command "
        "actually acts on; raw_response is the unparsed provider text, kept "
        "for debugging a parse failure."
    ),
)

Index("ix_generated_outputs_context_request_id", generated_outputs.c.context_request_id)

proposed_changes = Table(
    "proposed_changes",
    metadata,
    _uuid_pk("ai_proposed_change_id"),
    Column(
        "generated_output_id",
        UUID(),
        ForeignKey("ai.generated_outputs.generated_output_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("proposal_kind", Text(), nullable=False),
    Column("proposed_arguments", JSONB(), nullable=False),
    Column("risk_tier", Text(), nullable=False),
    Column("status", Text(), nullable=False, server_default=text("'pending'::text")),
    Column("decided_by_user_id", UUID(), ForeignKey("security.users.user_id", ondelete="SET NULL")),
    Column("decided_at", TIMESTAMP(timezone=True)),
    Column("decision_reason", Text()),
    Column(
        "applied_event_id", UUID(), ForeignKey("narrative.events.event_id", ondelete="SET NULL")
    ),
    *_timestamps(),
    schema="ai",
    comment=(
        "One AI-generated proposal, never itself canonical (CLAUDE.md rule "
        "2) — implements the Generated -> Proposed -> Validated -> Approved "
        "-> Applied lifecycle (docs/ENTITY_LIFECYCLE.md §10). "
        "proposed_arguments is the exact keyword-argument payload the "
        "target domain command (named by proposal_kind) will be called with "
        "if approved — a legitimate JSONB use (conventions §5.7): a proposed "
        "command invocation awaiting a decision, structurally identical to "
        "integration.sync_jobs.payload_jsonb's own \"external payload "
        'snapshot" precedent. decided_by_user_id IS NULL with decided_at SET '
        "marks a policy auto-approval (dnd_ai.domain.ai_policy) rather than "
        "a human reviewer — see ai.change_reviews, which only exists for "
        "actual human decisions."
    ),
)

Index("ix_proposed_changes_generated_output_id", proposed_changes.c.generated_output_id)
Index(
    "ix_proposed_changes_campaign_status",
    proposed_changes.c.campaign_id,
    proposed_changes.c.status,
)
Index(
    "ix_proposed_changes_applied_event_id",
    proposed_changes.c.applied_event_id,
    postgresql_where=proposed_changes.c.applied_event_id.isnot(None),
)
# 098_ai_domain_fk_indexes
Index(
    "ix_proposed_changes_decided_by_user_id",
    proposed_changes.c.decided_by_user_id,
    postgresql_where=proposed_changes.c.decided_by_user_id.isnot(None),
)

change_reviews = Table(
    "change_reviews",
    metadata,
    _uuid_pk("ai_change_review_id"),
    Column(
        "ai_proposed_change_id",
        UUID(),
        ForeignKey("ai.proposed_changes.ai_proposed_change_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("reviewer_user_id", UUID(), ForeignKey("security.users.user_id", ondelete="SET NULL")),
    Column("decision", Text(), nullable=False),
    Column("comments", Text()),
    Column("reviewed_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="ai",
    comment=(
        "One human review decision for one ai.proposed_changes row — only "
        "created for an actual reviewer action (dnd_ai.commands.ai_proposals."
        "review_proposed_change); an automatic policy approval never creates "
        "a row here (docs/architecture/DATABASE_MODEL.md §18), see "
        "ai.proposed_changes.decided_by_user_id's own comment."
    ),
)

Index("ix_change_reviews_ai_proposed_change_id", change_reviews.c.ai_proposed_change_id)
# 098_ai_domain_fk_indexes
Index(
    "ix_change_reviews_reviewer_user_id",
    change_reviews.c.reviewer_user_id,
    postgresql_where=change_reviews.c.reviewer_user_id.isnot(None),
)

# ---------------------------------------------------------------------------
# ai — rules/reference corpus retrieval (revision 094_reference_corpus).
# core.source_documents (the registered document itself) lives in
# tables/core.py alongside its sources/source_types siblings.
# ---------------------------------------------------------------------------

reference_passages = Table(
    "reference_passages",
    metadata,
    _uuid_pk("reference_passage_id"),
    Column(
        "source_document_id",
        UUID(),
        ForeignKey("core.source_documents.source_document_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("passage_order", Integer(), nullable=False),
    Column("chapter", Text()),
    Column("section", Text()),
    Column("page_label", Text()),
    Column("heading", Text()),
    Column("content", Text(), nullable=False),
    Column(
        "content_tsv",
        TSVECTOR(),
        Computed("to_tsvector('english'::regconfig, content)", persisted=True),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "source_document_id", "passage_order", name="ux_reference_passages_source_order"
    ),
    schema="ai",
    comment=(
        "One retrievable, citable chunk of a registered source document "
        "(docs/PLAN.md §18.3): chapter/section/page_label carry citation "
        "location, content_tsv is a generated, indexed tsvector column — "
        "PostgreSQL-native full-text search, no embeddings or external "
        "search service for this phase. passage_order is the source's own "
        "ordinal position, used for deterministic tie-breaking and as a "
        "stable citation reference alongside chapter/section/page_label."
    ),
)

Index("ix_reference_passages_source_document_id", reference_passages.c.source_document_id)
Index(
    "ix_reference_passages_content_tsv",
    reference_passages.c.content_tsv,
    postgresql_using="gin",
)

reference_source_campaigns = Table(
    "reference_source_campaigns",
    metadata,
    _uuid_pk("reference_source_campaign_id"),
    Column(
        "source_document_id",
        UUID(),
        ForeignKey("core.source_documents.source_document_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("is_house_rule", Boolean(), nullable=False, server_default=text("false")),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("granted_by_user_id", UUID(), ForeignKey("security.users.user_id", ondelete="SET NULL")),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    schema="ai",
    comment=(
        "Explicit per-campaign retrieval grant for a 'campaign_restricted' "
        "core.source_documents row (docs/PLAN.md §18.3) — never needed for "
        "a 'general' source, which any same-ruleset campaign may already "
        "retrieve. is_house_rule marks the grant as this campaign's own "
        "override, taking retrieval precedence over a general source for "
        "the same ruleset (dnd_ai.queries.reference_corpus). Revoked, not "
        "deleted, so grant history remains auditable; the partial unique "
        "index below allows re-granting after a revocation."
    ),
)

Index(
    "ux_reference_source_campaigns_active",
    reference_source_campaigns.c.source_document_id,
    reference_source_campaigns.c.campaign_id,
    unique=True,
    postgresql_where=reference_source_campaigns.c.revoked_at.is_(None),
)
Index("ix_reference_source_campaigns_campaign_id", reference_source_campaigns.c.campaign_id)
# 098_ai_domain_fk_indexes
Index(
    "ix_reference_source_campaigns_granted_by_user_id",
    reference_source_campaigns.c.granted_by_user_id,
    postgresql_where=reference_source_campaigns.c.granted_by_user_id.isnot(None),
)

reference_retrievals = Table(
    "reference_retrievals",
    metadata,
    _uuid_pk("reference_retrieval_id"),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "requested_by_user_id", UUID(), ForeignKey("security.users.user_id", ondelete="SET NULL")
    ),
    Column(
        "context_request_id",
        UUID(),
        ForeignKey("ai.context_requests.context_request_id", ondelete="SET NULL"),
    ),
    Column("query_text", Text(), nullable=False),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="ai",
    comment=(
        "One corpus retrieval — the audit trail docs/PLAN.md §18.3 requires "
        '("retrieval and downstream AI use are audited"), independent of '
        "ai.context_requests: context_request_id is set when the retrieval "
        "happened as part of an agent invocation (dnd_ai.commands.ai_npc), "
        "NULL for a standalone rules-question lookup with no agent call "
        "attached."
    ),
)

Index("ix_reference_retrievals_campaign_id", reference_retrievals.c.campaign_id)
Index(
    "ix_reference_retrievals_context_request_id",
    reference_retrievals.c.context_request_id,
    postgresql_where=reference_retrievals.c.context_request_id.isnot(None),
)
# 098_ai_domain_fk_indexes
Index("ix_reference_retrievals_ruleset_version_id", reference_retrievals.c.ruleset_version_id)
Index(
    "ix_reference_retrievals_requested_by_user_id",
    reference_retrievals.c.requested_by_user_id,
    postgresql_where=reference_retrievals.c.requested_by_user_id.isnot(None),
)

reference_retrieval_results = Table(
    "reference_retrieval_results",
    metadata,
    Column(
        "reference_retrieval_id",
        UUID(),
        ForeignKey("ai.reference_retrievals.reference_retrieval_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "reference_passage_id",
        UUID(),
        ForeignKey("ai.reference_passages.reference_passage_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("rank", Integer(), nullable=False),
    Column("relevance_score", REAL()),
    # No explicit name — the migration's own inline `PRIMARY KEY (...)`
    # clause leaves Postgres to assign its default `<table>_pkey` name,
    # which SQLAlchemy also leaves unset here so autogenerate matches it.
    PrimaryKeyConstraint("reference_retrieval_id", "reference_passage_id"),
    schema="ai",
    comment=(
        "One returned, cited passage for one ai.reference_retrievals row, "
        "in rank order — preserves exactly what was retrieved and in what "
        "order, for audit and reproducibility."
    ),
)

Index(
    "ix_reference_retrieval_results_passage_id", reference_retrieval_results.c.reference_passage_id
)
