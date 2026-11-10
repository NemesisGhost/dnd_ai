# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Published species and size over HTTP (P03-A A4a, decision D6, plan sections 12.5 and 12.6).

The draft carries two strict-boolean controls; a release that publishes either snapshots the
character's actual species (id, code, label) and size with the `core.entities.row_version` they were
read at, and needs the version the releaser reviewed. No audience response reads any of it in A4a:
these tests cover the save, the release, the retry key, the audit and the GM read.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (  # noqa: F401 - fixtures by name
    APPEARANCE,
    Prof,
    body,
    code,
    counts,
    deny,
    draft_row,
    error_code,
    prof,
    read,
    release_rows,
    save,
    url,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.factories import make_species

pytestmark = pytest.mark.database


# --- helpers ----------------------------------------------------------------------------------


def identity_release(
    client_factory: Callable[[uuid.UUID], TestClient],
    user: uuid.UUID,
    g: Gate,
    character: uuid.UUID,
    version: int,
    character_version: int | None,
    *,
    key: str | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    payload: dict[str, object] = {"expected_draft_row_version": version}
    if character_version is not None:
        payload["expected_character_row_version"] = character_version
    with client_factory(user) as client:
        return client.post(url(g, character, "/releases"), json=payload, headers=headers)


def entity_row_version(engine: Engine, character: uuid.UUID) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT row_version FROM core.entities WHERE entity_id = :c"),
                {"c": character},
            ).scalar_one()
        )


def live_identity(engine: Engine, character: uuid.UUID) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text("""
                SELECT ch.species_id, ch.size_category, sp.code, sp.display_name
                FROM character.characters ch JOIN rules.species sp USING (species_id)
                WHERE ch.character_id = :c
            """),
            {"c": character},
        ).one()
    return {
        "species_id": row.species_id,
        "size": row.size_category,
        "code": row.code,
        "label": row.display_name,
    }


def change_identity(
    engine: Engine, character: uuid.UUID, *, size: str = "large", species_code: str = "elf"
) -> uuid.UUID:
    """The definition changes the way `update_character_identity` leaves it: a new species and
    size, and a bumped `core.entities.row_version`. (The races use the real commands.)"""
    with engine.begin() as connection:
        version_id = connection.execute(
            text("""
                SELECT sp.ruleset_version_id FROM character.characters ch
                JOIN rules.species sp USING (species_id) WHERE ch.character_id = :c
            """),
            {"c": character},
        ).scalar_one()
        species = make_species(
            connection, version_id, code=f"{species_code}_{uuid.uuid4().hex[:6]}"
        )
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "UPDATE character.characters SET species_id = :s, size_category = :z WHERE character_id = :c"
            ),
            {"s": species, "z": size, "c": character},
        )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE core.entities SET summary = :s WHERE entity_id = :c"),
            {"s": f"edited {uuid.uuid4().hex[:6]}", "c": character},
        )
    return species


def relabel_species(engine: Engine, species: uuid.UUID, label: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("UPDATE rules.species SET code = :c, display_name = :l WHERE species_id = :s"),
            {"c": label.lower().replace(" ", "_"), "l": label, "s": species},
        )


def identity_columns(engine: Engine, g: Gate, character: uuid.UUID) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT version_number, from_draft_row_version, released_species_id,
                       released_species_code, released_species_display_name,
                       released_size_category, identity_entity_row_version
                FROM campaign.character_public_profile_releases
                WHERE campaign_id = :c AND character_id = :ch ORDER BY version_number
            """),
            {"c": g.campaign_id, "ch": character},
        ).mappings()
        return [dict(row) for row in rows]


def flags(engine: Engine, g: Gate, character: uuid.UUID) -> tuple[bool, bool, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text("""
                SELECT should_publish_species, should_publish_size, row_version
                FROM campaign.character_public_profiles
                WHERE campaign_id = :c AND character_id = :ch
            """),
            {"c": g.campaign_id, "ch": character},
        ).one()
    return (bool(row[0]), bool(row[1]), int(row[2]))


def audit_fields(engine: Engine, g: Gate, command: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT changed_fields FROM audit.change_log "
                "WHERE world_id = :w AND command_name = :n ORDER BY change_log_id"
            ),
            {"w": g.world_id, "n": command},
        ).all()
    return [dict(r[0]) for r in rows]


# --- the draft controls (12.5) -------------------------------------------------------------------


def test_each_flag_sets_clears_and_repeats_as_a_no_op_with_one_bump_and_the_audit_names(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    created = save(
        client_factory, g.o1_user_id, g, c,
        {"expected_row_version": None, "public_appearance": APPEARANCE},
    )  # fmt: skip
    assert code(created) == 201
    assert flags(postgres_engine, g, c) == (False, False, 1)  # both off by default

    on = save(
        client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "publish_species": True}
    )
    assert code(on) == 200 and body(on)["changed"] is True and body(on)["row_version"] == 2
    assert flags(postgres_engine, g, c) == (True, False, 2)

    # Setting the value it already has is a no-op: no bump, no audit row.
    audited = counts(postgres_engine, g)
    same = save(
        client_factory, g.o1_user_id, g, c, {"expected_row_version": 2, "publish_species": True}
    )
    assert code(same) == 200 and body(same)["changed"] is False and body(same)["row_version"] == 2
    assert counts(postgres_engine, g) == audited

    # A flag and a text change in one request: one bump.
    both = save(
        client_factory, g.o1_user_id, g, c,
        {"expected_row_version": 2, "publish_size": True, "public_appearance": "Changed"},
    )  # fmt: skip
    assert code(both) == 200 and body(both)["row_version"] == 3
    assert flags(postgres_engine, g, c) == (True, True, 3)

    # Absent leaves each untouched; an explicit false clears.
    untouched = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 3, "public_appearance": "Again"})  # fmt: skip
    assert code(untouched) == 200 and flags(postgres_engine, g, c) == (True, True, 4)
    cleared = save(
        client_factory, g.o1_user_id, g, c,
        {"expected_row_version": 4, "publish_species": False, "publish_size": False},
    )  # fmt: skip
    assert code(cleared) == 200 and body(cleared)["row_version"] == 5
    assert flags(postgres_engine, g, c) == (False, False, 5)

    names = [
        row["changed_field_names"]
        for row in audit_fields(postgres_engine, g, "save_character_public_profile_draft")
    ]
    assert names[0] == ["public_appearance"]
    assert names[1] == ["publish_species"]
    assert sorted(names[2]) == ["public_appearance", "publish_size"]
    assert names[3] == ["public_appearance"]
    assert names[4] == ["publish_species", "publish_size"]
    # The audit never carries a species code, a label or a size.
    assert "elf" not in str(names)


def test_a_flag_may_be_set_by_the_first_save_and_null_is_422(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    for bad in (None, "true", 1, "yes"):
        refused = save(
            client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "publish_size": bad}
        )
        assert code(refused) == 422, bad
    assert draft_row(postgres_engine, g, c) is None  # nothing written
    first = save(
        client_factory, g.o1_user_id, g, c,
        {"expected_row_version": None, "publish_species": True, "publish_size": True},
    )  # fmt: skip
    assert code(first) == 201 and flags(postgres_engine, g, c) == (True, True, 1)
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "publish_species": None})) == 422  # fmt: skip
    assert flags(postgres_engine, g, c) == (True, True, 1)


def test_the_d8_edit_refusals_are_unchanged_for_a_flag_save(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    c = prof.character_id
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None})) == 201
    # A player has no `canon.edit`: refused at the route; the draft is untouched.
    refused = save(client_factory, g.player_user_id, g, c, {"expected_row_version": 1, "publish_species": True})  # fmt: skip
    assert code(refused) == 403
    # A stale token is a 409 and writes nothing.
    stale = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 7, "publish_species": True})  # fmt: skip
    assert code(stale) == 409 and error_code(stale) == "stale_write"
    # A canon.edit deny on the character: 403 public_profile_edit_denied for a flag too.
    deny(postgres_engine, g, m.gm, "canon.edit", c)
    denied = save(client_factory, m.gm_user_id, g, c, {"expected_row_version": 1, "publish_species": True})  # fmt: skip
    assert code(denied) == 403 and error_code(denied) == "public_profile_edit_denied"
    assert flags(postgres_engine, g, c) == (False, False, 1)


# --- the release (12.6) --------------------------------------------------------------------------


def draft_with(
    client_factory: Callable[[uuid.UUID], TestClient], g: Gate, c: uuid.UUID, **flags_: bool
) -> int:
    created = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": APPEARANCE, **flags_})  # fmt: skip
    assert code(created) == 201, body(created)
    return int(body(created)["row_version"])


@pytest.mark.parametrize(
    ("species", "size"),
    [(True, False), (False, True), (True, True)],
    ids=["species", "size", "both"],
)
def test_a_flagged_release_snapshots_exactly_the_selected_live_values(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof,
    species: bool, size: bool,
) -> None:  # fmt: skip
    c = prof.character_id
    v = draft_with(client_factory, g, c, publish_species=species, publish_size=size)
    live = live_identity(postgres_engine, c)
    token = entity_row_version(postgres_engine, c)
    released = identity_release(client_factory, g.o1_user_id, g, c, v, token)
    assert code(released) == 201, body(released)
    receipt = body(released)
    assert receipt["species_published"] is species and receipt["size_published"] is size
    assert receipt["identity_entity_row_version"] == token
    [row] = identity_columns(postgres_engine, g, c)
    assert row["released_species_id"] == (live["species_id"] if species else None)
    assert row["released_species_code"] == (live["code"] if species else None)
    assert row["released_species_display_name"] == (live["label"] if species else None)
    assert row["released_size_category"] == (live["size"] if size else None)
    assert row["identity_entity_row_version"] == token
    audit = audit_fields(postgres_engine, g, "release_character_public_profile")
    assert audit[-1]["species_published"] is species and audit[-1]["size_published"] is size
    assert audit[-1]["identity_entity_row_version"] == token
    assert live["code"] not in str(audit) and live["size"] not in str(audit)


def test_a_release_without_a_flag_is_the_a2_release_and_ignores_the_token(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    v = draft_with(client_factory, g, c)
    # No token, a wrong token and a stale one all behave alike: nothing is validated or stored.
    first = identity_release(client_factory, g.o1_user_id, g, c, v, 9999)
    assert code(first) == 201 and body(first)["species_published"] is False
    assert (
        body(first)["size_published"] is False
        and body(first)["identity_entity_row_version"] is None
    )
    [row] = identity_columns(postgres_engine, g, c)
    assert row["identity_entity_row_version"] is None and row["released_species_id"] is None
    retry = identity_release(client_factory, g.o1_user_id, g, c, v, None)
    assert code(retry) == 200 and body(retry)["created"] is False
    assert (
        body(retry)["character_public_profile_release_id"]
        == body(first)["character_public_profile_release_id"]
    )


def test_a_flagged_release_needs_the_token_and_a_current_one(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    v = draft_with(client_factory, g, c, publish_species=True)
    before = counts(postgres_engine, g)
    missing = identity_release(client_factory, g.o1_user_id, g, c, v, None)
    assert (
        code(missing) == 422 and error_code(missing) == "public_profile_identity_version_required"
    )
    token = entity_row_version(postgres_engine, c)
    stale = identity_release(client_factory, g.o1_user_id, g, c, v, token + 1)
    assert code(stale) == 409 and error_code(stale) == "stale_write"
    assert counts(postgres_engine, g) == before  # nothing written
    # A definition edit moves the version: the old token is now stale.
    change_identity(postgres_engine, c)
    old = identity_release(client_factory, g.o1_user_id, g, c, v, token)
    assert code(old) == 409 and error_code(old) == "stale_write"
    assert counts(postgres_engine, g) == before
    fresh = identity_release(
        client_factory, g.o1_user_id, g, c, v, entity_row_version(postgres_engine, c)
    )
    assert code(fresh) == 201


def test_a_releaser_without_a_character_view_tier_is_refused_403_field_withheld(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    v = draft_with(client_factory, g, c, publish_size=True)
    # A raw stray `canon.edit` deny under `character_id`: the owner's only character-view source is
    # `canon.edit` (the built-in owner holds no `character.view_full`).
    deny(postgres_engine, g, g.o1, "canon.edit", c, key="character_id")
    before = counts(postgres_engine, g)
    refused = identity_release(
        client_factory, g.o1_user_id, g, c, v, entity_row_version(postgres_engine, c)
    )
    assert code(refused) == 403 and error_code(refused) == "public_profile_field_withheld"
    assert counts(postgres_engine, g) == before
    # A flag-less draft version of the same character still releases for this owner.
    assert code(save(client_factory, g.o2_user_id, g, c, {"expected_row_version": 1, "publish_size": False})) == 200  # fmt: skip
    assert code(identity_release(client_factory, g.o1_user_id, g, c, 2, None)) == 201


def test_the_natural_retry_and_the_keyed_replay(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    v = draft_with(client_factory, g, c, publish_species=True, publish_size=True)
    token = entity_row_version(postgres_engine, c)
    first = identity_release(client_factory, g.o1_user_id, g, c, v, token, key="k-identity")
    assert code(first) == 201
    # The same key and body: the stored receipt, with the new flags and version, and no new row.
    replay = identity_release(client_factory, g.o1_user_id, g, c, v, token, key="k-identity")
    assert code(replay) == 201 and body(replay)["version_number"] == 1
    assert body(replay)["species_published"] is True and body(replay)["size_published"] is True
    assert body(replay)["identity_entity_row_version"] == token
    assert len(identity_columns(postgres_engine, g, c)) == 1
    # A retry with the same token and no key: 200 created false, the same release.
    retry = identity_release(client_factory, g.o1_user_id, g, c, v, token)
    assert code(retry) == 200 and body(retry)["created"] is False
    assert (
        body(retry)["character_public_profile_release_id"]
        == body(first)["character_public_profile_release_id"]
    )
    assert (
        body(retry)["species_published"] is True
        and body(retry)["identity_entity_row_version"] == token
    )
    # After a definition edit a retry with the old token is still that release (never a false
    # stale write), and a keyed replay stays the stored receipt: no new snapshot.
    change_identity(postgres_engine, c)
    again = identity_release(client_factory, g.o1_user_id, g, c, v, token)
    assert code(again) == 200 and body(again)["version_number"] == 1
    assert body(identity_release(client_factory, g.o1_user_id, g, c, v, token, key="k-identity"))["version_number"] == 1  # fmt: skip
    assert len(identity_columns(postgres_engine, g, c)) == 1
    # The same draft version with the NEW character version: a new release snapshotting new values.
    new_token = entity_row_version(postgres_engine, c)
    second = identity_release(client_factory, g.o1_user_id, g, c, v, new_token)
    assert code(second) == 201 and body(second)["version_number"] == 2
    new = live_identity(postgres_engine, c)
    first_row, second_row = identity_columns(postgres_engine, g, c)
    assert first_row["from_draft_row_version"] == second_row["from_draft_row_version"] == v
    assert second_row["released_species_code"] == new["code"]
    assert second_row["released_size_category"] == new["size"]
    assert second_row["identity_entity_row_version"] == new_token > token
    assert first_row["released_species_code"] != new["code"]
    # A second flagged-release key reuse with a different token is the existing idempotency conflict.
    conflict = identity_release(client_factory, g.o1_user_id, g, c, v, new_token, key="k-identity")
    assert code(conflict) == 409 and error_code(conflict) != "stale_write"


def test_a_snapshot_survives_later_species_size_and_label_changes_and_a_later_release_may_withhold(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    v = draft_with(client_factory, g, c, publish_species=True, publish_size=True)
    live = live_identity(postgres_engine, c)
    first = identity_release(
        client_factory, g.o1_user_id, g, c, v, entity_row_version(postgres_engine, c)
    )
    assert code(first) == 201
    before = body(read(client_factory, g.o1_user_id, g, c, "/releases/1"))
    assert before["species"] == {"code": live["code"], "label": live["label"]}
    assert before["size"] == {"code": live["size"], "label": live["size"].title()}
    assert before["identity_entity_row_version"] == entity_row_version(postgres_engine, c)
    assert (
        body(read(client_factory, g.o1_user_id, g, c))["identity_differs_from_latest_release"]
        is False
    )

    new_species = change_identity(postgres_engine, c, size="tiny")
    relabel_species(postgres_engine, live["species_id"], "Relabelled")
    relabel_species(postgres_engine, new_species, "Also Relabelled")
    after = body(read(client_factory, g.o1_user_id, g, c, "/releases/1"))
    assert after == before  # the release is unchanged
    view = body(read(client_factory, g.o1_user_id, g, c))
    assert view["identity_differs_from_latest_release"] is True
    assert view["latest_release"]["species"] == before["species"]
    assert view["identity_preview"]["species"] == {
        "code": "also_relabelled",
        "label": "Also Relabelled",
    }
    assert view["identity_preview"]["size"] == {"code": "tiny", "label": "Tiny"}

    # A later release with the flags off withholds both: the latest release wins as a whole.
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": v, "publish_species": False, "publish_size": False})) == 200  # fmt: skip
    later = identity_release(client_factory, g.o1_user_id, g, c, v + 1, None)
    assert code(later) == 201 and body(later)["species_published"] is False
    latest = body(read(client_factory, g.o1_user_id, g, c))
    assert latest["latest_release"]["species"] is None and latest["latest_release"]["size"] is None
    assert latest["latest_release"]["identity_entity_row_version"] is None
    assert latest["identity_differs_from_latest_release"] is False
    # Older releases keep what they published.
    assert (
        body(read(client_factory, g.o1_user_id, g, c, "/releases/1"))["species"]
        == before["species"]
    )


# --- the GM read (12.6) --------------------------------------------------------------------------


def test_the_gm_read_shows_flags_preview_and_the_differs_flag(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    empty = body(read(client_factory, g.o1_user_id, g, c))
    assert empty["draft"] is None and empty["identity_differs_from_latest_release"] is False
    v = draft_with(client_factory, g, c, publish_species=True)
    live = live_identity(postgres_engine, c)
    view = body(read(client_factory, g.o1_user_id, g, c))
    assert view["draft"]["publish_species"] is True and view["draft"]["publish_size"] is False
    assert view["identity_preview_withheld"] is False and view["can_release"] is True
    assert view["identity_preview"] == {
        "character_row_version": entity_row_version(postgres_engine, c),
        "species": {"code": live["code"], "label": live["label"]},
        "size": {"code": live["size"], "label": live["size"].title()},
    }
    assert view["identity_differs_from_latest_release"] is False  # nothing released yet
    # A release that published only the species is stale on the species, not on a size change.
    assert code(identity_release(client_factory, g.o1_user_id, g, c, v, view["identity_preview"]["character_row_version"])) == 201  # fmt: skip
    change_identity(postgres_engine, c, size="gargantuan")
    relabel = body(read(client_factory, g.o1_user_id, g, c))
    assert relabel["identity_differs_from_latest_release"] is True  # the species changed too
    # The summaries list never carries a species or size.
    assert all("species" not in row for row in relabel["releases"])


def test_a_reader_with_no_character_view_tier_sees_the_preview_withheld_and_cannot_release(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    draft_with(client_factory, g, c, publish_species=True)
    deny(postgres_engine, g, g.o1, "canon.edit", c, key="character_id")  # leaves no view tier
    view = body(read(client_factory, g.o1_user_id, g, c))
    assert view["identity_preview"] is None and view["identity_preview_withheld"] is True
    assert view["can_release"] is False
    # The draft flag itself is the GM's own draft and stays visible.
    assert view["draft"]["publish_species"] is True
    # With neither flag set, can_release does not depend on the preview.
    other = prof.other_character_id
    assert code(save(client_factory, g.o2_user_id, g, other, {"expected_row_version": None, "public_appearance": "x"})) == 201  # fmt: skip
    deny(postgres_engine, g, g.o1, "canon.edit", other, key="character_id")
    plain = body(read(client_factory, g.o1_user_id, g, other))
    assert plain["identity_preview_withheld"] is True and plain["can_release"] is True
