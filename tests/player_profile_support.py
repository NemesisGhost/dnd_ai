"""The only raw writer of the campaign player-profile tables (P03-A A5a, design section 11.1).

A5 is infrastructure with no production writer (decision D18): no application role can write the
profile tables (`app_read_write` holds SELECT only; `integration_worker` and `app_read_only` hold
no access), and nothing under `src/` writes them. Tests that need a
profile populate it through this module, which runs as the test superuser and follows the write
shape P03-B's controller edit command will have (design section 6.2), minus the assignment row P03-B
introduces:

1. the world `FOR SHARE`, then the editing member's membership and account, then the campaign;
2. the character's `core.entities` row `FOR SHARE`;
3. the profile head `FOR UPDATE`, or an `INSERT ... ON CONFLICT (campaign_id, character_id) DO
   NOTHING` race for the first version;
4. a head `UPDATE` that bumps `row_version`;
5. a version `INSERT` carrying that `row_version` and the editing membership.

A structural test (tests/unit/test_player_profiles_structure.py) confines raw INSERT/UPDATE of the
profile tables under `tests/` to this module and to the database tests that probe the schema's own
triggers. P03-B replaces this module's production role with the controller command.

`fields` is the complete state of the new version: a code left out is stored as NULL.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.player_profiles import PLAYER_PROFILE_FIELDS

_HEAD = "campaign.character_player_profiles"
_VERSIONS = "campaign.character_player_profile_versions"


def _lock_scope(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    editor_membership_id: uuid.UUID,
) -> None:
    connection.execute(
        text("""
            SELECT 1 FROM core.worlds w
            JOIN campaign.timelines t ON t.world_id = w.world_id
            JOIN campaign.campaigns c ON c.timeline_id = t.timeline_id
            WHERE c.campaign_id = :campaign FOR SHARE OF w
        """),
        {"campaign": campaign_id},
    )
    connection.execute(
        text("""
            SELECT 1 FROM security.campaign_memberships cm
            JOIN security.users u ON u.user_id = cm.user_id
            WHERE cm.campaign_membership_id = :membership FOR SHARE OF cm, u
        """),
        {"membership": editor_membership_id},
    )
    connection.execute(
        text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR KEY SHARE"),
        {"c": campaign_id},
    )
    connection.execute(
        text("SELECT 1 FROM core.entities WHERE entity_id = :e FOR SHARE"), {"e": character_id}
    )


def _insert_version(
    connection: Connection,
    *,
    profile_id: uuid.UUID,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    row_version: int,
    editor_membership_id: uuid.UUID,
    fields: Mapping[str, str | None],
) -> None:
    unknown = set(fields) - set(PLAYER_PROFILE_FIELDS)
    if unknown:
        raise ValueError(f"unknown player-profile fields: {sorted(unknown)}")
    columns = ", ".join(PLAYER_PROFILE_FIELDS)
    placeholders = ", ".join(f":f_{code}" for code in PLAYER_PROFILE_FIELDS)
    connection.execute(
        text(f"""
            INSERT INTO {_VERSIONS} (
                character_player_profile_id, campaign_id, character_id, profile_row_version,
                edited_by_campaign_membership_id, {columns})
            VALUES (:profile, :campaign, :character, :row_version, :editor, {placeholders})
        """),  # noqa: S608
        {
            "profile": profile_id,
            "campaign": campaign_id,
            "character": character_id,
            "row_version": row_version,
            "editor": editor_membership_id,
            **{f"f_{code}": fields.get(code) for code in PLAYER_PROFILE_FIELDS},
        },
    )


def seed_player_profile_in(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    editor_membership_id: uuid.UUID,
    fields: Mapping[str, str | None],
) -> uuid.UUID:
    """Creates the profile (head at `row_version` 1 and its first version) inside the caller's
    transaction and returns the head id."""
    _lock_scope(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        editor_membership_id=editor_membership_id,
    )
    head = connection.execute(
        text(f"""
            INSERT INTO {_HEAD} (campaign_id, character_id)
            VALUES (:campaign, :character)
            ON CONFLICT (campaign_id, character_id) DO NOTHING
            RETURNING character_player_profile_id
        """),  # noqa: S608
        {"campaign": campaign_id, "character": character_id},
    ).scalar_one_or_none()
    if head is None:
        raise ValueError("the character already has a player profile in this campaign")
    _insert_version(
        connection,
        profile_id=head,
        campaign_id=campaign_id,
        character_id=character_id,
        row_version=1,
        editor_membership_id=editor_membership_id,
        fields=fields,
    )
    assert isinstance(head, uuid.UUID)
    return head


def edit_player_profile_in(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    editor_membership_id: uuid.UUID,
    fields: Mapping[str, str | None],
) -> int:
    """Adds a version inside the caller's transaction (the head `FOR UPDATE`, then a head `UPDATE`
    that bumps `row_version`, then the version) and returns the new `row_version`. The head lock is
    held until the caller commits or rolls back."""
    _lock_scope(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        editor_membership_id=editor_membership_id,
    )
    head = connection.execute(
        text(f"""
            SELECT character_player_profile_id FROM {_HEAD}
            WHERE campaign_id = :campaign AND character_id = :character FOR UPDATE
        """),  # noqa: S608
        {"campaign": campaign_id, "character": character_id},
    ).scalar_one()
    row_version = connection.execute(
        text(f"""
            UPDATE {_HEAD} SET updated_at = now()
            WHERE character_player_profile_id = :profile RETURNING row_version
        """),  # noqa: S608
        {"profile": head},
    ).scalar_one()
    _insert_version(
        connection,
        profile_id=head,
        campaign_id=campaign_id,
        character_id=character_id,
        row_version=int(row_version),
        editor_membership_id=editor_membership_id,
        fields=fields,
    )
    return int(row_version)


def seed_player_profile(
    engine: Engine,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    editor_membership_id: uuid.UUID,
    fields: Mapping[str, str | None],
) -> uuid.UUID:
    """Creates a profile in its own committed transaction."""
    with engine.begin() as connection:
        return seed_player_profile_in(
            connection,
            campaign_id=campaign_id,
            character_id=character_id,
            editor_membership_id=editor_membership_id,
            fields=fields,
        )


def edit_player_profile(
    engine: Engine,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    editor_membership_id: uuid.UUID,
    fields: Mapping[str, str | None],
) -> int:
    """Adds a version in its own committed transaction and returns the new `row_version`."""
    with engine.begin() as connection:
        return edit_player_profile_in(
            connection,
            campaign_id=campaign_id,
            character_id=character_id,
            editor_membership_id=editor_membership_id,
            fields=fields,
        )


def markers(campaign_label: str) -> dict[str, str]:
    """A distinct marker per field and campaign label, e.g. `PP-A-ideals-4f2c`."""
    nonce = uuid.uuid4().hex[:4]
    return {code: f"PP-{campaign_label}-{code}-{nonce}" for code in PLAYER_PROFILE_FIELDS}


# --- A5b: seeding a public-profile draft field that came from a player profile ------------------------
#
# A5c's copy command does not exist yet, so nothing in `src/` writes the `player_profile` origin. This
# helper is the only raw seeding of such a draft field: it performs the write the copy will perform
# (design section 9.3, step 7) so that A5b's rules can be exercised, and it satisfies the migration
# 148 trigger and CHECKs. A5c replaces it with the real command.

_DRAFTS = "campaign.character_public_profiles"
_FIELD_COLUMNS = {
    "public_appearance": (
        "public_appearance_origin_id",
        "public_appearance_origin_entity_row_version",
        "public_appearance_origin_player_profile_version_id",
        "public_appearance_origin_player_profile_field_id",
        "public_appearance_restricted_row_version",
    ),
    "public_background": (
        "public_background_origin_id",
        "public_background_origin_entity_row_version",
        "public_background_origin_player_profile_version_id",
        "public_background_origin_player_profile_field_id",
        "public_background_restricted_row_version",
    ),
}


def _origin_id(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text(
            "SELECT public_profile_field_origin_id FROM campaign.public_profile_field_origins "
            "WHERE code = :c"
        ),
        {"c": code},
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def seed_player_profile_copy_in(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    membership_id: uuid.UUID,
    target_field: str,
    source_field: str,
    profile_row_version: int | None = None,
) -> int:
    """Copies `source_field` of the character's player-profile version (the current one, or
    `profile_row_version`) into the draft's `target_field`, as the A5c copy will: the text, the
    `player_profile` origin, the provenance pair and a watermark equal to the draft's new
    `row_version`. Creates the draft when there is none (only this field set). Returns the draft's
    new `row_version`. Raises `ValueError` for a source field with no text."""
    version_id, text_value = connection.execute(
        text(f"""
            SELECT v.character_player_profile_version_id, v.{source_field}
            FROM campaign.character_player_profiles h
            JOIN campaign.character_player_profile_versions v
              ON v.character_player_profile_id = h.character_player_profile_id
             AND v.profile_row_version = COALESCE(:version, h.row_version)
            WHERE h.campaign_id = :campaign AND h.character_id = :character
        """),  # noqa: S608
        {"campaign": campaign_id, "character": character_id, "version": profile_row_version},
    ).one()
    if text_value is None:
        raise ValueError(f"the player-profile field {source_field} has no text")
    field_id = connection.execute(
        text("SELECT player_profile_field_id FROM campaign.player_profile_fields WHERE code = :c"),
        {"c": source_field},
    ).scalar_one()
    origin, _entity_version, pp_version, pp_field, watermark = _FIELD_COLUMNS[target_field]
    other_field = (
        "public_background" if target_field == "public_appearance" else "public_appearance"
    )
    other_origin = _FIELD_COLUMNS[other_field][0]
    params = {
        "campaign": campaign_id,
        "character": character_id,
        "membership": membership_id,
        "text": text_value,
        "origin": _origin_id(connection, "player_profile"),
        "authored": _origin_id(connection, "authored"),
        "version": version_id,
        "field": field_id,
    }
    existing = connection.execute(
        text(f"""
            SELECT character_public_profile_id, row_version FROM {_DRAFTS}
            WHERE campaign_id = :campaign AND character_id = :character FOR UPDATE
        """),  # noqa: S608
        params,
    ).one_or_none()
    if existing is None:
        connection.execute(
            text(f"""
                INSERT INTO {_DRAFTS} (campaign_id, character_id, {target_field}, {origin},
                    {pp_version}, {pp_field}, {watermark}, {other_origin},
                    created_by_membership_id, updated_by_membership_id)
                VALUES (:campaign, :character, :text, :origin, :version, :field, 1, :authored,
                        :membership, :membership)
            """),  # noqa: S608
            params,
        )
        return 1
    new_version = int(existing.row_version) + 1
    connection.execute(
        text(f"""
            UPDATE {_DRAFTS}
            SET {target_field} = :text, {origin} = :origin,
                {_FIELD_COLUMNS[target_field][1]} = NULL,
                {pp_version} = :version, {pp_field} = :field, {watermark} = :new_version,
                updated_by_membership_id = :membership
            WHERE character_public_profile_id = :profile
        """),  # noqa: S608
        {**params, "profile": existing.character_public_profile_id, "new_version": new_version},
    )
    return new_version


def seed_player_profile_copy(engine: Engine, **kwargs: Any) -> int:
    """`seed_player_profile_copy_in` in its own committed transaction."""
    with engine.begin() as connection:
        return seed_player_profile_copy_in(connection, **kwargs)
