"""Rules/reference-corpus commands (docs/PLAN.md §18.3, migration
094_reference_corpus): registration, ingestion, campaign grants, and
audience/edition-filtered cited retrieval.

Uses the connection-taking `_impl` forms directly on the rollback-wrapped
`db_connection` fixture (matching every other database test in this
package) rather than the engine-based public wrappers, which open their
own transaction and would not see this fixture's uncommitted setup rows.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.reference_corpus import (
    DuplicateFileHashError,
    PassageInput,
    SourceDocumentNotIndexableError,
    _ingest_reference_passages_impl,
    _register_source_document_impl,
    _retrieve_cited_passages_impl,
)
from tests.factories import (
    make_campaign,
    make_reference_passage,
    make_reference_source_campaign_grant,
    make_ruleset_version_for_world,
    make_source_document,
    make_timeline,
    make_world,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, ruleset_version_id=self.ruleset_version_id
        )


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, f"corpus-{uuid.uuid4().hex[:8]}")


def _register(connection: Connection, f: Fixture, **overrides: object) -> uuid.UUID:
    kwargs: dict[str, object] = {
        "source_type_code": "rulebook",
        "ruleset_version_id": f.ruleset_version_id,
        "title": "Test Sourcebook",
        "classification": "srd",
        "file_hash": uuid.uuid4().hex,
        "source_version_label": "v1",
        "visibility": "general",
    }
    kwargs.update(overrides)
    return _register_source_document_impl(connection, **kwargs)  # type: ignore[arg-type]


def test_register_source_document_returns_a_new_id(db_connection: Connection, f: Fixture) -> None:
    source_id = _register(db_connection, f)
    assert isinstance(source_id, uuid.UUID)


def test_duplicate_file_hash_is_rejected(db_connection: Connection, f: Fixture) -> None:
    file_hash = uuid.uuid4().hex
    _register(db_connection, f, file_hash=file_hash)
    with pytest.raises(DuplicateFileHashError):
        _register(db_connection, f, file_hash=file_hash)


def test_ingest_requires_allow_indexing(db_connection: Connection, f: Fixture) -> None:
    source_id = _register(db_connection, f, allow_indexing=False)
    with pytest.raises(SourceDocumentNotIndexableError):
        _ingest_reference_passages_impl(
            db_connection,
            source_document_id=source_id,
            passages=(PassageInput(passage_order=0, content="Some content."),),
        )


def test_ingest_and_retrieve_returns_citation_location(
    db_connection: Connection, f: Fixture
) -> None:
    source_id = _register(db_connection, f)
    _ingest_reference_passages_impl(
        db_connection,
        source_document_id=source_id,
        passages=(
            PassageInput(
                passage_order=0,
                content="The fireball spell deals fire damage in a 20-foot radius.",
                chapter="Chapter 10: Spells",
                section="Fireball",
                page_label="241",
            ),
        ),
    )

    results = _retrieve_cited_passages_impl(
        db_connection,
        campaign_id=f.campaign_id,
        query_text="fireball damage",
        requested_by_user_id=None,
        context_request_id=None,
        limit=5,
    )

    assert len(results) == 1
    assert results[0].source_document_id == source_id
    assert results[0].chapter == "Chapter 10: Spells"
    assert results[0].section == "Fireball"
    assert results[0].page_label == "241"


def test_retrieval_excludes_a_conflicting_edition(db_connection: Connection, f: Fixture) -> None:
    other_ruleset_version_id = make_ruleset_version_for_world(
        db_connection, f.world_id, code=f"other_{uuid.uuid4().hex[:8]}"
    )
    other_source_id = make_source_document(
        db_connection, other_ruleset_version_id, visibility="general"
    )
    make_reference_passage(
        db_connection, other_source_id, content="Fireball rules from another edition."
    )

    results = _retrieve_cited_passages_impl(
        db_connection,
        campaign_id=f.campaign_id,
        query_text="fireball",
        requested_by_user_id=None,
        context_request_id=None,
        limit=5,
    )
    assert results == ()


def test_retrieval_excludes_an_unauthorized_campaign_restricted_source(
    db_connection: Connection, f: Fixture
) -> None:
    source_id = make_source_document(
        db_connection, f.ruleset_version_id, visibility="campaign_restricted"
    )
    make_reference_passage(db_connection, source_id, content="Secret house content about goblins.")

    results = _retrieve_cited_passages_impl(
        db_connection,
        campaign_id=f.campaign_id,
        query_text="goblins",
        requested_by_user_id=None,
        context_request_id=None,
        limit=5,
    )
    assert results == ()


def test_granting_a_campaign_restricted_source_makes_it_retrievable(
    db_connection: Connection, f: Fixture
) -> None:
    source_id = make_source_document(
        db_connection, f.ruleset_version_id, visibility="campaign_restricted"
    )
    make_reference_passage(db_connection, source_id, content="Secret house content about goblins.")
    make_reference_source_campaign_grant(db_connection, source_id, f.campaign_id)

    results = _retrieve_cited_passages_impl(
        db_connection,
        campaign_id=f.campaign_id,
        query_text="goblins",
        requested_by_user_id=None,
        context_request_id=None,
        limit=5,
    )
    assert len(results) == 1
    assert results[0].source_document_id == source_id


def test_a_house_rule_grant_outranks_a_general_source_of_the_same_edition(
    db_connection: Connection, f: Fixture
) -> None:
    general_source_id = _register(db_connection, f, visibility="general")
    _ingest_reference_passages_impl(
        db_connection,
        source_document_id=general_source_id,
        passages=(PassageInput(passage_order=0, content="Goblins have 7 hit points normally."),),
    )

    house_rule_source_id = make_source_document(
        db_connection, f.ruleset_version_id, visibility="campaign_restricted"
    )
    make_reference_passage(
        db_connection, house_rule_source_id, content="House rule: goblins have 12 hit points here."
    )
    make_reference_source_campaign_grant(
        db_connection, house_rule_source_id, f.campaign_id, is_house_rule=True
    )

    results = _retrieve_cited_passages_impl(
        db_connection,
        campaign_id=f.campaign_id,
        query_text="goblins hit points",
        requested_by_user_id=None,
        context_request_id=None,
        limit=5,
    )
    assert len(results) == 2
    assert results[0].source_document_id == house_rule_source_id
    assert results[0].is_house_rule is True


def test_a_removed_source_is_excluded_from_retrieval(db_connection: Connection, f: Fixture) -> None:
    source_id = _register(db_connection, f)
    _ingest_reference_passages_impl(
        db_connection,
        source_document_id=source_id,
        passages=(PassageInput(passage_order=0, content="Unique wizardry content."),),
    )
    db_connection.execute(
        text(
            "UPDATE core.source_documents SET status = 'removed', removed_at = now() WHERE source_document_id = :id"
        ),
        {"id": source_id},
    )

    results = _retrieve_cited_passages_impl(
        db_connection,
        campaign_id=f.campaign_id,
        query_text="wizardry",
        requested_by_user_id=None,
        context_request_id=None,
        limit=5,
    )
    assert results == ()


def test_retrieval_is_recorded_for_audit(db_connection: Connection, f: Fixture) -> None:
    source_id = _register(db_connection, f)
    _ingest_reference_passages_impl(
        db_connection,
        source_document_id=source_id,
        passages=(PassageInput(passage_order=0, content="Auditable arcane content."),),
    )

    _retrieve_cited_passages_impl(
        db_connection,
        campaign_id=f.campaign_id,
        query_text="arcane",
        requested_by_user_id=None,
        context_request_id=None,
        limit=5,
    )

    retrieval_count = db_connection.execute(
        text("SELECT count(*) FROM ai.reference_retrievals WHERE campaign_id = :c"),
        {"c": f.campaign_id},
    ).scalar()
    assert retrieval_count == 1

    result_count = db_connection.execute(
        text("""
            SELECT count(*) FROM ai.reference_retrieval_results rr
            JOIN ai.reference_retrievals r ON r.reference_retrieval_id = rr.reference_retrieval_id
            WHERE r.campaign_id = :c
        """),
        {"c": f.campaign_id},
    ).scalar()
    assert result_count == 1


def test_a_house_rule_grant_must_share_the_source_ruleset_version(
    db_connection: Connection, f: Fixture
) -> None:
    other_ruleset_version_id = make_ruleset_version_for_world(
        db_connection, f.world_id, code=f"mismatch_{uuid.uuid4().hex[:8]}"
    )
    other_campaign_id = make_campaign(
        db_connection,
        make_timeline(db_connection, f.world_id),
        ruleset_version_id=other_ruleset_version_id,
    )
    source_id = make_source_document(
        db_connection, f.ruleset_version_id, visibility="campaign_restricted"
    )

    with pytest.raises(IntegrityError):
        make_reference_source_campaign_grant(db_connection, source_id, other_campaign_id)
