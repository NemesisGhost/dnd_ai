"""Character player-profile GM reads (P03-A A5a): storage and reads, no writer.

    GET /campaigns/{campaign_id}/characters/{character_id}/player-profile
    GET /campaigns/{campaign_id}/characters/{character_id}/player-profile/versions/{profile_row_version}

The route dependency is `campaign.view`, not `canon.edit`: P03-B's controller read reuses these
routes and controllers need not hold `canon.edit` (D15). The read rule runs in the query
(`may_read_player_profile`, whose only A5 branch is effective character-scoped `canon.edit`), and a
caller who fails it gets the same generic 404 as for a missing profile version or a non-canon
character; no body says whether a profile exists.

There is no production writer of the profile (D18), so there is no POST here, no idempotency, no
audit row and no receipt. The text appears only in an authorized read's response.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.player_profiles import read_player_profile, read_player_profile_version

from .access import require_campaign_capability
from .deps import get_connection
from .errors import NotFoundError

router = APIRouter(tags=["character-player-profile"])

_BASE = "/campaigns/{campaign_id}/characters/{character_id}/player-profile"

_view_access = require_campaign_capability("campaign.view")

_Conn = Annotated[Connection, Depends(get_connection)]

_MAX_ROW_VERSION = 9_223_372_036_854_775_807  # BIGINT
_MAX_ROW_VERSION_DIGITS = len(str(_MAX_ROW_VERSION))


def _parse_row_version(segment: str) -> int | None:
    """The version a path segment names, or `None` when it names none (the generic 404).

    ASCII digits only, so a superscript digit is not a number. Leading zeros are dropped *before*
    the length is bounded, so `0001` still names version 1, and anything with more significant
    digits than the largest BIGINT is refused without ever being converted: `int()` raises on a
    string beyond Python's integer-conversion limit (4,300 digits), and that error would otherwise
    escape as a `400 validation_failed` that names this resource's profile route differently from
    every other miss."""
    if not (segment.isascii() and segment.isdigit()):
        return None
    significant = segment.lstrip("0")
    if not significant or len(significant) > _MAX_ROW_VERSION_DIGITS:
        return None
    value = int(significant)
    return value if value <= _MAX_ROW_VERSION else None


@router.get(_BASE)
def get_character_player_profile_endpoint(
    character_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(_view_access)],
    connection: _Conn,
) -> dict[str, Any]:
    view = read_player_profile(connection, access=access, character_id=character_id)
    if view is None:
        raise NotFoundError()
    return view


@router.get(_BASE + "/versions/{profile_row_version}")
def get_character_player_profile_version_endpoint(
    character_id: uuid.UUID,
    profile_row_version: str,
    access: Annotated[AccessContext, Depends(_view_access)],
    connection: _Conn,
) -> dict[str, Any]:
    # A segment that is not a version number names nothing: the same 404 as a missing version (and
    # the route manifest's generic probes substitute a UUID here).
    number = _parse_row_version(profile_row_version)
    if number is None:
        raise NotFoundError()
    version = read_player_profile_version(
        connection, access=access, character_id=character_id, profile_row_version=number
    )
    if version is None:
        raise NotFoundError()
    return version
