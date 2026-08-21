"""Rules/reference-corpus command and query endpoints (docs/PLAN.md §18.3).

Authorization: registration, ingestion, granting, and removal all require
`rules_source.manage` — a capability this codebase's own seed data already
named for exactly this purpose (`database/seeds/security.capabilities.
yaml`) but that had no route using it until this module. Retrieval requires
only `campaign.view`, the read-only counterpart every other query endpoint
in this codebase uses — any campaign member, not only the GM, may ask a
rules question.

`core.source_documents` is not itself campaign-owned (it is ruleset-scoped,
potentially shared across many campaigns — see `094_reference_corpus`'s
migration docstring), so every route here is still authorized through a
specific campaign's own `AccessContext`, the same posture `dnd_ai.api.
campaigns`' own docstring documents as the one deliberate exception
notwithstanding: a corpus-management action is performed *as* a GM of some
campaign, even though the resulting resource is not exclusively that
campaign's.

No `Idempotency-Key` support on the mutating routes here (register/ingest/
grant/revoke/remove) — a deliberate scope reduction, not an oversight.
`register_source_document`'s own `ux_source_documents_file_hash` uniqueness
already rejects a byte-identical retry with a clean, typed 409
(`DuplicateFileHashError`), which covers the one duplicate-side-effect risk
that actually matters for this route; the others (ingest/grant/revoke/
remove) are administrative, GM-only, low-frequency actions with no exit
criterion requiring durable retry-safety, unlike the player-facing,
high-frequency command routes (`dnd_ai.api.items`/`.encounters`) that do
implement it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine

from dnd_ai.commands.reference_corpus import (
    CitedPassage,
    PassageInput,
    _register_source_document_impl,
    _remove_source_document_impl,
    grant_source_to_campaign,
    ingest_reference_passages,
    retrieve_cited_passages,
    revoke_source_campaign_grant,
)
from dnd_ai.domain.access import AccessContext

from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_engine

router = APIRouter(tags=["reference-corpus"])

_MANAGE_CAPABILITY = "rules_source.manage"
_VIEW_CAPABILITY = "campaign.view"

_REGISTER_COMMAND_NAME = "register_source_document"
_REMOVE_COMMAND_NAME = "remove_source_document"


class RegisterSourceDocumentRequest(BaseModel):
    source_type_code: str
    ruleset_version_id: uuid.UUID
    title: str
    classification: str
    file_hash: str
    source_version_label: str
    publisher_or_author: str | None = None
    usage_rights_status: str = "pending_review"
    usage_rights_notes: str | None = None
    file_hash_algorithm: str = "sha256"
    supersedes_source_document_id: uuid.UUID | None = None
    visibility: str = "campaign_restricted"
    allow_indexing: bool = True
    allow_quotation: bool = True
    allow_summarization: bool = True
    allow_export: bool = False
    allow_training: bool = False


class RegisterSourceDocumentResponse(BaseModel):
    source_document_id: uuid.UUID


class PassageRequest(BaseModel):
    passage_order: int
    content: str = Field(min_length=1, max_length=20000)
    chapter: str | None = None
    section: str | None = None
    page_label: str | None = None
    heading: str | None = None


class IngestReferencePassagesRequest(BaseModel):
    passages: list[PassageRequest]


class IngestReferencePassagesResponse(BaseModel):
    reference_passage_ids: list[uuid.UUID]


class GrantSourceToCampaignRequest(BaseModel):
    is_house_rule: bool = False


class GrantSourceToCampaignResponse(BaseModel):
    reference_source_campaign_id: uuid.UUID


class RetrieveCitedPassagesRequest(BaseModel):
    query_text: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


class CitedPassageResponse(BaseModel):
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

    @classmethod
    def from_domain(cls, passage: CitedPassage) -> "CitedPassageResponse":
        return cls(
            reference_passage_id=passage.reference_passage_id,
            source_document_id=passage.source_document_id,
            source_title=passage.source_title,
            chapter=passage.chapter,
            section=passage.section,
            page_label=passage.page_label,
            heading=passage.heading,
            content=passage.content,
            is_house_rule=passage.is_house_rule,
            rank=passage.rank,
            relevance_score=passage.relevance_score,
        )


class RetrieveCitedPassagesResponse(BaseModel):
    passages: list[CitedPassageResponse]


@router.post(
    "/campaigns/{campaign_id}/reference-corpus/sources",
    response_model=RegisterSourceDocumentResponse,
    status_code=201,
)
def register_source_document_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001
    body: RegisterSourceDocumentRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_MANAGE_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> RegisterSourceDocumentResponse:
    source_document_id = _register_source_document_impl(
        connection,
        source_type_code=body.source_type_code,
        ruleset_version_id=body.ruleset_version_id,
        title=body.title,
        classification=body.classification,
        file_hash=body.file_hash,
        source_version_label=body.source_version_label,
        publisher_or_author=body.publisher_or_author,
        usage_rights_status=body.usage_rights_status,
        usage_rights_notes=body.usage_rights_notes,
        file_hash_algorithm=body.file_hash_algorithm,
        supersedes_source_document_id=body.supersedes_source_document_id,
        visibility=body.visibility,
        allow_indexing=body.allow_indexing,
        allow_quotation=body.allow_quotation,
        allow_summarization=body.allow_summarization,
        allow_export=body.allow_export,
        allow_training=body.allow_training,
        ingested_by_user_id=access.user_id,
    )
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="core",
        table_name="source_documents",
        record_id=source_document_id,
        entity_id=None,
        world_id=None,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_REGISTER_COMMAND_NAME,
        event_id=None,
    )
    return RegisterSourceDocumentResponse(source_document_id=source_document_id)


@router.post(
    "/campaigns/{campaign_id}/reference-corpus/sources/{source_document_id}/passages",
    response_model=IngestReferencePassagesResponse,
    status_code=201,
)
def ingest_reference_passages_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001
    source_document_id: uuid.UUID,
    body: IngestReferencePassagesRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_MANAGE_CAPABILITY))],  # noqa: ARG001
    engine: Annotated[Engine, Depends(get_engine)],
) -> IngestReferencePassagesResponse:
    passage_ids = ingest_reference_passages(
        engine,
        source_document_id=source_document_id,
        passages=tuple(
            PassageInput(
                passage_order=p.passage_order,
                content=p.content,
                chapter=p.chapter,
                section=p.section,
                page_label=p.page_label,
                heading=p.heading,
            )
            for p in body.passages
        ),
    )
    return IngestReferencePassagesResponse(reference_passage_ids=list(passage_ids))


@router.post(
    "/campaigns/{campaign_id}/reference-corpus/sources/{source_document_id}/grant",
    response_model=GrantSourceToCampaignResponse,
    status_code=201,
)
def grant_source_to_campaign_endpoint(
    campaign_id: uuid.UUID,
    source_document_id: uuid.UUID,
    body: GrantSourceToCampaignRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_MANAGE_CAPABILITY))],
    engine: Annotated[Engine, Depends(get_engine)],
) -> GrantSourceToCampaignResponse:
    grant_id = grant_source_to_campaign(
        engine,
        source_document_id=source_document_id,
        campaign_id=campaign_id,
        is_house_rule=body.is_house_rule,
        granted_by_user_id=access.user_id,
    )
    return GrantSourceToCampaignResponse(reference_source_campaign_id=grant_id)


@router.delete(
    "/campaigns/{campaign_id}/reference-corpus/grants/{reference_source_campaign_id}",
    status_code=204,
)
def revoke_source_campaign_grant_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001
    reference_source_campaign_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_MANAGE_CAPABILITY))],  # noqa: ARG001
    engine: Annotated[Engine, Depends(get_engine)],
) -> None:
    revoke_source_campaign_grant(engine, reference_source_campaign_id=reference_source_campaign_id)


@router.delete(
    "/campaigns/{campaign_id}/reference-corpus/sources/{source_document_id}", status_code=204
)
def remove_source_document_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001
    source_document_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_MANAGE_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> None:
    _remove_source_document_impl(
        connection, source_document_id=source_document_id, removed_by_user_id=access.user_id
    )
    record_change_log(
        connection,
        change_action_code="archived",
        schema_name="core",
        table_name="source_documents",
        record_id=source_document_id,
        entity_id=None,
        world_id=None,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_REMOVE_COMMAND_NAME,
        event_id=None,
    )


@router.post(
    "/campaigns/{campaign_id}/reference-corpus/query",
    response_model=RetrieveCitedPassagesResponse,
    status_code=200,
)
def retrieve_cited_passages_endpoint(
    campaign_id: uuid.UUID,
    body: RetrieveCitedPassagesRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW_CAPABILITY))],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RetrieveCitedPassagesResponse:
    passages = retrieve_cited_passages(
        engine,
        campaign_id=campaign_id,
        query_text=body.query_text,
        requested_by_user_id=access.user_id,
        limit=body.limit,
    )
    return RetrieveCitedPassagesResponse(
        passages=[CitedPassageResponse.from_domain(p) for p in passages]
    )
