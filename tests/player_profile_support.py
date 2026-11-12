"""The only raw writer of the campaign player-profile tables (P03-A A5a, design section 11.1).

A5 is infrastructure with no production writer (decision D18): the application roles can SELECT the
profile tables and cannot write them, and nothing under `src/` writes them. Tests that need a
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
