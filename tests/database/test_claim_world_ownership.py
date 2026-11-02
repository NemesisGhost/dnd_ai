"""scripts/claim_world_ownership.py (Phase 14, ADR 0014)."""

import uuid

import claim_world_ownership
import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.worlds import update_world
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from dnd_ai.domain.authoring import WorldAlreadyClaimedError
from tests.builders import make_authored_world
from tests.factories import (
    make_external_identity,
    make_system_role_assignment,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


def _local_user(connection: Connection, login: str) -> uuid.UUID:
    user = make_user(connection, login)
    make_external_identity(connection, user, issuer=LOCAL_AUTH_ISSUER, subject=login)
    return user


def test_list_unowned_includes_only_worlds_with_no_membership_rows(
    db_connection: Connection,
) -> None:
    legacy = make_world(db_connection, "claim-list-legacy")
    owned = make_authored_world(db_connection, owner_user_id=make_user(db_connection)).world_id
    listed = {w[0] for w in claim_world_ownership.list_unowned_worlds(db_connection)}
    assert legacy in listed
    assert owned not in listed


def test_claim_makes_the_user_the_owner_who_can_then_author_it(db_connection: Connection) -> None:
    user = _local_user(db_connection, "claimer")
    # Managing a world (here: renaming it) needs the system `gm` role as well (ADR 0020, D11).
    make_system_role_assignment(db_connection, user, "gm")
    legacy = make_world(db_connection, "claim-legacy-world", name="Legacy")
    result = claim_world_ownership.claim_world(db_connection, world_id=legacy, user_id=user)
    assert result.user_id == user
    version = db_connection.execute(
        text("SELECT row_version FROM core.worlds WHERE world_id = :w"), {"w": legacy}
    ).scalar()
    update_world(
        db_connection,
        world_id=legacy,
        actor_user_id=user,
        expected_row_version=version,
        name="Legacy Renamed",
        description=None,
    )


def test_claim_is_audited_with_the_script_as_actor_and_no_user(db_connection: Connection) -> None:
    user = _local_user(db_connection, "claimer2")
    legacy = make_world(db_connection, "claim-audited")
    claim_world_ownership.claim_world(db_connection, world_id=legacy, user_id=user)
    row = db_connection.execute(
        text(
            "SELECT actor_user_id, actor_service, command_name, world_id FROM audit.change_log "
            "WHERE command_name = 'claim_unowned_world' AND world_id = :w"
        ),
        {"w": legacy},
    ).one()
    assert row.actor_user_id is None
    assert row.actor_service == "claim_world_ownership_script"


def test_claim_refuses_an_owned_world(db_connection: Connection) -> None:
    owned = make_authored_world(db_connection, owner_user_id=make_user(db_connection)).world_id
    with pytest.raises(WorldAlreadyClaimedError):
        claim_world_ownership.claim_world(
            db_connection, world_id=owned, user_id=_local_user(db_connection, "thief")
        )


def test_resolve_local_user_requires_an_active_local_identity(db_connection: Connection) -> None:
    active = _local_user(db_connection, "resolvable")
    assert (
        claim_world_ownership.resolve_local_user(db_connection, login_name="Resolvable") == active
    )
    assert claim_world_ownership.resolve_local_user(db_connection, login_name="nobody") is None
