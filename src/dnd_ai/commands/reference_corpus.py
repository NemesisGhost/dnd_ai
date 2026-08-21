"""RegisterSourceDocument, IngestReferencePassages, GrantSourceToCampaign,
RevokeSourceCampaignGrant, RemoveSourceDocument, and RetrieveCitedPassages —
the rules/reference-corpus commands docs/PLAN.md §18.3 describes.

Registration, ingestion, granting, and removal never create or mutate
canonical campaign state (§18.3's own exit criterion) — none of the
functions below touch `campaign.*`, `narrative.*`, or any other canonical
table; they write only `core.source_documents` and `ai.reference_*` rows,
and never call `dnd_ai.commands.events._insert_event_row`. There is
deliberately no causal-event requirement here (CLAUDE.md rule 6 governs
canonical *world* state changes; a corpus registration is neither).

`retrieve_cited_passages` is the one function in this module that performs a
write alongside its read: every retrieval is audited
(`ai.reference_retrievals`/`.reference_retrieval_results`), per §18.3's
"retrieval and downstream AI use are audited." That write is why this lives
in `commands/`, not `queries/` — `dnd_ai.queries.*` modules are
framework-free reads with no side effect, and this function has one.

Full-text search: `websearch_to_tsquery('english', ...)`, which accepts
ordinary natural-language query text (quoted phrases, `-exclusion`) rather
than requiring the caller to construct `tsquery` syntax — the "PostgreSQL
full-text indexing"/"deterministic passage selection where practical" §18.3
calls for, no embeddings.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

from ._shared import lookup_id


class SourceDocumentNotFoundError(DomainAuthorizationError):
    """Raised for a `source_document_id` that does not resolve to an
    existing `core.source_documents` row. Inherits the fixed, non-
    disclosing 404 contract — a registered source's own existence can be
    sensitive (an unreleased homebrew document, a licensed sourcebook a
    campaign is not entitled to know about), the same reasoning
    `dnd_ai.queries.knowledge.KnowledgeNotAuthorizedError` already applies
    to a knowledge item. The supplied id is included only in the
    constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


class SourceDocumentNotIndexableError(SafeMessageError):
    """Raised by `ingest_reference_passages()` when the target source's own
    `allow_indexing` is `false` — a registered source that opted out of
    indexing must never have retrievable passages, regardless of who is
    calling."""

    safe_error_code = "source_not_indexable"
    safe_message = "This source document does not permit indexing."


class DuplicateFileHashError(SafeMessageError):
    """Raised by `register_source_document()` for a `file_hash` that
    already has a `core.source_documents` row — `ux_source_documents_
    file_hash` is the database-level backstop; this is the same check
    surfaced as a clean, typed error before the INSERT even runs, matching
    `dnd_ai.commands._shared.lookup_id`'s "resolve before writing" posture
    elsewhere in this codebase."""

    safe_status_code = 409
    safe_error_code = "duplicate_source_file_hash"
    safe_message = "A source document with this file hash is already registered."


@dataclass(frozen=True)
class PassageInput:
    passage_order: int
    content: str
    chapter: str | None = None
    section: str | None = None
    page_label: str | None = None
    heading: str | None = None


@dataclass(frozen=True)
class CitedPassage:
    reference_passage_id: uuid.UUID
    source_document_id: uuid.UUID
    source_title: str
    chapter: str | None
    section: str | None
    page_label: str | None
    heading: str | None
    content: str
    is_house_rule: bool
    rank: int
    relevance_score: float


def _register_source_document_impl(
    connection: Connection,
    *,
    source_type_code: str,
    ruleset_version_id: uuid.UUID,
    title: str,
    classification: str,
    file_hash: str,
    source_version_label: str,
    publisher_or_author: str | None = None,
    usage_rights_status: str = "pending_review",
    usage_rights_notes: str | None = None,
    file_hash_algorithm: str = "sha256",
    supersedes_source_document_id: uuid.UUID | None = None,
    visibility: str = "campaign_restricted",
    allow_indexing: bool = True,
    allow_quotation: bool = True,
    allow_summarization: bool = True,
    allow_export: bool = False,
    allow_training: bool = False,
    ingested_by_user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """The actual work of `register_source_document()`, on a connection the
    caller already has open — see `dnd_ai.commands.quests._advance_
    objective_impl`'s docstring for the composable-implementation/public-
    wrapper pattern this mirrors. `dnd_ai.api.reference_corpus` calls this
    directly on the request's own connection so the resulting `audit.
    change_log` row commits atomically with the insert it describes."""
    existing = connection.execute(
        text("SELECT 1 FROM core.source_documents WHERE file_hash = :hash"),
        {"hash": file_hash},
    ).scalar()
    if existing is not None:
        raise DuplicateFileHashError()

    source_type_id = lookup_id(
        connection, "core", "source_types", "source_type_id", source_type_code
    )
    source_document_id = connection.execute(
        text("""
                INSERT INTO core.source_documents
                    (source_type_id, ruleset_version_id, title, publisher_or_author,
                     classification, usage_rights_status, usage_rights_notes, file_hash,
                     file_hash_algorithm, source_version_label, supersedes_source_document_id,
                     visibility, allow_indexing, allow_quotation, allow_summarization,
                     allow_export, allow_training, ingested_by_user_id)
                VALUES
                    (:source_type, :ruleset_version, :title, :publisher, :classification,
                     :usage_rights_status, :usage_rights_notes, :file_hash, :file_hash_algorithm,
                     :source_version_label, :supersedes, :visibility, :allow_indexing,
                     :allow_quotation, :allow_summarization, :allow_export, :allow_training,
                     :ingested_by)
                RETURNING source_document_id
            """),
        {
            "source_type": source_type_id,
            "ruleset_version": ruleset_version_id,
            "title": title,
            "publisher": publisher_or_author,
            "classification": classification,
            "usage_rights_status": usage_rights_status,
            "usage_rights_notes": usage_rights_notes,
            "file_hash": file_hash,
            "file_hash_algorithm": file_hash_algorithm,
            "source_version_label": source_version_label,
            "supersedes": supersedes_source_document_id,
            "visibility": visibility,
            "allow_indexing": allow_indexing,
            "allow_quotation": allow_quotation,
            "allow_summarization": allow_summarization,
            "allow_export": allow_export,
            "allow_training": allow_training,
            "ingested_by": ingested_by_user_id,
        },
    ).scalar()
    assert isinstance(source_document_id, uuid.UUID)
    return source_document_id


def register_source_document(
    engine: Engine,
    *,
    source_type_code: str,
    ruleset_version_id: uuid.UUID,
    title: str,
    classification: str,
    file_hash: str,
    source_version_label: str,
    publisher_or_author: str | None = None,
    usage_rights_status: str = "pending_review",
    usage_rights_notes: str | None = None,
    file_hash_algorithm: str = "sha256",
    supersedes_source_document_id: uuid.UUID | None = None,
    visibility: str = "campaign_restricted",
    allow_indexing: bool = True,
    allow_quotation: bool = True,
    allow_summarization: bool = True,
    allow_export: bool = False,
    allow_training: bool = False,
    ingested_by_user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Register one immutable source document, atomically. Public
    convenience API: opens and commits its own transaction. See
    `_register_source_document_impl()` for the composable form a caller
    with its own transaction (e.g. an API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _register_source_document_impl(
            connection,
            source_type_code=source_type_code,
            ruleset_version_id=ruleset_version_id,
            title=title,
            classification=classification,
            file_hash=file_hash,
            source_version_label=source_version_label,
            publisher_or_author=publisher_or_author,
            usage_rights_status=usage_rights_status,
            usage_rights_notes=usage_rights_notes,
            file_hash_algorithm=file_hash_algorithm,
            supersedes_source_document_id=supersedes_source_document_id,
            visibility=visibility,
            allow_indexing=allow_indexing,
            allow_quotation=allow_quotation,
            allow_summarization=allow_summarization,
            allow_export=allow_export,
            allow_training=allow_training,
            ingested_by_user_id=ingested_by_user_id,
        )


def _ingest_reference_passages_impl(
    connection: Connection, *, source_document_id: uuid.UUID, passages: tuple[PassageInput, ...]
) -> tuple[uuid.UUID, ...]:
    """The actual work of `ingest_reference_passages()`, on a connection the
    caller already has open. Structured extraction itself (turning a source
    document's raw text into discrete, citation-located passages) is an
    operator/tooling step outside this database, per §18.3's own
    "structured extraction ... deterministic passage selection where
    practical" — this command's input is the result of that step, not raw
    document bytes; no PDF/OCR/NLP pipeline lives in this codebase."""
    allow_indexing = connection.execute(
        text("SELECT allow_indexing FROM core.source_documents WHERE source_document_id = :id"),
        {"id": source_document_id},
    ).scalar()
    if allow_indexing is None:
        raise SourceDocumentNotFoundError(f"source document {source_document_id} not found")
    if not allow_indexing:
        raise SourceDocumentNotIndexableError()

    passage_ids: list[uuid.UUID] = []
    for passage in passages:
        passage_id = connection.execute(
            text("""
                INSERT INTO ai.reference_passages
                    (source_document_id, passage_order, chapter, section, page_label,
                     heading, content)
                VALUES (:source, :order, :chapter, :section, :page, :heading, :content)
                RETURNING reference_passage_id
            """),
            {
                "source": source_document_id,
                "order": passage.passage_order,
                "chapter": passage.chapter,
                "section": passage.section,
                "page": passage.page_label,
                "heading": passage.heading,
                "content": passage.content,
            },
        ).scalar()
        assert isinstance(passage_id, uuid.UUID)
        passage_ids.append(passage_id)
    return tuple(passage_ids)


def ingest_reference_passages(
    engine: Engine, *, source_document_id: uuid.UUID, passages: tuple[PassageInput, ...]
) -> tuple[uuid.UUID, ...]:
    """Insert the already-extracted, already-structured passages for a
    source document, atomically. Public convenience API: opens and commits
    its own transaction. See `_ingest_reference_passages_impl()` for the
    composable form."""
    with engine.begin() as connection:
        return _ingest_reference_passages_impl(
            connection, source_document_id=source_document_id, passages=passages
        )


def grant_source_to_campaign(
    engine: Engine,
    *,
    source_document_id: uuid.UUID,
    campaign_id: uuid.UUID,
    is_house_rule: bool = False,
    granted_by_user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Grant one campaign explicit retrieval access to one source document
    — required for a `visibility = 'campaign_restricted'` source (harmless,
    if redundant, for a `'general'` one, which is already retrievable by
    ruleset match alone); see `dnd_ai.queries` module-level reasoning in
    `094_reference_corpus`'s migration docstring. `ai.enforce_reference_
    source_campaign_ruleset()` rejects a mismatched-edition grant at the
    database layer; this function does not pre-check it, matching how
    every other same-world/same-ruleset trigger in this codebase is relied
    on rather than duplicated in application code."""
    with engine.begin() as connection:
        grant_id = connection.execute(
            text("""
                INSERT INTO ai.reference_source_campaigns
                    (source_document_id, campaign_id, is_house_rule, granted_by_user_id)
                VALUES (:source, :campaign, :house_rule, :granted_by)
                RETURNING reference_source_campaign_id
            """),
            {
                "source": source_document_id,
                "campaign": campaign_id,
                "house_rule": is_house_rule,
                "granted_by": granted_by_user_id,
            },
        ).scalar()
        assert isinstance(grant_id, uuid.UUID)
        return grant_id


def revoke_source_campaign_grant(
    engine: Engine, *, reference_source_campaign_id: uuid.UUID
) -> None:
    """Revoke (not delete) a campaign's retrieval grant — the row remains
    for audit history; `ux_reference_source_campaigns_active`'s partial
    uniqueness allows re-granting afterward."""
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE ai.reference_source_campaigns
                SET revoked_at = now()
                WHERE reference_source_campaign_id = :grant AND revoked_at IS NULL
            """),
            {"grant": reference_source_campaign_id},
        )


def _remove_source_document_impl(
    connection: Connection,
    *,
    source_document_id: uuid.UUID,
    removed_by_user_id: uuid.UUID | None,
    removal_reason: str | None = None,
) -> None:
    """The actual work of `remove_source_document()`, on a connection the
    caller already has open — `dnd_ai.api.reference_corpus` calls this
    directly so its `audit.change_log` row commits atomically. Marks a
    source removed — never a physical delete (CLAUDE.md rule 9);
    `retrieve_cited_passages()` only ever considers `status = 'active'`
    sources, so a removed source's passages become unavailable to later
    retrieval immediately, per §18.3's own exit criterion, without losing
    the row's history."""
    updated = connection.execute(
        text("""
            UPDATE core.source_documents
            SET status = 'removed', removed_at = now(), removed_by_user_id = :removed_by,
                removal_reason = :reason
            WHERE source_document_id = :id AND status <> 'removed'
            RETURNING source_document_id
        """),
        {"id": source_document_id, "removed_by": removed_by_user_id, "reason": removal_reason},
    ).scalar()
    if updated is None:
        raise SourceDocumentNotFoundError(f"source document {source_document_id} not found")


def remove_source_document(
    engine: Engine,
    *,
    source_document_id: uuid.UUID,
    removed_by_user_id: uuid.UUID | None,
    removal_reason: str | None = None,
) -> None:
    """Mark a source removed, atomically. Public convenience API: opens and
    commits its own transaction. See `_remove_source_document_impl()` for
    the composable form."""
    with engine.begin() as connection:
        _remove_source_document_impl(
            connection,
            source_document_id=source_document_id,
            removed_by_user_id=removed_by_user_id,
            removal_reason=removal_reason,
        )


def _retrieve_cited_passages_impl(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    query_text: str,
    requested_by_user_id: uuid.UUID | None,
    context_request_id: uuid.UUID | None,
    limit: int,
) -> tuple[CitedPassage, ...]:
    ruleset_version_id = connection.execute(
        text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :campaign"),
        {"campaign": campaign_id},
    ).scalar()
    if ruleset_version_id is None:
        raise SourceDocumentNotFoundError(f"campaign {campaign_id} not found")

    rows = connection.execute(
        text("""
            SELECT
                p.reference_passage_id, p.source_document_id, sd.title, p.chapter, p.section,
                p.page_label, p.heading, p.content,
                COALESCE(bool_or(rsc.is_house_rule), false) AS is_house_rule,
                ts_rank(p.content_tsv, websearch_to_tsquery('english', :query)) AS relevance_score
            FROM ai.reference_passages p
            JOIN core.source_documents sd ON sd.source_document_id = p.source_document_id
            LEFT JOIN ai.reference_source_campaigns rsc
                ON rsc.source_document_id = sd.source_document_id
               AND rsc.campaign_id = :campaign
               AND rsc.revoked_at IS NULL
            WHERE sd.status = 'active'
              AND sd.ruleset_version_id = :ruleset_version
              AND (sd.visibility = 'general' OR rsc.reference_source_campaign_id IS NOT NULL)
              AND p.content_tsv @@ websearch_to_tsquery('english', :query)
            GROUP BY p.reference_passage_id, p.source_document_id, sd.title, p.chapter,
                     p.section, p.page_label, p.heading, p.content
            ORDER BY is_house_rule DESC, relevance_score DESC, p.passage_order ASC
            LIMIT :limit
        """),
        {
            "campaign": campaign_id,
            "ruleset_version": ruleset_version_id,
            "query": query_text,
            "limit": limit,
        },
    ).all()

    retrieval_id = connection.execute(
        text("""
            INSERT INTO ai.reference_retrievals
                (campaign_id, requested_by_user_id, context_request_id, query_text,
                 ruleset_version_id)
            VALUES (:campaign, :requested_by, :context_request, :query, :ruleset_version)
            RETURNING reference_retrieval_id
        """),
        {
            "campaign": campaign_id,
            "requested_by": requested_by_user_id,
            "context_request": context_request_id,
            "query": query_text,
            "ruleset_version": ruleset_version_id,
        },
    ).scalar()
    assert isinstance(retrieval_id, uuid.UUID)

    results = []
    for rank, row in enumerate(rows, start=1):
        connection.execute(
            text("""
                INSERT INTO ai.reference_retrieval_results
                    (reference_retrieval_id, reference_passage_id, rank, relevance_score)
                VALUES (:retrieval, :passage, :rank, :score)
            """),
            {
                "retrieval": retrieval_id,
                "passage": row.reference_passage_id,
                "rank": rank,
                "score": float(row.relevance_score),
            },
        )
        results.append(
            CitedPassage(
                reference_passage_id=row.reference_passage_id,
                source_document_id=row.source_document_id,
                source_title=row.title,
                chapter=row.chapter,
                section=row.section,
                page_label=row.page_label,
                heading=row.heading,
                content=row.content,
                is_house_rule=row.is_house_rule,
                rank=rank,
                relevance_score=float(row.relevance_score),
            )
        )
    return tuple(results)


def retrieve_cited_passages(
    engine: Engine,
    *,
    campaign_id: uuid.UUID,
    query_text: str,
    requested_by_user_id: uuid.UUID | None = None,
    context_request_id: uuid.UUID | None = None,
    limit: int = 5,
) -> tuple[CitedPassage, ...]:
    """Retrieve cited passages for `query_text`, filtered to the campaign's
    own selected ruleset/edition and authorized sources, ordered by §18.3's
    precedence (campaign house rule first, then relevance), and record the
    retrieval for audit (`ai.reference_retrievals`/
    `.reference_retrieval_results`). Opens and commits its own transaction
    — see this module's docstring for why this is a command, not a query,
    despite being read-mostly.

    A conflicting edition is excluded structurally (`sd.ruleset_version_id
    = :ruleset_version`, the campaign's own pinned version — never any
    other edition's passages, even from an otherwise-authorized source);
    an unauthorized source is excluded by the `visibility`/grant predicate.
    Passages from a source with `usage_rights_status = 'pending_review'`
    are still retrievable once ingested — this function does not
    re-validate usage rights on every read, matching `docs/architecture/
    DATABASE_MODEL.md §8`'s "source presence/validation is an application-
    command obligation" precedent: an operator who calls `ingest_reference_
    passages()` before rights review is complete is responsible for that
    choice, the same way registering unverified content is."""
    with engine.begin() as connection:
        return _retrieve_cited_passages_impl(
            connection,
            campaign_id=campaign_id,
            query_text=query_text,
            requested_by_user_id=requested_by_user_id,
            context_request_id=context_request_id,
            limit=limit,
        )
