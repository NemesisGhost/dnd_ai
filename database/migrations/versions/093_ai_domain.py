"""AI domain: agents, prompts, context assembly, generated output, and the
proposed-change/review workflow.

Revision ID: 093_ai_domain
Revises: 092_foundry_key_principal
Create Date: 2026-08-20 12:00:00.000000

Purpose:
    Phase 12 ("Narrow AI/NPC MVP", docs/PLAN.md) delivers the database model
    for docs/architecture/DATABASE_MODEL.md §18 ("AI and approval model") —
    the `ai` schema itself already existed (seeded, with default privileges
    wired, by revision 001) but has never been populated. This revision
    builds the agent/prompt/context/proposal apparatus; the companion
    094_reference_corpus migration builds the rules/reference-corpus tables
    §18.3 describes, deliberately as a second migration since the corpus's
    own audit table (ai.reference_retrievals) references ai.context_requests
    below.

    `ai.embedding_records` (named in §18's own primary-table list) is
    deliberately NOT built here: docs/PLAN.md's Phase 12 entry is explicit —
    "Do not create a general-purpose document-ingestion or vector-search
    framework for this scenario. Defer embeddings ... until structured
    metadata, relational retrieval, and PostgreSQL full-text search have
    proved insufficient." Building an unused embeddings table now would be
    exactly the "don't build ahead of the phase that needs it" anti-pattern
    CLAUDE.md warns against — the same reasoning rules.item_definitions was
    deferred out of the Phase 4 rules-model migration (DATABASE_MODEL.md
    §8).

    `audit.agent_activity`/`audit.approval_history` (§21's general audit
    table list) are also deliberately not built here. Every fact those
    tables would carry for AI activity is already captured, with full
    provenance, by the tables below: ai.context_requests/.context_snapshots
    are the request-and-context audit trail, ai.generated_outputs is the
    response audit trail, and ai.proposed_changes/.change_reviews are the
    proposal-and-decision audit trail. A separate audit.* copy of the same
    facts would violate CLAUDE.md rule 1 (PostgreSQL is the only source of
    truth — not "the same fact stored twice"), the same "don't duplicate
    domain state" reasoning Phase 11 workstream 4's sync-state view already
    applied to itself. audit.validation_failures/.state_transitions are
    unrelated to what Phase 12 needs and remain unbuilt until a phase that
    actually needs them exists.

Forward migration:
    - ai.agent_roles (seeded lookup — the eight roles PLAN.md §18 names;
      only npc_portrayal is wired to a concrete ai.agents row anywhere in
      this phase's application code, matching the "start with one use
      case" instruction in PLAN.md's Phase 12 entry)
    - ai.agents
    - ai.agent_assignments, with ai.enforce_agent_assignment_world()
    - ai.prompt_fragments
    - ai.prompt_templates
    - ai.context_requests
    - ai.context_snapshots
    - ai.generated_outputs
    - ai.proposed_changes
    - ai.change_reviews

Rollback:
    Supported. Drops everything created here in FK-dependency order.

Data implications:
    Seeds ai.agent_roles only. Creates no other rows.

Locking considerations:
    Every statement creates a new, empty object.

Deliberate scoping decisions:
    - ai.proposed_changes.proposal_kind is a single-value closed set today
      (`reveal_knowledge`) — the one canonical mutation this phase's NPC-
      portrayal use case actually proposes (dnd_ai.commands.ai_npc). A
      CHECK-constrained set, not free text, since (unlike integration.
      external_identifiers.external_kind, where the vocabulary genuinely
      varies per external system) this vocabulary is entirely owned by
      this codebase's own command layer — extending it is a migration, the
      same posture narrative.event_types/audit.change_actions already
      take. PLAN.md §18's own high-impact/low-risk examples (character
      death, settlement destruction, marking a hidden feature discovered,
      recording conversational memory, ...) describe the eventual range;
      this phase implements the one low-risk example a conversational NPC
      can actually produce evidence for.
    - No new narrative.event_types row: reveal_knowledge's target command
      (dnd_ai.commands.knowledge.reveal_knowledge_to_party, added
      alongside this migration) reuses the existing 'knowledge_revealed'
      code interactions.py's _maybe_discover_target() already established
      — the causal fact ("a party learned of a knowledge item") is
      identical regardless of whether a hidden dungeon feature or an
      approved AI proposal triggered it.
    - ai.context_requests carries no campaign_id of its own — it is
      resolved via agent_assignment_id -> ai.agent_assignments.campaign_id,
      the same "resolve through the owning row rather than duplicate the
      column" choice narrative.quest_objectives/campaign.objective_state
      already make for their own owning quest. ai.reference_retrievals
      (094_reference_corpus) is the one exception, since a rules-question
      retrieval is not always driven by an agent invocation at all.
    - ai.context_snapshots is 1:1 with its ai.context_requests row
      (UNIQUE) for this MVP: a caller who wants to retry gets a new
      context_requests row (a fresh, reproducible assembly), never a
      second snapshot layered onto the same request.

See: docs/PLAN.md Phase 12 (Narrow AI/NPC MVP)
     docs/architecture/DATABASE_MODEL.md §18 (AI and approval model)
     docs/ENTITY_LIFECYCLE.md §10 (AI-generated entities and changes —
     the Generated -> Proposed -> Validated -> Approved -> Applied
     lifecycle ai.proposed_changes.status implements)
     docs/DATABASE_CONVENTIONS.md §5.7 (JSONB — assembled_context/
     proposed_arguments/structured_output are each a legitimate "external
     payload snapshot" use, not a substitute for typed columns)
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "093_ai_domain"
down_revision = "092_foundry_key_principal"
branch_labels = None
depends_on = None

_CONTEXT_REQUEST_KINDS = (
    "npc_conversation",
    "rules_question",
    "gm_brief",
    "player_summary",
    "observer_summary",
)
_RISK_TIERS = ("auto_approve", "requires_approval")
_PROPOSAL_STATUSES = ("pending", "approved", "rejected", "applied", "withdrawn")
_REVIEW_DECISIONS = ("approve", "reject")


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. ai.agent_roles
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.agent_roles (
            agent_role_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code           TEXT NOT NULL,
            display_name   TEXT NOT NULL,
            description    TEXT,
            sort_order     INTEGER NOT NULL DEFAULT 0,
            is_active      BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT ux_agent_roles_code UNIQUE (code),
            CONSTRAINT ck_agent_roles_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.agent_roles IS
        'The eight initial AI agent roles PLAN.md §18 names (npc portrayal, '
        'dungeon state, quest manager, rules assistant, world state manager, '
        'lore consistency checker, session summarizer, rumor propagation). '
        'A lookup, not a CTI hierarchy — a role has no behavior of its own '
        'beyond naming which ai.agents rows exist for it.';
    """)
    apply_seed(op, "ai", "agent_roles")

    # ==========================================================================
    # 2. ai.agents
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.agents (
            agent_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_role_id      UUID NOT NULL
                               REFERENCES ai.agent_roles(agent_role_id) ON DELETE RESTRICT,
            display_name       TEXT NOT NULL,
            provider           TEXT NOT NULL,
            model_identifier   TEXT NOT NULL,
            is_active          BOOLEAN NOT NULL DEFAULT true,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_agents_display_name_length CHECK (char_length(display_name) BETWEEN 1 AND 200),
            CONSTRAINT ck_agents_provider_length CHECK (char_length(provider) BETWEEN 1 AND 100),
            CONSTRAINT ck_agents_model_identifier_length
                CHECK (char_length(model_identifier) BETWEEN 1 AND 200)
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.agents IS
        'One configured agent instance — a role plus a provider/model pin '
        '(docs/architecture/DATABASE_MODEL.md §18). provider/model_identifier '
        'are free text, not a CHECK-constrained set: unlike this codebase''s '
        'own closed vocabularies (event types, capability codes, ...), which '
        'provider and model exist is decided by the AI vendor landscape, not '
        'this schema, and genuinely changes over time.';
    """)
    op.execute("""
        CREATE TRIGGER tr_agents_set_updated_at
        BEFORE UPDATE ON ai.agents
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_agents_agent_role_id ON ai.agents (agent_role_id);")

    # ==========================================================================
    # 3. ai.agent_assignments
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.agent_assignments (
            agent_assignment_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id                UUID NOT NULL
                                   REFERENCES ai.agents(agent_id) ON DELETE CASCADE,
            campaign_id                 UUID NOT NULL
                                   REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            entity_id                       UUID NOT NULL
                                   REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            assigned_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
            assigned_by_user_id                    UUID
                                   REFERENCES security.users(user_id) ON DELETE SET NULL,
            ended_at                                  TIMESTAMPTZ
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.agent_assignments IS
        'Assigns one ai.agents row to portray/manage one entity within one '
        'campaign — for this phase''s only wired role (npc_portrayal), the '
        'NPC entity_id an agent speaks as. ended_at IS NULL is "currently '
        'assigned" (the same current-record pattern DATABASE_MODEL.md §12.4 '
        'already establishes elsewhere), enforced unique below.';
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_agent_assignments_current
        ON ai.agent_assignments (campaign_id, entity_id)
        WHERE ended_at IS NULL;
    """)
    op.execute("CREATE INDEX ix_agent_assignments_agent_id ON ai.agent_assignments (agent_id);")
    op.execute(
        "CREATE INDEX ix_agent_assignments_campaign_id ON ai.agent_assignments (campaign_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION ai.enforce_agent_assignment_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_world  UUID;
            v_entity_world    UUID;
        BEGIN
            SELECT t.world_id INTO v_campaign_world
            FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = NEW.campaign_id;

            SELECT world_id INTO v_entity_world
            FROM core.entities WHERE entity_id = NEW.entity_id;

            IF v_entity_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Agent assignment % belongs to campaign % (world %), but entity % '
                    'belongs to world %',
                    NEW.agent_assignment_id, NEW.campaign_id, v_campaign_world, NEW.entity_id,
                    v_entity_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION ai.enforce_agent_assignment_world() IS
        'Same-world guard for ai.agent_assignments (conventions §9.5): the '
        'assigned entity must belong to the assigning campaign''s own world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_agent_assignments_enforce_world
        BEFORE INSERT OR UPDATE ON ai.agent_assignments
        FOR EACH ROW EXECUTE FUNCTION ai.enforce_agent_assignment_world();
    """)

    # ==========================================================================
    # 4. ai.prompt_fragments
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.prompt_fragments (
            prompt_fragment_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            fragment_key            TEXT NOT NULL,
            content                    TEXT NOT NULL,
            description                   TEXT,
            is_active                       BOOLEAN NOT NULL DEFAULT true,
            created_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_prompt_fragments_key UNIQUE (fragment_key),
            CONSTRAINT ck_prompt_fragments_key_length
                CHECK (char_length(fragment_key) BETWEEN 1 AND 200),
            CONSTRAINT ck_prompt_fragments_content_length
                CHECK (char_length(content) BETWEEN 1 AND 20000)
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.prompt_fragments IS
        'A reusable, independently editable block of prompt text (a system '
        'persona, a safety constraint, ...) a prompt_templates row composes '
        'by key — never inlined per-template, so a shared constraint can be '
        'edited once (docs/architecture/DATABASE_MODEL.md §18). Composition '
        'itself is application code (dnd_ai.domain.context_assembly), not a '
        'database concern.';
    """)
    op.execute("""
        CREATE TRIGGER tr_prompt_fragments_set_updated_at
        BEFORE UPDATE ON ai.prompt_fragments
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 5. ai.prompt_templates
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.prompt_templates (
            prompt_template_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_role_id            UUID NOT NULL
                                    REFERENCES ai.agent_roles(agent_role_id) ON DELETE CASCADE,
            code                        TEXT NOT NULL,
            template_text                  TEXT NOT NULL,
            version                            INTEGER NOT NULL DEFAULT 1,
            is_active                            BOOLEAN NOT NULL DEFAULT true,
            created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_prompt_templates_role_code UNIQUE (agent_role_id, code),
            CONSTRAINT ck_prompt_templates_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_prompt_templates_template_text_length
                CHECK (char_length(template_text) BETWEEN 1 AND 20000),
            CONSTRAINT ck_prompt_templates_version_positive CHECK (version >= 1)
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.prompt_templates IS
        'One versioned prompt layout for one agent role — may reference '
        'ai.prompt_fragments by key; composition is application code, not '
        'enforced by this schema.';
    """)
    op.execute("""
        CREATE TRIGGER tr_prompt_templates_set_updated_at
        BEFORE UPDATE ON ai.prompt_templates
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 6. ai.context_requests
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE ai.context_requests (
            context_request_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_assignment_id        UUID NOT NULL
                                      REFERENCES ai.agent_assignments(agent_assignment_id)
                                      ON DELETE CASCADE,
            requesting_user_id            UUID
                                      REFERENCES security.users(user_id) ON DELETE SET NULL,
            requesting_character_id          UUID
                                      REFERENCES character.characters(character_id)
                                      ON DELETE SET NULL,
            request_kind                        TEXT NOT NULL,
            input_text                             TEXT NOT NULL,
            created_at                                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_context_requests_kind CHECK (request_kind IN {_CONTEXT_REQUEST_KINDS}),
            CONSTRAINT ck_context_requests_input_text_length
                CHECK (char_length(input_text) BETWEEN 1 AND 4000)
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.context_requests IS
        'One attempt to assemble deterministic, audience-filtered context '
        'for an agent invocation (docs/architecture/DATABASE_MODEL.md §18). '
        'requesting_character_id is the perspective the context was filtered '
        'through (dnd_ai.domain.context_assembly) — NULL for a GM-perspective '
        'request (e.g. a gm_brief), set for a player/character-perspective '
        'one.';
    """)
    op.execute(
        "CREATE INDEX ix_context_requests_agent_assignment_id "
        "ON ai.context_requests (agent_assignment_id);"
    )
    op.execute(
        "CREATE INDEX ix_context_requests_requesting_character_id "
        "ON ai.context_requests (requesting_character_id) WHERE requesting_character_id IS NOT NULL;"
    )

    # ==========================================================================
    # 7. ai.context_snapshots
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.context_snapshots (
            context_snapshot_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            context_request_id      UUID NOT NULL
                                   REFERENCES ai.context_requests(context_request_id)
                                   ON DELETE CASCADE,
            assembled_context           JSONB NOT NULL,
            created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_context_snapshots_request UNIQUE (context_request_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.context_snapshots IS
        'The assembled context actually sent for a request, retained for '
        'reproducibility and debugging — distinct from the request itself '
        '(docs/architecture/DATABASE_MODEL.md §18). JSONB is an explicitly '
        'acceptable use here (conventions §5.7): an external-request payload '
        'snapshot, never queried by field, one row per context_requests row. '
        'A retry gets a new context_requests row and its own snapshot, never '
        'a second snapshot layered onto an existing request.';
    """)

    # ==========================================================================
    # 8. ai.generated_outputs
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.generated_outputs (
            generated_output_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            context_request_id      UUID NOT NULL
                                   REFERENCES ai.context_requests(context_request_id)
                                   ON DELETE CASCADE,
            provider                    TEXT NOT NULL,
            model_identifier                TEXT NOT NULL,
            raw_response                        TEXT,
            structured_output                       JSONB,
            finish_reason                              TEXT,
            latency_ms                                    INTEGER,
            error_message                                    TEXT,
            created_at                                         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_generated_outputs_latency_nonnegative
                CHECK (latency_ms IS NULL OR latency_ms >= 0)
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.generated_outputs IS
        'The provider response for one context request — recorded whether '
        'the call succeeded or failed (error_message set, raw_response/'
        'structured_output NULL, on failure), so a failed call is still '
        'auditable (docs/architecture/DATABASE_MODEL.md §18). '
        'structured_output is the parsed/schema-validated result a command '
        'actually acts on; raw_response is the unparsed provider text, kept '
        'for debugging a parse failure.';
    """)
    op.execute(
        "CREATE INDEX ix_generated_outputs_context_request_id "
        "ON ai.generated_outputs (context_request_id);"
    )

    # ==========================================================================
    # 9. ai.proposed_changes
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE ai.proposed_changes (
            ai_proposed_change_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            generated_output_id       UUID NOT NULL
                                     REFERENCES ai.generated_outputs(generated_output_id)
                                     ON DELETE CASCADE,
            campaign_id                  UUID NOT NULL
                                     REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            proposal_kind                    TEXT NOT NULL,
            proposed_arguments                  JSONB NOT NULL,
            risk_tier                              TEXT NOT NULL,
            status                                    TEXT NOT NULL DEFAULT 'pending',
            decided_by_user_id                          UUID
                                     REFERENCES security.users(user_id) ON DELETE SET NULL,
            decided_at                                     TIMESTAMPTZ,
            decision_reason                                   TEXT,
            applied_event_id                                     UUID
                                     REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                                              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_proposed_changes_kind CHECK (proposal_kind = 'reveal_knowledge'),
            CONSTRAINT ck_proposed_changes_risk_tier CHECK (risk_tier IN {_RISK_TIERS}),
            CONSTRAINT ck_proposed_changes_status CHECK (status IN {_PROPOSAL_STATUSES}),
            CONSTRAINT ck_proposed_changes_pending_undecided CHECK (
                status <> 'pending' OR (decided_at IS NULL AND applied_event_id IS NULL)
            ),
            CONSTRAINT ck_proposed_changes_applied_has_event CHECK (
                status <> 'applied' OR applied_event_id IS NOT NULL
            ),
            CONSTRAINT ck_proposed_changes_decided_states CHECK (
                status IN ('pending', 'withdrawn') OR decided_at IS NOT NULL
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.proposed_changes IS
        'One AI-generated proposal, never itself canonical (CLAUDE.md rule '
        '2) — implements the Generated -> Proposed -> Validated -> Approved '
        '-> Applied lifecycle (docs/ENTITY_LIFECYCLE.md §10). '
        'proposed_arguments is the exact keyword-argument payload the '
        'target domain command (named by proposal_kind) will be called with '
        'if approved — a legitimate JSONB use (conventions §5.7): a proposed '
        'command invocation awaiting a decision, structurally identical to '
        'integration.sync_jobs.payload_jsonb''s own "external payload '
        'snapshot" precedent. decided_by_user_id IS NULL with decided_at SET '
        'marks a policy auto-approval (dnd_ai.domain.ai_policy) rather than '
        'a human reviewer — see ai.change_reviews, which only exists for '
        'actual human decisions.';
    """)
    op.execute("""
        CREATE TRIGGER tr_proposed_changes_set_updated_at
        BEFORE UPDATE ON ai.proposed_changes
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_proposed_changes_generated_output_id "
        "ON ai.proposed_changes (generated_output_id);"
    )
    op.execute(
        "CREATE INDEX ix_proposed_changes_campaign_status "
        "ON ai.proposed_changes (campaign_id, status);"
    )
    op.execute(
        "CREATE INDEX ix_proposed_changes_applied_event_id "
        "ON ai.proposed_changes (applied_event_id) WHERE applied_event_id IS NOT NULL;"
    )

    # ==========================================================================
    # 10. ai.change_reviews
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE ai.change_reviews (
            ai_change_review_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ai_proposed_change_id    UUID NOT NULL
                                    REFERENCES ai.proposed_changes(ai_proposed_change_id)
                                    ON DELETE CASCADE,
            reviewer_user_id             UUID
                                    REFERENCES security.users(user_id) ON DELETE SET NULL,
            decision                        TEXT NOT NULL,
            comments                           TEXT,
            reviewed_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_change_reviews_decision CHECK (decision IN {_REVIEW_DECISIONS})
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.change_reviews IS
        'One human review decision for one ai.proposed_changes row — only '
        'created for an actual reviewer action (dnd_ai.commands.ai_proposals.'
        'review_proposed_change); an automatic policy approval never creates '
        'a row here (docs/architecture/DATABASE_MODEL.md §18), see '
        'ai.proposed_changes.decided_by_user_id''s own comment.';
    """)
    op.execute(
        "CREATE INDEX ix_change_reviews_ai_proposed_change_id "
        "ON ai.change_reviews (ai_proposed_change_id);"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS ai.change_reviews;")
    op.execute("DROP TABLE IF EXISTS ai.proposed_changes;")
    op.execute("DROP TABLE IF EXISTS ai.generated_outputs;")
    op.execute("DROP TABLE IF EXISTS ai.context_snapshots;")
    op.execute("DROP TABLE IF EXISTS ai.context_requests;")
    op.execute("DROP TABLE IF EXISTS ai.prompt_templates;")
    op.execute("DROP TABLE IF EXISTS ai.prompt_fragments;")

    op.execute("DROP TRIGGER IF EXISTS tr_agent_assignments_enforce_world ON ai.agent_assignments;")
    op.execute("DROP FUNCTION IF EXISTS ai.enforce_agent_assignment_world();")
    op.execute("DROP TABLE IF EXISTS ai.agent_assignments;")

    op.execute("DROP TABLE IF EXISTS ai.agents;")
    op.execute("DROP TABLE IF EXISTS ai.agent_roles;")
