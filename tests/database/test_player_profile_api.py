# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The GM reads of a character's campaign player profile over HTTP (P03-A A5a, design sections 8,
11.2, 11.3 and 11.4; decisions D13, D15 and D17).

A5 is infrastructure: there is no production writer, so every profile here is created by the one
raw fixture writer (`tests/player_profile_support.py`) and read through the real routes. The reader
matrix runs each design section 8.3 row through HTTP, with roles created through the application and
denies created through the grant route. Responses are checked for their exact key sets and for any
text that must not appear; refusals are the generic 404 body, byte-identical to a missing resource.
"""

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands.memberships import end_campaign_membership, revoke_membership_role
from dnd_ai.domain.player_profiles import PLAYER_PROFILE_FIELDS
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_grant_denies import (
    deny_via_route,
    revoke_via_route,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_character_relationship,
    make_membership_role,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_user,
    make_world,
)
from tests.player_profile_support import edit_player_profile, markers, seed_player_profile

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

PROFILE_KEYS = {
    "character_player_profile_id",
    "row_version",
    "updated_at",
    "edited_at",
    "edited_by",
    "fields",
}
TOP_KEYS = {"character_id", "character_active", "profile", "fields_catalog"}
VERSION_KEYS = {"character_id", "profile_row_version", "edited_at", "edited_by", "fields"}


@dataclass
class Pp:
    character: uuid.UUID  # K: has a profile in campaign A
    bare: uuid.UUID  # a character with no profile
    a_markers: dict[str, str]
    head: uuid.UUID
    observer_user: uuid.UUID
    observer: uuid.UUID
    canon_editor_user: uuid.UUID
    canon_editor: uuid.UUID
    controller_user: uuid.UUID
    controller: uuid.UUID
    revealed_user: uuid.UUID  # the player, once K is revealed to them


@pytest.fixture
def pp(postgres_engine: Engine, g: Gate, m: Members) -> Pp:
    with postgres_engine.begin() as connection:
        character = make_character(connection, g.world_id, name="Profile Subject")
        bare = make_character(connection, g.world_id, name="Profile Bare")
        observer_user = make_user(connection, "Profile Observer")
        observer = make_campaign_membership(connection, g.campaign_id, observer_user)
        observer_role = connection.execute(
            text(
                "SELECT role_id FROM security.roles WHERE code = 'observer' AND campaign_id IS NULL"
            )
        ).scalar_one()
        make_membership_role(connection, observer, observer_role)
        # A custom role carrying canon.edit (and campaign.view).
        editor_role = make_role(
            connection, campaign_id=g.campaign_id, code=f"custom_editor_{uuid.uuid4().hex[:8]}"
        )
        for capability in ("canon.edit", "campaign.view"):
            make_role_capability(
                connection,
                editor_role,
                lookup_id(connection, "security", "capabilities", "capability_id", capability),
            )
        canon_editor_user = make_user(connection, "Profile Custom Editor")
        canon_editor = make_campaign_membership(connection, g.campaign_id, canon_editor_user)
        make_membership_role(connection, canon_editor, editor_role)
        # A live legacy relationship holder of K: relationship capabilities never include canon.edit.
        controller_user = make_user(connection, "Profile Controller")
        controller = make_campaign_membership(connection, g.campaign_id, controller_user)
        make_membership_role(connection, controller, g.player_role_id)
        make_membership_character_relationship(
            connection,
            controller,
            character,
            lookup_id(
                connection,
                "security",
                "character_relationship_types",
                "character_relationship_type_id",
                "primary_controller",
            ),
            timeline_id=g.timeline_id,
        )
    a_markers = markers("A")
    head = seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields=a_markers,
    )
    return Pp(
        character=character,
        bare=bare,
        a_markers=a_markers,
        head=head,
        observer_user=observer_user,
        observer=observer,
        canon_editor_user=canon_editor_user,
        canon_editor=canon_editor,
        controller_user=controller_user,
        controller=controller,
        revealed_user=g.player_user_id,
    )


# --- helpers ----------------------------------------------------------------------------------


def url(campaign: uuid.UUID, character: uuid.UUID, suffix: str = "") -> str:
    return f"/campaigns/{campaign}/characters/{character}/player-profile{suffix}"


def get(factory: Factory, user: uuid.UUID, path: str, engine_factory: Factory | None = None) -> Any:
    with (engine_factory or factory)(user) as client:
        response = client.get(path)
    if response.status_code >= 400:
        # The per-request correlation id is the only thing two otherwise identical refusals differ
        # by; drop it so "the same body" can be compared byte for byte.
        data = response.json()
        if isinstance(data.get("error"), dict):
            data["error"].pop("correlation_id", None)
        response._content = json.dumps(data, sort_keys=True).encode()
    return response


def generic_404(factory: Factory, user: uuid.UUID, g: Gate, bare: uuid.UUID) -> Any:
    """The refusal a non-reader gets for a character that has no profile at all."""
    response = get(factory, user, url(g.campaign_id, bare))
    assert response.status_code == 404, response.text
    return response.json()


def assert_all_markers_absent(blob: str, values: dict[str, str]) -> None:
    for code, marker in values.items():
        assert marker not in blob, code


# --- the response shape -------------------------------------------------------------------------


def test_the_current_profile_has_exactly_the_documented_keys_and_names_only_the_editor(
    client_factory: Factory, g: Gate, pp: Pp
) -> None:
    response = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.character))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == TOP_KEYS
    assert body["character_id"] == str(pp.character) and body["character_active"] is True
    assert set(body["profile"]) == PROFILE_KEYS
    assert body["profile"]["row_version"] == 1
    assert body["profile"]["character_player_profile_id"] == str(pp.head)
    assert list(body["profile"]["fields"]) == list(PLAYER_PROFILE_FIELDS)
    assert body["profile"]["fields"] == pp.a_markers
    assert body["profile"]["edited_by"] == "Gate Owner One"
    assert body["fields_catalog"] == [
        {
            "code": code,
            "label": "Notes for the GM and controllers" if code == "profile_notes" else label,
            "copy_eligible": code not in ("boundaries", "profile_notes"),
        }
        for code, label in zip(
            PLAYER_PROFILE_FIELDS,
            (
                "Portrayal guidance",
                "Personality",
                "Ideals",
                "Bonds",
                "Flaws",
                "Goals",
                "Fears",
                "Loyalties",
                "Boundaries",
                "Speech patterns",
                "Notes for the GM and controllers",
            ),
            strict=True,
        )
    ]
    # No membership id, user id, e-mail or account name beyond the display name.
    for hidden in (g.o1, g.o1_user_id, g.campaign_id):
        assert str(hidden) not in json.dumps({**body, "character_id": None})


def test_an_empty_field_is_null_and_a_character_without_a_profile_reads_null(
    client_factory: Factory, postgres_engine: Engine, g: Gate, pp: Pp
) -> None:
    edit_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=pp.character,
        editor_membership_id=g.o1,
        fields={"personality": "Only this"},
    )
    body = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.character)).json()
    assert body["profile"]["row_version"] == 2
    assert body["profile"]["fields"] == {
        code: ("Only this" if code == "personality" else None) for code in PLAYER_PROFILE_FIELDS
    }
    bare = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.bare))
    assert bare.status_code == 200
    assert set(bare.json()) == TOP_KEYS and bare.json()["profile"] is None


def test_each_version_is_immutable_history_and_a_bad_segment_names_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, pp: Pp
) -> None:
    second = markers("A2")
    assert (
        edit_player_profile(
            postgres_engine,
            campaign_id=g.campaign_id,
            character_id=pp.character,
            editor_membership_id=m.gm,
            fields=second,
        )
        == 2
    )
    first = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.character, "/versions/1"))
    assert first.status_code == 200 and set(first.json()) == VERSION_KEYS
    assert first.json()["fields"] == pp.a_markers and first.json()["profile_row_version"] == 1
    assert first.json()["edited_by"] == "Gate Owner One"
    latest = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.character, "/versions/2"))
    assert latest.json()["fields"] == second and latest.json()["edited_by"] == "Reveal GM"
    current = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.character)).json()
    assert current["profile"]["fields"] == second
    refused = {
        "/versions/3": 404,  # missing
        "/versions/0": 404,
        "/versions/-1": 404,
        "/versions/abc": 404,
        "/versions/1.5": 404,
        "/versions/%C2%B2": 404,  # a superscript digit is not a version number
        "/versions/99999999999999999999999": 404,
        f"/versions/{uuid.uuid4()}": 404,
    }
    bodies = set()
    for suffix, status in refused.items():
        response = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.character, suffix))
        assert response.status_code == status, suffix
        bodies.add(json.dumps(response.json(), sort_keys=True))
    assert len(bodies) == 1  # one generic body for every miss


# --- the reader matrix (design section 8.3) -------------------------------------------------------


def test_the_gm_branch_admits_the_owner_gm_assistant_and_a_custom_canon_edit_role(
    client_factory: Factory, g: Gate, m: Members, pp: Pp
) -> None:
    for name, user in (
        ("owner", g.o1_user_id),
        ("second owner", g.o2_user_id),
        ("gm", m.gm_user_id),  # also a delegated reveal GM: the delegation adds nothing
        ("assistant gm", m.ast_user_id),
        ("custom canon.edit role", pp.canon_editor_user),
    ):
        for suffix in ("", "/versions/1"):
            response = get(client_factory, user, url(g.campaign_id, pp.character, suffix))
            assert response.status_code == 200, (name, suffix, response.text)
            assert response.json()["profile" if not suffix else "fields"] is not None


def test_every_non_reader_gets_the_generic_404_that_a_profileless_character_gives(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, pp: Pp
) -> None:
    with postgres_engine.begin() as connection:
        outsider = make_user(connection, "Profile Outsider")
    non_readers = {
        "access.manage-only custom role": g.manager_user_id,
        "player": g.player_user_id,
        "observer": pp.observer_user,
        "legacy relationship holder": pp.controller_user,
        "no membership": outsider,
    }
    for name, user in non_readers.items():
        reference = generic_404(client_factory, user, g, pp.bare)
        for suffix in ("", "/versions/1"):
            response = get(client_factory, user, url(g.campaign_id, pp.character, suffix))
            assert response.status_code == 404, (name, suffix, response.text)
            assert response.json() == reference, (name, suffix)
            assert_all_markers_absent(response.text, pp.a_markers)


def test_a_member_without_campaign_view_is_refused_by_the_campaign_gate_before_the_rule(
    client_factory: Factory, g: Gate, m: Members, pp: Pp
) -> None:
    """A custom role that merely borrows the code `gm` carries no capability, so the route's
    `campaign.view` dependency refuses it (the existing campaign gate), and nothing is read."""
    for suffix in ("", "/versions/1"):
        response = get(
            client_factory, m.lookalike_user_id, url(g.campaign_id, pp.character, suffix)
        )
        assert response.status_code == 403
        assert_all_markers_absent(response.text, pp.a_markers)


def test_a_holder_of_a_revelation_of_the_character_reads_no_profile(
    client_factory: Factory, postgres_engine: Engine, g: Gate, pp: Pp
) -> None:
    base = f"/campaigns/{g.campaign_id}/characters/{pp.character}"
    with client_factory(g.o1_user_id) as client:
        saved = client.post(
            base + "/public-profile/draft",
            json={"expected_row_version": None, "public_appearance": "Tall"},
        )
        assert saved.status_code == 201, saved.text
        released = client.post(
            base + "/public-profile/releases", json={"expected_draft_row_version": 1}
        )
        assert released.status_code == 201, released.text
        revealed = client.post(
            base + "/revelations",
            json={
                "audience_kind": "member",
                "target_campaign_membership_id": str(g.player),
                "reason": "The table meets them",
            },
        )
        assert revealed.status_code == 201, revealed.text
    reference = generic_404(client_factory, g.player_user_id, g, pp.bare)
    for suffix in ("", "/versions/1"):
        response = get(client_factory, g.player_user_id, url(g.campaign_id, pp.character, suffix))
        assert response.status_code == 404 and response.json() == reference
    # Holding reveal authority is no read either: a delegated GM without canon.edit would read
    # nothing, and the revelation holder shows the audience tier confers nothing here.
    assert_all_markers_absent(json.dumps(reference), pp.a_markers)


def test_a_whole_character_deny_and_a_canon_edit_deny_refuse_the_read_for_any_source(
    client_factory: Factory, g: Gate, m: Members, pp: Pp
) -> None:
    reference = generic_404(client_factory, g.player_user_id, g, pp.bare)
    path = url(g.campaign_id, pp.character)

    whole = deny_via_route(client_factory, g, "campaign.view", pp.character, member=m.gm)
    refused = get(client_factory, m.gm_user_id, path)
    assert refused.status_code == 404 and refused.json() == reference
    assert get(client_factory, g.o1_user_id, path).status_code == 200  # others are unaffected
    revoke_via_route(client_factory, g, whole)
    assert get(client_factory, m.gm_user_id, path).status_code == 200

    # A canon.edit deny refuses this GM path, including an owner who keeps reveal authority.
    for user, membership in ((m.gm_user_id, m.gm), (g.o1_user_id, g.o1), (m.ast_user_id, m.ast)):
        grant = deny_via_route(client_factory, g, "canon.edit", pp.character, member=membership)
        for suffix in ("", "/versions/1"):
            response = get(client_factory, user, url(g.campaign_id, pp.character, suffix))
            assert response.status_code == 404 and response.json() == reference, (user, suffix)
            assert_all_markers_absent(response.text, pp.a_markers)
        revoke_via_route(client_factory, g, grant)
        assert get(client_factory, user, path).status_code == 200


def test_a_denied_character_does_not_deny_another_and_a_raw_allow_grant_confers_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, pp: Pp
) -> None:
    grant = deny_via_route(client_factory, g, "canon.edit", pp.bare, member=m.gm)
    assert get(client_factory, m.gm_user_id, url(g.campaign_id, pp.character)).status_code == 200
    revoke_via_route(client_factory, g, grant)
    # The application cannot create an allow of canon.edit on a character, so write the raw row and
    # show it opens nothing for a player (D8: a resource grant is not an authoring path).
    with postgres_engine.begin() as connection:
        make_resource_grant(
            connection,
            g.campaign_id,
            lookup_id(connection, "security", "capabilities", "capability_id", "canon.edit"),
            timeline_id=g.timeline_id,
            grantee_campaign_membership_id=g.player,
            effect="allow",
            entity_id=pp.character,
        )
    for suffix in ("", "/versions/1"):
        response = get(client_factory, g.player_user_id, url(g.campaign_id, pp.character, suffix))
        assert response.status_code == 404
        assert_all_markers_absent(response.text, pp.a_markers)


def test_a_revoked_role_and_an_ended_membership_lose_the_read(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, pp: Pp
) -> None:
    path = url(g.campaign_id, pp.character)
    assert get(client_factory, m.ast_user_id, path).status_code == 200
    with postgres_engine.begin() as connection:
        role_id = connection.execute(
            text(
                "SELECT membership_role_id FROM security.membership_roles "
                "WHERE campaign_membership_id = :m AND revoked_at IS NULL"
            ),
            {"m": m.ast},
        ).scalar_one()
        revoke_membership_role(connection, membership_role_id=role_id, campaign_id=g.campaign_id)
    revoked = get(client_factory, m.ast_user_id, path)
    assert revoked.status_code in (403, 404)
    assert_all_markers_absent(revoked.text, pp.a_markers)

    assert get(client_factory, pp.canon_editor_user, path).status_code == 200
    with postgres_engine.begin() as connection:
        end_campaign_membership(
            connection,
            campaign_membership_id=pp.canon_editor,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.o1,
        )
    ended = get(client_factory, pp.canon_editor_user, path)
    assert ended.status_code in (403, 404)
    assert_all_markers_absent(ended.text, pp.a_markers)
    # The editor of a version may have left: the read still names them.
    edit_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=pp.character,
        editor_membership_id=pp.canon_editor,
        fields={"personality": "Written before leaving"},
    )
    current = get(client_factory, g.o1_user_id, path).json()["profile"]
    assert current["edited_by"] == "Profile Custom Editor"


# --- invalid and boundary states ------------------------------------------------------------------


def test_characters_that_are_not_canon_characters_of_the_world_read_404(
    client_factory: Factory, postgres_engine: Engine, g: Gate, pp: Pp
) -> None:
    with postgres_engine.begin() as connection:
        foreign_world = make_world(connection, slug=f"pp-foreign-{uuid.uuid4().hex[:8]}")
        foreign = make_character(connection, foreign_world, name="Foreign Character")
        connection.execute(
            text(
                "UPDATE core.entities SET canon_status_id = "
                "(SELECT canon_status_id FROM core.canon_statuses WHERE code = 'draft') "
                "WHERE entity_id = :c"
            ),
            {"c": pp.bare},
        )
    try:
        reference = None
        for character in (uuid.uuid4(), foreign, pp.bare):
            for suffix in ("", "/versions/1"):
                response = get(client_factory, g.o1_user_id, url(g.campaign_id, character, suffix))
                assert response.status_code == 404, (character, suffix)
                reference = reference or response.json()
                assert response.json() == reference
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text("DELETE FROM core.entities WHERE world_id = :w"), {"w": foreign_world}
            )
            connection.execute(
                text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": foreign_world}
            )


def test_an_archived_character_is_still_readable_and_says_so(
    client_factory: Factory, postgres_engine: Engine, g: Gate, pp: Pp
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE entity_id = :c"
            ),
            {"c": pp.character},
        )
    response = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.character))
    assert response.status_code == 200
    assert response.json()["character_active"] is False
    assert response.json()["profile"]["fields"] == pp.a_markers


def test_an_archived_campaign_refuses_the_read_through_the_lifecycle_gate(
    client_factory: Factory, postgres_engine: Engine, g: Gate, pp: Pp
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE campaign.campaigns SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE campaign_id = :c"
            ),
            {"c": g.campaign_id},
        )
    response = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.character))
    assert response.status_code == 404
    assert_all_markers_absent(response.text, pp.a_markers)


def test_the_read_works_for_the_actual_runtime_database_role(
    postgres_engine: Engine,
    app_read_write_engine: Engine,
    client_factory: Factory,
    g: Gate,
    m: Members,
    pp: Pp,
) -> None:
    """The routes run as `app_read_write`, which holds SELECT on the profile tables and nothing
    that writes them; a GM gets the profile and a player the generic 404, exactly as when the
    request connection is the superuser."""
    from fastapi.testclient import TestClient

    from dnd_ai.api.app import create_app
    from dnd_ai.api.auth import get_authenticated_user_id
    from dnd_ai.api.deps import get_engine
    from tests.factories import oidc_principal

    def runtime(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: app_read_write_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    for suffix in ("", "/versions/1"):
        for user in (g.o1_user_id, m.gm_user_id, m.ast_user_id):
            response = get(client_factory, user, url(g.campaign_id, pp.character, suffix), runtime)
            assert response.status_code == 200, (user, suffix, response.text)
        refused = get(
            client_factory, g.player_user_id, url(g.campaign_id, pp.character, suffix), runtime
        )
        assert refused.status_code == 404
        assert_all_markers_absent(refused.text, pp.a_markers)


# --- campaign isolation (design section 11.3) -----------------------------------------------------


def test_two_campaigns_of_one_world_and_timeline_keep_their_profiles_apart(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, pp: Pp
) -> None:
    with postgres_engine.begin() as connection:
        campaign_b = make_campaign(
            connection, g.timeline_id, "Campaign B", lifecycle_status_code="active"
        )
        b_only_user = make_user(connection, "Profile B GM")
        b_only = make_campaign_membership(connection, campaign_b, b_only_user)
        make_membership_role(connection, b_only, g.owner_role_id)
        shared = make_campaign_membership(connection, campaign_b, m.gm_user_id)  # also GM in A
        make_membership_role(connection, shared, g.owner_role_id)
        player_b_user = make_user(connection, "Profile B Player")
        player_b = make_campaign_membership(connection, campaign_b, player_b_user)
        make_membership_role(connection, player_b, g.player_role_id)

    # With a profile only in A: B's GM reads null, a non-reader in B reads 404, A's data stays in A.
    b_path = url(campaign_b, pp.character)
    empty = get(client_factory, b_only_user, b_path)
    assert empty.status_code == 200 and empty.json()["profile"] is None
    assert get(client_factory, player_b_user, b_path).status_code == 404
    assert_all_markers_absent(empty.text, pp.a_markers)
    # B's GM is not a member of A, and A-only roles do not apply in B.
    assert get(client_factory, b_only_user, url(g.campaign_id, pp.character)).status_code == 404
    assert get(client_factory, g.o1_user_id, b_path).status_code == 404

    b_markers = markers("B")
    seed_player_profile(
        postgres_engine,
        campaign_id=campaign_b,
        character_id=pp.character,
        editor_membership_id=b_only,
        fields=b_markers,
    )
    b_view = get(client_factory, b_only_user, b_path).json()
    a_view = get(client_factory, g.o1_user_id, url(g.campaign_id, pp.character)).json()
    assert b_view["profile"]["fields"] == b_markers and a_view["profile"]["fields"] == pp.a_markers
    assert (
        b_view["profile"]["character_player_profile_id"]
        != a_view["profile"]["character_player_profile_id"]
    )
    assert_all_markers_absent(json.dumps(b_view), pp.a_markers)
    assert_all_markers_absent(json.dumps(a_view), b_markers)
    # A GM of both reads each campaign's own profile through that campaign's route.
    assert get(client_factory, m.gm_user_id, b_path).json()["profile"]["fields"] == b_markers
    assert (
        get(client_factory, m.gm_user_id, url(g.campaign_id, pp.character)).json()["profile"][
            "fields"
        ]
        == pp.a_markers
    )
    # A version number names the version of this campaign's profile only.
    edit_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=pp.character,
        editor_membership_id=g.o1,
        fields={"personality": "A second"},
    )
    assert (
        get(client_factory, b_only_user, url(campaign_b, pp.character, "/versions/2")).status_code
        == 404
    )
    assert (
        get(
            client_factory, g.o1_user_id, url(g.campaign_id, pp.character, "/versions/2")
        ).status_code
        == 200
    )


# --- disclosure (design section 11.4) ---------------------------------------------------------------


def _text_of_tables(engine: Engine, like: str, *, world: uuid.UUID | None = None) -> str:
    """Every row of every table whose name matches `like`, as text (receipts), or the audit log."""
    with engine.connect() as connection:
        if like == "audit":
            rows = connection.execute(
                text("SELECT row_to_json(c)::text FROM audit.change_log c WHERE world_id = :w"),
                {"w": world},
            ).scalars()
            return "\n".join(rows)
        tables = connection.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_name LIKE :like AND table_type = 'BASE TABLE'"
            ),
            {"like": like},
        ).all()
        blobs = []
        for schema, table in tables:
            blobs.extend(
                connection.execute(
                    text(f"SELECT row_to_json(t)::text FROM {schema}.{table} t")  # noqa: S608
                ).scalars()
            )
        return "\n".join(blobs)


def test_no_surface_a_non_reader_can_reach_carries_profile_text(
    client_factory: Factory,
    postgres_engine: Engine,
    caplog: pytest.LogCaptureFixture,
    g: Gate,
    m: Members,
    pp: Pp,
) -> None:
    """Sweeps the player-profile routes, the character and public-profile reads, every refusal body,
    the stored receipts, the audit history and captured DEBUG logs for the profile markers."""
    base = f"/campaigns/{g.campaign_id}/characters/{pp.character}"
    callers = {
        "player": g.player_user_id,
        "observer": pp.observer_user,
        "manager": g.manager_user_id,
        "relationship holder": pp.controller_user,
    }
    caplog.set_level(logging.DEBUG)
    # A GM with a canon.edit deny on K (who also holds reveal authority) is a non-reader too.
    deny_via_route(client_factory, g, "canon.edit", pp.character, member=m.gm)
    callers["gm with canon.edit deny"] = m.gm_user_id
    bodies: list[str] = []
    for name, user in callers.items():
        for path in (
            url(g.campaign_id, pp.character),
            url(g.campaign_id, pp.character, "/versions/1"),
            base,
            base + "/public-profile",
            base + "/revelations",
            base + "/sheet",
            f"/campaigns/{g.campaign_id}/world/characters",
        ):
            response = get(client_factory, user, path)
            bodies.append(f"{name} {path} {response.status_code} {response.text}")
    # The GM flows that touch the public profile run with the markers present in the store.
    with client_factory(g.o1_user_id) as client:
        client.post(
            base + "/public-profile/draft",
            json={"expected_row_version": None, "public_appearance": "Tall"},
            headers={"Idempotency-Key": "pp-disclosure-1"},
        )
        client.post(
            base + "/public-profile/releases",
            json={"expected_draft_row_version": 1},
            headers={"Idempotency-Key": "pp-disclosure-2"},
        )
        bodies.append(client.get(base + "/public-profile").text)
        bodies.append(client.get(f"/campaigns/{g.campaign_id}/audit-history").text)
        # The GM read itself returns the markers to a reader, and writes nothing.
        before = (
            _text_of_tables(postgres_engine, "%idempot%"),
            _text_of_tables(postgres_engine, "audit", world=g.world_id),
        )
        assert client.get(url(g.campaign_id, pp.character)).status_code == 200
        assert client.get(url(g.campaign_id, pp.character, "/versions/1")).status_code == 200
        after = (
            _text_of_tables(postgres_engine, "%idempot%"),
            _text_of_tables(postgres_engine, "audit", world=g.world_id),
        )
        assert after == before  # a profile read stores no receipt and writes no audit row
    blob = "\n".join(bodies)
    stored = _text_of_tables(postgres_engine, "%idempot%") + _text_of_tables(
        postgres_engine, "audit", world=g.world_id
    )
    logs = "\n".join(f"{r.name} {r.getMessage()}" for r in caplog.records)
    for surface, content in (("responses", blob), ("receipts and audit", stored), ("logs", logs)):
        for code, marker in pp.a_markers.items():
            assert marker not in content, (surface, code)
    # The sweep was not vacuous: the public-profile flows ran and left their own receipts.
    assert "pp-disclosure-1" in stored or '"save_character_public_profile_draft"' in stored


def test_a_failing_read_builds_no_message_from_profile_text(
    client_factory: Factory, caplog: pytest.LogCaptureFixture, g: Gate, pp: Pp
) -> None:
    caplog.set_level(logging.DEBUG)
    for suffix in ("/versions/abc", "/versions/9", "", "/versions/1"):
        response = get(client_factory, g.player_user_id, url(g.campaign_id, pp.character, suffix))
        assert response.status_code == 404
        assert_all_markers_absent(response.text, pp.a_markers)
    for record in caplog.records:
        assert_all_markers_absent(record.getMessage(), pp.a_markers)
        assert_all_markers_absent(str(record.exc_info), pp.a_markers)


# --- the version path segment (review correction) ---------------------------------------------------

BIGINT_MAX = 9_223_372_036_854_775_807


def test_an_over_long_version_segment_is_the_generic_404_for_every_caller_and_writes_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, pp: Pp
) -> None:
    """A 4,301-digit segment is past Python's integer-conversion limit; converting it raised and the
    error escaped as `400 validation_failed`. It names no version, so it is the same profile-level
    404 as any other miss, whoever asks, and the request changes and records nothing."""
    with postgres_engine.begin() as connection:
        outsider = make_user(connection, "Long Segment Outsider")
    long_segment = "1" * 4301
    before = (
        _text_of_tables(postgres_engine, "%idempot%"),
        _text_of_tables(postgres_engine, "audit", world=g.world_id),
        _text_of_tables(postgres_engine, "character_player_profile%"),
    )
    reference = {}
    for name, user in (
        ("owner", g.o1_user_id),
        ("gm", m.gm_user_id),
        ("player", g.player_user_id),
        ("observer", pp.observer_user),
    ):
        reference[name] = get(
            client_factory, user, url(g.campaign_id, pp.character, "/versions/abc")
        )
        response = get(
            client_factory, user, url(g.campaign_id, pp.character, f"/versions/{long_segment}")
        )
        assert response.status_code == 404, (name, response.status_code, response.text[:200])
        assert response.json()["error"]["code"] == "not_found", name
        assert response.json() == reference[name].json(), name  # the one generic body
        assert long_segment not in response.text
        assert_all_markers_absent(response.text, pp.a_markers)
    # The same body for the authorized and the ordinary member.
    assert reference["owner"].json() == reference["player"].json()
    # A caller with no campaign access is unchanged: the campaign gate answers, as for any segment.
    for segment in (long_segment, "abc", "1"):
        refused = get(
            client_factory, outsider, url(g.campaign_id, pp.character, f"/versions/{segment}")
        )
        assert refused.status_code == 404
        assert (
            refused.json()
            == get(
                client_factory, outsider, url(g.campaign_id, pp.character, "/versions/abc")
            ).json()
        )
    after = (
        _text_of_tables(postgres_engine, "%idempot%"),
        _text_of_tables(postgres_engine, "audit", world=g.world_id),
        _text_of_tables(postgres_engine, "character_player_profile%"),
    )
    assert after == before


def test_the_version_segment_boundary_keeps_every_representable_version_readable(
    client_factory: Factory, postgres_engine: Engine, g: Gate, pp: Pp
) -> None:
    ok = {
        "1": 200,
        "0001": 200,  # leading zeros name the same version
        "0" * 5000 + "1": 200,  # ... however many, with nothing converted past the limit
    }
    missing = [
        str(BIGINT_MAX),  # the largest storable version: a miss only because none is stored
        "2",
        str(BIGINT_MAX + 1),  # beyond BIGINT
        "9" * 19,
        "9" * 20,
        "1" * 4300,
        "1" * 4301,
        "1" * 4302,
        "0" * 4301,
        "0",
        "00",
    ]
    malformed = ["abc", "1.5", "-1", "+1", "1e3", " 1", "1 ", "%C2%B2", "%D9%A1", "٣"]
    for segment, status in ok.items():
        response = get(
            client_factory, g.o1_user_id, url(g.campaign_id, pp.character, f"/versions/{segment}")
        )
        assert response.status_code == status, segment[:12]
        assert response.json()["profile_row_version"] == 1
    bodies = set()
    for segment in [*missing, *malformed]:
        response = get(
            client_factory, g.o1_user_id, url(g.campaign_id, pp.character, f"/versions/{segment}")
        )
        assert response.status_code == 404, (segment[:12], response.status_code)
        bodies.add(response.text)
    assert len(bodies) == 1
