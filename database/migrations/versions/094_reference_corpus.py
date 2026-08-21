"""Rules/reference-corpus ingestion and retrieval, and the two
security.resource_grants target columns this phase's tables unblock.

Revision ID: 094_reference_corpus
Revises: 093_ai_domain
Create Date: 2026-08-20 13:00:00.000000

Purpose:
    Phase 12's second increment: docs/PLAN.md §18.3's rules/reference
    corpus — "source registration and rights validation, immutable source/
    hash retention, structured extraction, passage provenance, PostgreSQL
    full-text indexing, filtered retrieval, citations, removal, and
    auditing." Deliberately a second migration after 093_ai_domain, since
    ai.reference_retrievals below references ai.context_requests.

    Table placement: docs/architecture/DATABASE_MODEL.md §5.5 already names
    `core.source_documents` as a planned core table (alongside the existing
    `core.sources`/`core.source_types`, which stay exactly as they are —
    they are lightweight "who authored this fact" provenance pointers, not
    the corpus's own richer registered-document record). §18.3 describes
    corpus *retrieval* as living "under the AI/context boundary" — the
    extracted/indexed/retrieved half (ai.reference_passages, ai.reference_
    source_campaigns, ai.reference_retrievals/.reference_retrieval_results)
    is built in the `ai` schema for that reason, while the registered
    document itself (core.source_documents) stays in `core` alongside its
    §5.5 siblings. There is no thirteenth "reference" schema to put any of
    this in — docs/DATABASE_CONVENTIONS.md §3's approved-schema list is
    fixed, and both `core` and `ai` already exist for exactly this split.

    security.resource_grants.source_document_id/.ai_proposed_change_id are
    two of the eight target columns docs/architecture/DATABASE_MODEL.md
    §19.6 lists but revision 080 deliberately deferred: "source_document_id,
    ai_proposed_change_id, and import_job_id are deferred to the migration
    that introduces their target table, per §19.6's own extension rule."
    Both target tables now exist (core.source_documents in this migration,
    ai.proposed_changes in 093_ai_domain), so both columns are added here,
    together, in one ALTER pass — see step 6 below. import_job_id remains
    deferred; no `import.*` table exists yet.

Forward migration:
    - core.source_documents, with a same-file-hash uniqueness guard and a
      status-consistency CHECK (removed_at set iff status = 'removed')
    - ai.reference_passages, with a generated tsvector column
      (content_tsv) and a GIN index — PostgreSQL-native full-text search,
      per §18.3's explicit "initial implementation uses ... PostgreSQL
      full-text search" instruction; no embeddings, no external search
      service
    - ai.reference_source_campaigns, with
      ai.enforce_reference_source_campaign_ruleset() — a campaign-scoped
      grant (including the "campaign house rule" precedence case) must
      share the source's own ruleset_version_id, or a GM could otherwise
      grant a mismatched-edition source into a campaign and silently mix
      editions, exactly what §18.3 forbids
    - ai.reference_retrievals / ai.reference_retrieval_results — the
      retrieval audit trail §18.3's "retrieval and downstream AI use are
      audited" requires, independent of ai.context_requests (a rules-
      question retrieval is not always driven by an agent invocation)
    - ALTER security.resource_grants: add source_document_id/
      ai_proposed_change_id, extend ck_resource_grants_exactly_one_target

Rollback:
    Supported. Reverts the resource_grants ALTER first (its CHECK
    constraint and new columns reference the tables being dropped), then
    drops everything created here in FK-dependency order.

Data implications:
    Creates no rows.

Locking considerations:
    Every CREATE statement creates a new, empty object. The
    security.resource_grants ALTER TABLE ADD COLUMN statements are
    metadata-only (nullable, no default requiring a rewrite); dropping and
    recreating ck_resource_grants_exactly_one_target validates the new
    CHECK against existing rows, which is cheap since every column it
    references already exists — the same "extend, revalidate" pattern
    089_foundry_system_credentials' own ALTER already used elsewhere in
    this project.

Deliberate scoping decisions:
    - core.source_documents.visibility ('general' | 'campaign_restricted')
      is how "campaigns or rulesets permitted to retrieve the source"
      (§18.3) is actually implemented: a 'general' source (a licensed SRD)
      is retrievable by any campaign whose own ruleset_version_id matches —
      checked in dnd_ai.queries.reference_corpus, not by a join table,
      since requiring one ai.reference_source_campaigns row per campaign
      for a source meant to apply to all of them would only be churn. A
      'campaign_restricted' source (homebrew, or a sourcebook only some
      campaigns are licensed for) requires an explicit
      ai.reference_source_campaigns row.
    - ai.reference_source_campaigns.is_house_rule is precedence metadata,
      not a separate table: §18.3's precedence order (house rules >
      campaign-selected sourcebooks > general references > model
      background) collapses to "is this grant flagged as a house rule"
      for the two campaign-scoped tiers; dnd_ai.queries.reference_corpus
      orders by (is_house_rule DESC, visibility) to implement it.
    - No entity-rooted / CTI shape for core.source_documents — a
      registered document is a corpus/administrative record, not a world
      entity with in-fiction identity (the same reasoning
      integration.external_systems already documented for itself).
    - allow_training defaults false and has no reader anywhere in this
      phase's application code — PLAN.md §18.3 requires recording whether
      training use is permitted, but also that "model training or
      fine-tuning requires a separate design ... ingested material is
      never training data by default." The column exists so the metadata
      §18.3 requires can be recorded now, without this phase building
      anything that acts on it.

See: docs/PLAN.md Phase 12 (Narrow AI/NPC MVP), §18.3
     docs/architecture/DATABASE_MODEL.md §5.5, §18, §19.6
     docs/DATABASE_CONVENTIONS.md §5.7 (JSONB), §9.5 (same-world/same-
     ruleset consistency triggers), "Names often benefit from trigram
     indexes. Documents and long descriptions may use generated tsvector
     columns."
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "094_reference_corpus"
down_revision = "093_ai_domain"
branch_labels = None
depends_on = None

_CLASSIFICATIONS = ("official", "third_party", "srd", "homebrew")
_USAGE_RIGHTS_STATUSES = (
    "verified_srd_license",
    "verified_licensed",
    "verified_owned",
    "verified_homebrew_authored",
    "pending_review",
)
_VISIBILITIES = ("general", "campaign_restricted")
_SOURCE_STATUSES = ("active", "superseded", "removed")


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.source_documents
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE core.source_documents (
            source_document_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_type_id             UUID NOT NULL
                                      REFERENCES core.source_types(source_type_id)
                                      ON DELETE RESTRICT,
            ruleset_version_id             UUID NOT NULL
                                      REFERENCES rules.ruleset_versions(ruleset_version_id)
                                      ON DELETE RESTRICT,
            title                              TEXT NOT NULL,
            publisher_or_author                   TEXT,
            classification                           TEXT NOT NULL,
            usage_rights_status                         TEXT NOT NULL DEFAULT 'pending_review',
            usage_rights_notes                             TEXT,
            file_hash                                         TEXT NOT NULL,
            file_hash_algorithm                                  TEXT NOT NULL DEFAULT 'sha256',
            source_version_label                                    TEXT NOT NULL,
            supersedes_source_document_id                              UUID
                                      REFERENCES core.source_documents(source_document_id)
                                      ON DELETE SET NULL,
            visibility                                                    TEXT NOT NULL
                                      DEFAULT 'campaign_restricted',
            allow_indexing                                                   BOOLEAN NOT NULL
                                      DEFAULT true,
            allow_quotation                                                     BOOLEAN NOT NULL
                                      DEFAULT true,
            allow_summarization                                                    BOOLEAN NOT NULL
                                      DEFAULT true,
            allow_export                                                              BOOLEAN NOT NULL
                                      DEFAULT false,
            allow_training                                                               BOOLEAN NOT NULL
                                      DEFAULT false,
            status                                                                          TEXT NOT NULL
                                      DEFAULT 'active',
            removed_at                                                                         TIMESTAMPTZ,
            removed_by_user_id                                                                    UUID
                                      REFERENCES security.users(user_id) ON DELETE SET NULL,
            removal_reason                                                                           TEXT,
            ingested_by_user_id                                                                         UUID
                                      REFERENCES security.users(user_id) ON DELETE SET NULL,
            created_at                                                                                     TIMESTAMPTZ
                                      NOT NULL DEFAULT now(),
            updated_at                                                                                     TIMESTAMPTZ
                                      NOT NULL DEFAULT now(),
            CONSTRAINT ux_source_documents_file_hash UNIQUE (file_hash),
            CONSTRAINT ck_source_documents_title_length CHECK (char_length(title) BETWEEN 1 AND 500),
            CONSTRAINT ck_source_documents_version_label_length
                CHECK (char_length(source_version_label) BETWEEN 1 AND 200),
            CONSTRAINT ck_source_documents_file_hash_format
                CHECK (file_hash ~ '^[0-9a-fA-F]{{32,128}}$'),
            CONSTRAINT ck_source_documents_classification CHECK (classification IN {_CLASSIFICATIONS}),
            CONSTRAINT ck_source_documents_usage_rights_status
                CHECK (usage_rights_status IN {_USAGE_RIGHTS_STATUSES}),
            CONSTRAINT ck_source_documents_visibility CHECK (visibility IN {_VISIBILITIES}),
            CONSTRAINT ck_source_documents_status CHECK (status IN {_SOURCE_STATUSES}),
            CONSTRAINT ck_source_documents_removed_consistency CHECK (
                (status = 'removed') = (removed_at IS NOT NULL)
            ),
            CONSTRAINT ck_source_documents_no_self_supersede CHECK (
                supersedes_source_document_id IS NULL
                OR supersedes_source_document_id <> source_document_id
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.source_documents IS
        'A registered reference/rules source — an authorized SRD, a '
        'licensed sourcebook, a homebrew document (docs/PLAN.md §18.3). '
        'Immutable identity: file_hash is unique and never reused; a '
        'revised edition is a new row with supersedes_source_document_id '
        'pointing at the one it replaces, not an in-place edit. Registering '
        'or ingesting a source never creates or mutates canonical campaign '
        'state — this table, ai.reference_passages, and '
        'ai.reference_source_campaigns are corpus/administrative records '
        'under the AI/context boundary, not campaign.* or narrative.* rows.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.source_documents.classification IS
        'official/third_party/srd/homebrew — the classification §18.3 '
        'requires recording, distinct from source_type_id (core.'
        'source_types, shared with core.sources — how the row was '
        'authored/imported, not what kind of publication it is).';
    """)
    op.execute("""
        COMMENT ON COLUMN core.source_documents.visibility IS
        '''general'': retrievable by any campaign whose own ruleset_'
        'version_id matches (a licensed SRD). ''campaign_restricted'': '
        'retrievable only by a campaign with an active '
        'ai.reference_source_campaigns grant (homebrew, or a sourcebook '
        'only some campaigns are licensed for).';
    """)
    op.execute("""
        CREATE TRIGGER tr_source_documents_set_updated_at
        BEFORE UPDATE ON core.source_documents
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_source_documents_ruleset_version_id "
        "ON core.source_documents (ruleset_version_id);"
    )
    op.execute(
        "CREATE INDEX ix_source_documents_active_ruleset "
        "ON core.source_documents (ruleset_version_id) WHERE status = 'active';"
    )
    op.execute("CREATE INDEX ix_source_documents_status ON core.source_documents (status);")
    op.execute(
        "CREATE INDEX ix_source_documents_supersedes "
        "ON core.source_documents (supersedes_source_document_id) "
        "WHERE supersedes_source_document_id IS NOT NULL;"
    )

    # ==========================================================================
    # 2. ai.reference_passages
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.reference_passages (
            reference_passage_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_document_id        UUID NOT NULL
                                     REFERENCES core.source_documents(source_document_id)
                                     ON DELETE CASCADE,
            passage_order                 INTEGER NOT NULL,
            chapter                          TEXT,
            section                             TEXT,
            page_label                            TEXT,
            heading                                  TEXT,
            content                                     TEXT NOT NULL,
            content_tsv                                     TSVECTOR
                GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
            created_at                                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_reference_passages_source_order UNIQUE (source_document_id, passage_order),
            CONSTRAINT ck_reference_passages_content_length
                CHECK (char_length(content) BETWEEN 1 AND 20000),
            CONSTRAINT ck_reference_passages_order_nonnegative CHECK (passage_order >= 0)
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.reference_passages IS
        'One retrievable, citable chunk of a registered source document '
        '(docs/PLAN.md §18.3): chapter/section/page_label carry citation '
        'location, content_tsv is a generated, indexed tsvector column — '
        'PostgreSQL-native full-text search, no embeddings or external '
        'search service for this phase. passage_order is the source''s own '
        'ordinal position, used for deterministic tie-breaking and as a '
        'stable citation reference alongside chapter/section/page_label.';
    """)
    op.execute(
        "CREATE INDEX ix_reference_passages_source_document_id "
        "ON ai.reference_passages (source_document_id);"
    )
    op.execute(
        "CREATE INDEX ix_reference_passages_content_tsv "
        "ON ai.reference_passages USING GIN (content_tsv);"
    )

    # ==========================================================================
    # 3. ai.reference_source_campaigns
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.reference_source_campaigns (
            reference_source_campaign_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_document_id                UUID NOT NULL
                                             REFERENCES core.source_documents(source_document_id)
                                             ON DELETE CASCADE,
            campaign_id                          UUID NOT NULL
                                             REFERENCES campaign.campaigns(campaign_id)
                                             ON DELETE CASCADE,
            is_house_rule                            BOOLEAN NOT NULL DEFAULT false,
            granted_at                                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            granted_by_user_id                             UUID
                                             REFERENCES security.users(user_id) ON DELETE SET NULL,
            revoked_at                                        TIMESTAMPTZ
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.reference_source_campaigns IS
        'Explicit per-campaign retrieval grant for a ''campaign_restricted'' '
        'core.source_documents row (docs/PLAN.md §18.3) — never needed for '
        'a ''general'' source, which any same-ruleset campaign may already '
        'retrieve. is_house_rule marks the grant as this campaign''s own '
        'override, taking retrieval precedence over a general source for '
        'the same ruleset (dnd_ai.queries.reference_corpus). Revoked, not '
        'deleted, so grant history remains auditable; the partial unique '
        'index below allows re-granting after a revocation.';
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_reference_source_campaigns_active
        ON ai.reference_source_campaigns (source_document_id, campaign_id)
        WHERE revoked_at IS NULL;
    """)
    op.execute(
        "CREATE INDEX ix_reference_source_campaigns_campaign_id "
        "ON ai.reference_source_campaigns (campaign_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION ai.enforce_reference_source_campaign_ruleset()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_source_ruleset_version    UUID;
            v_campaign_ruleset_version  UUID;
        BEGIN
            SELECT ruleset_version_id INTO v_source_ruleset_version
            FROM core.source_documents WHERE source_document_id = NEW.source_document_id;

            SELECT ruleset_version_id INTO v_campaign_ruleset_version
            FROM campaign.campaigns WHERE campaign_id = NEW.campaign_id;

            IF v_source_ruleset_version IS DISTINCT FROM v_campaign_ruleset_version THEN
                RAISE EXCEPTION
                    'Reference source % is pinned to ruleset version %, but campaign % is '
                    'pinned to ruleset version % — a source may only be granted to a campaign '
                    'on the same ruleset version',
                    NEW.source_document_id, v_source_ruleset_version, NEW.campaign_id,
                    v_campaign_ruleset_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION ai.enforce_reference_source_campaign_ruleset() IS
        'Same-ruleset-version guard for ai.reference_source_campaigns '
        '(conventions §9.5) — closes the one gap visibility/grants alone '
        'do not: without this, a GM could grant a source pinned to one '
        'edition into a campaign pinned to a different one, silently '
        'mixing editions, which docs/PLAN.md §18.3 explicitly forbids.';
    """)
    op.execute("""
        CREATE TRIGGER tr_reference_source_campaigns_enforce_ruleset
        BEFORE INSERT OR UPDATE ON ai.reference_source_campaigns
        FOR EACH ROW EXECUTE FUNCTION ai.enforce_reference_source_campaign_ruleset();
    """)

    # ==========================================================================
    # 4. ai.reference_retrievals / ai.reference_retrieval_results
    # ==========================================================================
    op.execute("""
        CREATE TABLE ai.reference_retrievals (
            reference_retrieval_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id                 UUID NOT NULL
                                       REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            requested_by_user_id           UUID
                                       REFERENCES security.users(user_id) ON DELETE SET NULL,
            context_request_id                UUID
                                       REFERENCES ai.context_requests(context_request_id)
                                       ON DELETE SET NULL,
            query_text                           TEXT NOT NULL,
            ruleset_version_id                      UUID NOT NULL
                                       REFERENCES rules.ruleset_versions(ruleset_version_id)
                                       ON DELETE RESTRICT,
            created_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_reference_retrievals_query_text_length
                CHECK (char_length(query_text) BETWEEN 1 AND 2000)
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.reference_retrievals IS
        'One corpus retrieval — the audit trail docs/PLAN.md §18.3 requires '
        '("retrieval and downstream AI use are audited"), independent of '
        'ai.context_requests: context_request_id is set when the retrieval '
        'happened as part of an agent invocation (dnd_ai.commands.ai_npc), '
        'NULL for a standalone rules-question lookup with no agent call '
        'attached.';
    """)
    op.execute(
        "CREATE INDEX ix_reference_retrievals_campaign_id ON ai.reference_retrievals (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_reference_retrievals_context_request_id "
        "ON ai.reference_retrievals (context_request_id) WHERE context_request_id IS NOT NULL;"
    )

    op.execute("""
        CREATE TABLE ai.reference_retrieval_results (
            reference_retrieval_id   UUID NOT NULL
                                    REFERENCES ai.reference_retrievals(reference_retrieval_id)
                                    ON DELETE CASCADE,
            reference_passage_id        UUID NOT NULL
                                    REFERENCES ai.reference_passages(reference_passage_id)
                                    ON DELETE CASCADE,
            rank                            INTEGER NOT NULL,
            relevance_score                    REAL,
            PRIMARY KEY (reference_retrieval_id, reference_passage_id),
            CONSTRAINT ck_reference_retrieval_results_rank_positive CHECK (rank >= 1)
        );
    """)
    op.execute("""
        COMMENT ON TABLE ai.reference_retrieval_results IS
        'One returned, cited passage for one ai.reference_retrievals row, '
        'in rank order — preserves exactly what was retrieved and in what '
        'order, for audit and reproducibility.';
    """)
    op.execute(
        "CREATE INDEX ix_reference_retrieval_results_passage_id "
        "ON ai.reference_retrieval_results (reference_passage_id);"
    )

    # ==========================================================================
    # 5. security.resource_grants — the two deferred target columns this
    #    migration's own tables (and 093_ai_domain's ai.proposed_changes)
    #    unblock (see this migration's docstring).
    # ==========================================================================
    op.execute(
        "ALTER TABLE security.resource_grants ADD COLUMN source_document_id UUID "
        "REFERENCES core.source_documents(source_document_id) ON DELETE CASCADE;"
    )
    op.execute(
        "ALTER TABLE security.resource_grants ADD COLUMN ai_proposed_change_id UUID "
        "REFERENCES ai.proposed_changes(ai_proposed_change_id) ON DELETE CASCADE;"
    )
    op.execute(
        "ALTER TABLE security.resource_grants "
        "DROP CONSTRAINT ck_resource_grants_exactly_one_target;"
    )
    op.execute("""
        ALTER TABLE security.resource_grants
        ADD CONSTRAINT ck_resource_grants_exactly_one_target CHECK (
            num_nonnulls(
                character_id, entity_id, knowledge_item_id, quest_id, session_id, event_id,
                source_document_id, ai_proposed_change_id
            ) = 1
        );
    """)
    op.execute(
        "CREATE INDEX ix_resource_grants_source_document_id "
        "ON security.resource_grants (source_document_id) WHERE source_document_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_resource_grants_ai_proposed_change_id "
        "ON security.resource_grants (ai_proposed_change_id) WHERE ai_proposed_change_id IS NOT NULL;"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP INDEX IF EXISTS security.ix_resource_grants_ai_proposed_change_id;")
    op.execute("DROP INDEX IF EXISTS security.ix_resource_grants_source_document_id;")
    op.execute(
        "ALTER TABLE security.resource_grants "
        "DROP CONSTRAINT IF EXISTS ck_resource_grants_exactly_one_target;"
    )
    op.execute("""
        ALTER TABLE security.resource_grants
        ADD CONSTRAINT ck_resource_grants_exactly_one_target CHECK (
            num_nonnulls(
                character_id, entity_id, knowledge_item_id, quest_id, session_id, event_id
            ) = 1
        );
    """)
    op.execute("ALTER TABLE security.resource_grants DROP COLUMN IF EXISTS ai_proposed_change_id;")
    op.execute("ALTER TABLE security.resource_grants DROP COLUMN IF EXISTS source_document_id;")

    op.execute("DROP TABLE IF EXISTS ai.reference_retrieval_results;")
    op.execute("DROP TABLE IF EXISTS ai.reference_retrievals;")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_reference_source_campaigns_enforce_ruleset "
        "ON ai.reference_source_campaigns;"
    )
    op.execute("DROP FUNCTION IF EXISTS ai.enforce_reference_source_campaign_ruleset();")
    op.execute("DROP TABLE IF EXISTS ai.reference_source_campaigns;")

    op.execute("DROP TABLE IF EXISTS ai.reference_passages;")

    op.execute("DROP TABLE IF EXISTS core.source_documents;")
