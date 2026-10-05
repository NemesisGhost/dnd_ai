"""Party definition policy (Phase 15 checkpoint 15.2C-1, decision D-30).

A party is a world-level group attached to campaigns; its identity (name,
description) is authored, while membership is timeline state (checkpoint
15.2C-2). Its operational lifecycle is `active` / `archived`: an archived party
stays referenced by history, is hidden from pickers, and takes no new membership
or knowledge writes. Errors here are fixed-code 409s.
"""

from .authoring import normalize_description, normalize_name
from .errors import SafeMessageError

PARTY_ACTIVE = "active"
PARTY_ARCHIVED = "archived"


class PartyNotActiveError(SafeMessageError):
    """The action needs an active party (edit, new membership, knowledge write)."""

    safe_status_code = 409
    safe_error_code = "party_not_active"
    safe_message = "This party is archived. Restore it first."


class PartyNotArchivedError(SafeMessageError):
    """Restore applies only to an archived party."""

    safe_status_code = 409
    safe_error_code = "party_not_archived"
    safe_message = "This party is not archived."


__all__ = [
    "PARTY_ACTIVE",
    "PARTY_ARCHIVED",
    "PartyNotActiveError",
    "PartyNotArchivedError",
    "normalize_description",
    "normalize_name",
]
