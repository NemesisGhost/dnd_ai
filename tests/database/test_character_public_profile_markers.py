# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Profile text stays out of every other response in A2a (plan sections 5.11 and A2a criterion 8).

A draft and a release carry distinct markers. Every GET the application exposes that needs only a
campaign id and a character id is read as each kind of audience; no response body may contain a
marker. Nothing but the GM-side profile routes reads the new tables, so this is a regression net,
not a filter: if a later change joined the profile into the character detail, the sweep fails.
Campaign B's GM gets 404 from A's profile routes.
"""

import re
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.app import create_app
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    _template_role_id,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (  # noqa: F401 - fixtures by name
    Prof,
    prof,
    release,
    save,
    url,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_resource_grant,
    make_user,
)

pytestmark = pytest.mark.database

RELEASED_APPEARANCE = "RELEASED-APPEARANCE-MARKER-5530"
RELEASED_BACKGROUND = "RELEASED-BACKGROUND-MARKER-6641"
RELEASED_NOTE = "RELEASE-NOTE-MARKER-7752"
DRAFT_TEXT = "LATER-DRAFT-MARKER-8863"
MARKERS = (RELEASED_APPEARANCE, RELEASED_BACKGROUND, RELEASED_NOTE, DRAFT_TEXT)

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_PROFILE_ROUTE = "/public-profile"


def _sweep_paths(g: Gate, character: uuid.UUID) -> list[str]:
    """Every GET of the application whose path needs only a campaign id and a character id."""
    paths: list[str] = []
    for template, operations in create_app().openapi()["paths"].items():
        if "get" not in operations or not template.startswith("/campaigns/{campaign_id}"):
            continue
        if _PROFILE_ROUTE in template:
            continue
        if set(_PLACEHOLDER.findall(template)) - {"campaign_id", "character_id"}:
            continue
        paths.append(
            template.replace("{campaign_id}", str(g.campaign_id)).replace(
                "{character_id}", str(character)
            )
        )
    return sorted(paths)


def test_no_other_response_carries_draft_or_release_text(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    c = prof.character_id
    assert save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": RELEASED_APPEARANCE, "public_background": RELEASED_BACKGROUND}).status_code == 201  # type: ignore[attr-defined]  # fmt: skip
    assert release(client_factory, g.o1_user_id, g, c, 1, note=RELEASED_NOTE).status_code == 201  # type: ignore[attr-defined]
    assert save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": DRAFT_TEXT}).status_code == 200  # type: ignore[attr-defined]  # fmt: skip

    with postgres_engine.begin() as connection:
        full_user = make_user(connection, "Marker Full Viewer")
        full = make_campaign_membership(connection, g.campaign_id, full_user)
        make_membership_role(connection, full, g.player_role_id)
        make_resource_grant(
            connection,
            g.campaign_id,
            lookup_id(
                connection, "security", "capabilities", "capability_id", "character.view_full"
            ),
            timeline_id=g.timeline_id,
            grantee_campaign_membership_id=full,
            character_id=c,
        )
        observer = make_user(connection, "Marker Observer")
        observer_membership = make_campaign_membership(connection, g.campaign_id, observer)
        make_membership_role(
            connection, observer_membership, _template_role_id(connection, "observer")
        )
        other_campaign = make_campaign(connection, g.timeline_id, "Marker Campaign B")
        b_gm = make_user(connection, "Marker B GM")
        b_membership = make_campaign_membership(connection, other_campaign, b_gm)
        make_membership_role(connection, b_membership, g.owner_role_id)

    audiences = {
        "player": g.player_user_id,
        "player with view_full": full_user,
        "observer": observer,
    }
    paths = _sweep_paths(g, c)
    assert len(paths) >= 10, "the route table was not read; the sweep would be vacuous"
    leaks: list[tuple[str, str, str]] = []
    for name, user in audiences.items():
        with client_factory(user) as client:
            for path in paths:
                response = client.get(path)
                leaks.extend((name, path, marker) for marker in MARKERS if marker in response.text)
    assert leaks == []

    # Campaign B's GM reads nothing of A's profile, and A's routes do not exist for them.
    with client_factory(b_gm) as client:
        assert client.get(url(g, c)).status_code == 404
        assert client.get(url(g, c, "/releases/1")).status_code == 404
        refused = client.post(url(g, c, "/releases"), json={"expected_draft_row_version": 1})
        assert refused.status_code == 404
        for path in paths:
            assert not any(marker in client.get(path).text for marker in MARKERS)

    with postgres_engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "DELETE FROM security.membership_roles WHERE campaign_membership_id IN "
                "(SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c)"
            ),
            {"c": other_campaign},
        )
        connection.execute(
            text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
            {"c": other_campaign},
        )
        connection.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"), {"c": other_campaign}
        )
