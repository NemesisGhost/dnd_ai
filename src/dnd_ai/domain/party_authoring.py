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


class PartyMembershipOverlapError(SafeMessageError):
    """The character already belongs to this party during part of that period."""

    safe_status_code = 409
    safe_error_code = "party_membership_overlap"
    safe_message = "That character is already a member of this party at that time."


class PartyMemberInvalidError(SafeMessageError):
    """The member is not a published, active NPC or player character of this world."""

    safe_status_code = 400
    safe_error_code = "party_member_invalid"
    safe_message = "The selected character cannot join this party."


class PartyMembershipNotOpenError(SafeMessageError):
    """Only an open membership can be ended."""

    safe_status_code = 409
    safe_error_code = "party_membership_not_open"
    safe_message = "That membership has already ended."


class PartyMembershipEndInvalidError(SafeMessageError):
    """A membership must end after it starts."""

    safe_status_code = 409
    safe_error_code = "party_membership_end_not_after_start"
    safe_message = "The end time must be later than when the membership began."


PARTY_MEMBER_JOINED = "party_member_joined"
PARTY_MEMBER_LEFT = "party_member_left"
PARTY_MEMBERSHIP_COMPONENT = "party_membership"

__all__ = [
    "PARTY_ACTIVE",
    "PARTY_ARCHIVED",
    "PARTY_MEMBERSHIP_COMPONENT",
    "PARTY_MEMBER_JOINED",
    "PARTY_MEMBER_LEFT",
    "PartyMemberInvalidError",
    "PartyMembershipEndInvalidError",
    "PartyMembershipNotOpenError",
    "PartyMembershipOverlapError",
    "PartyNotActiveError",
    "PartyNotArchivedError",
    "normalize_description",
    "normalize_name",
]
