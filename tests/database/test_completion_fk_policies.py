"""Focused schema tests for the two completion foreign keys revisions 087
and 088 introduced: `security.timeline_bootstrap_grants.
consumed_by_campaign_id` and `security.campaign_creation_reservations.
created_campaign_id`.

Both columns pair with a `CHECK` constraint requiring a fixed set of
completion columns to be `NULL` or non-`NULL` *together*
(`ck_timeline_bootstrap_grants_consumed_pairing`,
`ck_campaign_creation_reservations_completion_consistent`). Both foreign
keys were originally declared `ON DELETE SET NULL` — a High-severity
schema defect: a deleted `campaign.campaigns` row would null out exactly
one half of the pair via the cascade, violating the very `CHECK`
constraint that pairing exists to enforce, the instant the cascade ran
(reproduced directly against a live database before this fix: `DELETE FROM
campaign.campaigns` failed with `psycopg.errors.CheckViolation:
ck_timeline_bootstrap_grants_consumed_pairing`, not a foreign-key error).

Both are now `ON DELETE RESTRICT` instead — see migrations
`087_timeline_bootstrap_grants` and `088_precampaign_idempotency`'s own
"Forward migration" sections for the full reasoning. No command in this
codebase ever deletes a `campaign.campaigns` row (campaigns are permanent
once created, CLAUDE.md rule 9), so `RESTRICT` costs nothing in practice —
it only turns what would otherwise be a silent, schema-corrupting
contradiction into an explicit, loud `RestrictViolation` if that
assumption is ever violated. These tests prove exactly that: attempting to
delete a campaign a consumed grant / completed reservation still
references fails cleanly with a foreign-key error naming the specific
constraint, never a `CHECK` violation, and the referencing row survives
completely untouched.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.api.idempotency import (
    CampaignCreationReservation,
    begin_campaign_creation_request,
    complete_campaign_creation_request,
)
from dnd_ai.commands.campaigns import create_campaign, grant_timeline_bootstrap
from tests.factories import make_ruleset_version_for_world, make_timeline, make_user, make_world

pytestmark = pytest.mark.database


def _make_campaign(connection: Connection, slug: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A real campaign created through `create_campaign` — the only code
    path that ever sets either completion pairing this file tests.
    Returns (campaign_id, timeline_id, creator_user_id)."""
    world_id = make_world(connection, slug=slug)
    timeline_id = make_timeline(connection, world_id, is_primary=True)
    ruleset_version_id = make_ruleset_version_for_world(connection, world_id)
    creator_user_id = make_user(connection, f"{slug} creator")
    grant_timeline_bootstrap(
        connection, timeline_id=timeline_id, granted_to_user_id=creator_user_id
    )
    result = create_campaign(
        connection,
        timeline_id=timeline_id,
        ruleset_version_id=ruleset_version_id,
        name=f"{slug} campaign",
        creator_user_id=creator_user_id,
    )
    return result.campaign_id, timeline_id, creator_user_id


def test_deleting_a_campaign_a_consumed_bootstrap_grant_still_references_is_rejected(
    db_connection: Connection,
) -> None:
    campaign_id, timeline_id, creator_user_id = _make_campaign(
        db_connection, f"fk-grant-{uuid.uuid4().hex[:8]}"
    )
    before = db_connection.execute(
        text("""
            SELECT consumed_at, consumed_by_campaign_id
            FROM security.timeline_bootstrap_grants
            WHERE timeline_id = :t AND granted_to_user_id = :u
        """),
        {"t": timeline_id, "u": creator_user_id},
    ).one()
    assert before.consumed_at is not None
    assert before.consumed_by_campaign_id == campaign_id

    with pytest.raises(IntegrityError) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"), {"c": campaign_id}
        )
    assert "timeline_bootstrap_grants_consumed_by_campaign_id_fkey" in str(exc.value)

    after = db_connection.execute(
        text("""
            SELECT consumed_at, consumed_by_campaign_id
            FROM security.timeline_bootstrap_grants
            WHERE timeline_id = :t AND granted_to_user_id = :u
        """),
        {"t": timeline_id, "u": creator_user_id},
    ).one()
    assert after.consumed_at == before.consumed_at
    assert after.consumed_by_campaign_id == campaign_id

    campaign_still_exists = db_connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c)"),
        {"c": campaign_id},
    ).scalar_one()
    assert campaign_still_exists is True


def test_deleting_a_campaign_a_completed_reservation_still_references_is_rejected(
    db_connection: Connection,
) -> None:
    """Uses a *second* campaign on the same timeline, reached through the
    ordinary `access.manage` timeline-*reuse* branch (the creator already
    owns the first campaign there) rather than the bootstrap-grant path —
    that branch never touches `security.timeline_bootstrap_grants` at all
    (`dnd_ai.commands.campaigns._authorize_timeline_reuse`'s own
    docstring), so no grant row references this second campaign. Isolates
    the `campaign_creation_reservations` foreign key under test from the
    sibling `timeline_bootstrap_grants` one on the same campaign row —
    without this, PostgreSQL reports whichever of the two `RESTRICT`
    violations it happens to check first, masking this one."""
    slug = f"fk-reservation-{uuid.uuid4().hex[:8]}"
    world_id = make_world(db_connection, slug=slug)
    timeline_id = make_timeline(db_connection, world_id, is_primary=True)
    ruleset_version_id = make_ruleset_version_for_world(db_connection, world_id)
    creator_user_id = make_user(db_connection, f"{slug} creator")
    grant_timeline_bootstrap(
        db_connection, timeline_id=timeline_id, granted_to_user_id=creator_user_id
    )
    create_campaign(
        db_connection,
        timeline_id=timeline_id,
        ruleset_version_id=ruleset_version_id,
        name=f"{slug} first",
        creator_user_id=creator_user_id,
    )

    key = f"fk-policy-{uuid.uuid4().hex[:8]}"
    payload = {"timeline_id": str(timeline_id), "name": "reservation payload"}
    outcome = begin_campaign_creation_request(
        db_connection,
        actor_user_id=creator_user_id,
        idempotency_key=key,
        payload=payload,
        correlation_id=None,
    )
    assert isinstance(outcome, CampaignCreationReservation)
    second = create_campaign(
        db_connection,
        timeline_id=timeline_id,
        ruleset_version_id=ruleset_version_id,
        name=f"{slug} second",
        creator_user_id=creator_user_id,
    )
    campaign_id = second.campaign_id
    complete_campaign_creation_request(
        db_connection,
        campaign_creation_reservation_id=outcome.campaign_creation_reservation_id,
        response_status_code=201,
        response_body={"campaign_id": str(campaign_id)},
        campaign_id=campaign_id,
    )

    before = db_connection.execute(
        text("""
            SELECT response_status_code, response_body, completed_at, created_campaign_id
            FROM security.campaign_creation_reservations
            WHERE actor_user_id = :u AND idempotency_key = :k
        """),
        {"u": creator_user_id, "k": key},
    ).one()
    assert before.completed_at is not None
    assert before.created_campaign_id == campaign_id

    with pytest.raises(IntegrityError) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"), {"c": campaign_id}
        )
    assert "campaign_creation_reservations_created_campaign_id_fkey" in str(exc.value)

    after = db_connection.execute(
        text("""
            SELECT response_status_code, response_body, completed_at, created_campaign_id
            FROM security.campaign_creation_reservations
            WHERE actor_user_id = :u AND idempotency_key = :k
        """),
        {"u": creator_user_id, "k": key},
    ).one()
    assert after.completed_at == before.completed_at
    assert after.created_campaign_id == campaign_id
    assert after.response_status_code == before.response_status_code

    campaign_still_exists = db_connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c)"),
        {"c": campaign_id},
    ).scalar_one()
    assert campaign_still_exists is True
