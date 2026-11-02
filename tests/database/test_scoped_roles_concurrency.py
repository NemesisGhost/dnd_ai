"""Real-PostgreSQL race for the world gate on a relationship-definition writer
(docs/adr/0020-scoped-system-world-and-campaign-roles.md, checkpoint CP-4b).

`lock_authoring_scope` resolves the caller's world capability under the world `FOR SHARE`
lock, and `end_world_role` takes the world `FOR UPDATE`, so a role that ends while another
transaction is mid-command is honoured: the writer waits for the ending transaction and then
re-resolves, finding no authority. Nothing is mocked; committed fixtures are purged after.

The existing sequential check (the *next* command after a role ends is refused) cannot show this:
only a writer that is already waiting on the lock distinguishes a resolved-under-lock gate from
one resolved before it.
"""

# ruff: noqa: F811
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.world_access import end_world_role
from dnd_ai.commands.world_relationships import update_relationship
from dnd_ai.domain.authoring import WorldAuthorityRequiredError
from tests.database.test_content_authoring_concurrency import race
from tests.database.test_relationship_authoring_concurrency import Fixture as RelationshipFixture
from tests.database.test_relationship_authoring_concurrency import (
    fx as relationship_fx,  # noqa: F401
)
from tests.factories import (
    lookup_id,
    make_campaign_membership,
    make_membership_role,
    make_user,
)

pytestmark = pytest.mark.database

WORLD_SHARE_LOCK = "query LIKE '%FROM core.worlds%FOR SHARE%'"


@dataclass
class Editor:
    user_id: uuid.UUID
    world_membership_id: uuid.UUID


@pytest.fixture
def editor(postgres_engine: Engine, relationship_fx: RelationshipFixture) -> Editor:
    """A campaign GM who holds the world Editor role on the relationship fixture's world."""
    fx = relationship_fx
    with postgres_engine.begin() as setup:
        user = make_user(setup, "Race Editor")
        membership = make_campaign_membership(setup, fx.campaign_id, user)
        gm_role = lookup_id(setup, "security", "roles", "role_id", "gm")
        make_membership_role(setup, membership, gm_role)
        world_id = setup.execute(
            text("""
                SELECT t.world_id FROM campaign.campaigns c
                JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                WHERE c.campaign_id = :c
            """),
            {"c": fx.campaign_id},
        ).scalar_one()
        world_membership = setup.execute(
            text("""
                INSERT INTO security.world_memberships
                    (world_id, user_id, world_role_id, membership_status_id, granted_by_user_id)
                VALUES (
                    :w, :u,
                    (SELECT world_role_id FROM security.world_roles WHERE code = 'world_editor'),
                    (SELECT membership_status_id FROM security.membership_statuses
                     WHERE code = 'active'),
                    :owner
                )
                RETURNING world_membership_id
            """),
            {"w": world_id, "u": user, "owner": fx.owner},
        ).scalar_one()
    return Editor(user, world_membership)


def _edit(fx: RelationshipFixture, editor: Editor, connection, description: str):  # type: ignore[no-untyped-def]
    return update_relationship(
        connection,
        campaign_id=fx.campaign_id,
        actor_user_id=editor.user_id,
        relationship_id=fx.relationship_id,
        expected_row_version=fx.version,
        description=description,
        started_world_time_id=None,
    )


def test_a_world_role_ended_mid_command_is_honoured_by_a_relationship_writer(
    postgres_engine: Engine, relationship_fx: RelationshipFixture, editor: Editor
) -> None:
    fx = relationship_fx
    world_id = fx.scalar(
        "SELECT t.world_id FROM campaign.campaigns c JOIN campaign.timelines t "
        "ON t.timeline_id = c.timeline_id WHERE c.campaign_id = :c",
        c=fx.campaign_id,
    )
    # The Editor can write while the role stands (also proves the fixture is a valid writer).
    with postgres_engine.begin() as connection:
        before = _edit(fx, editor, connection, "Edited while the role stood")
    assert before.changed

    out = race(
        postgres_engine,
        lambda holder: end_world_role(
            holder,
            actor_user_id=fx.owner,
            world_id=world_id,
            world_membership_id=editor.world_membership_id,
        ),
        lambda racer: update_relationship(
            racer,
            campaign_id=fx.campaign_id,
            actor_user_id=editor.user_id,
            relationship_id=fx.relationship_id,
            expected_row_version=before.row_version,
            description="Edited after the role ended",
            started_world_time_id=None,
        ),
        WORLD_SHARE_LOCK,
    )
    assert isinstance(out.get("error"), WorldAuthorityRequiredError), out
    assert (
        fx.scalar(
            "SELECT description FROM world.relationships WHERE relationship_id = :r",
            r=fx.relationship_id,
        )
        == "Edited while the role stood"
    )
