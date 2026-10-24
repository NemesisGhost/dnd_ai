"""Per-record authoring eligibility (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

Shared world canon is written with campaign `canon.edit` **and** the matching world
capability, except for the campaign-originated records that live in world tables
(player-character identity and item instances, decision D8 E2/E3), which stay
authorized by the campaign alone, lifecycle included. This module is the one place
that states that rule, so the commands that enforce it, the read models that tell the
portal which buttons to render, and the per-record eligibility fields cannot drift
apart:

- `LIFECYCLE_ACTION_CAPABILITIES` is the world capability each lifecycle action needs
  (preparing and withdrawing a draft is editing; approving, publishing, superseding,
  archiving and restoring is reviewing);
- `CAMPAIGN_ORIGINATED_TYPES` are the exceptions;
- `record_authoring` resolves what one caller may do to one record from the caller's
  campaign `canon.edit` and resolved world authority, and `authorized_record_actions`
  drops the actions that caller does not hold (deny by default).

Pure and framework-free. It resolves nothing itself: callers pass the already-resolved
`WorldAuthority`, so there is exactly one resolver (`resolve_world_authority`) and the
portal never infers any of this from a role name or a category.
"""

from dataclasses import dataclass
from typing import Protocol

from .content_authoring import UPDATE
from .entity_lifecycle import (
    APPROVE,
    ARCHIVE,
    DELETE_DRAFT,
    PUBLISH,
    REJECT,
    RESTORE,
    RETURN_TO_DRAFT,
    SUBMIT_FOR_REVIEW,
    SUPERSEDE,
)
from .world_authority import (
    WORLD_CANON_EDIT,
    WORLD_CANON_READ_PRIVATE,
    WORLD_CANON_REVIEW,
    WorldAuthority,
)

# The campaign-originated records that live in world tables (D8: E2 item instances, E3
# player-character identity). A campaign GM who creates one must be able to finish it, so
# neither their authoring nor their lifecycle needs a world role.
CAMPAIGN_ORIGINATED_TYPES: frozenset[str] = frozenset({"player_character", "item_instance"})

# What each lifecycle action needs on the world (Q13): preparing and withdrawing a draft is
# editing; approving, rejecting, publishing, superseding, archiving and restoring change what
# every campaign on the world sees, so they are reviewing. Campaign `canon.edit` is required in
# addition, as for every authoring write.
LIFECYCLE_ACTION_CAPABILITIES: dict[str, str] = {
    SUBMIT_FOR_REVIEW: WORLD_CANON_EDIT,
    RETURN_TO_DRAFT: WORLD_CANON_EDIT,
    DELETE_DRAFT: WORLD_CANON_EDIT,
    APPROVE: WORLD_CANON_REVIEW,
    REJECT: WORLD_CANON_REVIEW,
    PUBLISH: WORLD_CANON_REVIEW,
    SUPERSEDE: WORLD_CANON_REVIEW,
    ARCHIVE: WORLD_CANON_REVIEW,
    RESTORE: WORLD_CANON_REVIEW,
}

# The blocked-action entry that says the whole lifecycle does not apply to the record (an entity
# type that is not lifecycle-managed). It is informational, not an action anyone holds.
ALL_ACTIONS = "all"

# Everything a record can offer: the lifecycle actions plus editing its content.
RECORD_ACTION_CAPABILITIES: dict[str, str] = {
    **LIFECYCLE_ACTION_CAPABILITIES,
    UPDATE: WORLD_CANON_EDIT,
}


def is_campaign_originated(entity_type_code: str) -> bool:
    return entity_type_code in CAMPAIGN_ORIGINATED_TYPES


def lifecycle_world_capability(entity_type_code: str, action: str) -> str | None:
    """The world capability `action` needs on a record of `entity_type_code`, or `None` for
    the campaign-originated exceptions. Raises `KeyError` for an unknown action (callers
    pass the closed vocabulary above)."""
    if is_campaign_originated(entity_type_code):
        return None
    return LIFECYCLE_ACTION_CAPABILITIES[action]


@dataclass(frozen=True)
class RecordAuthoring:
    """What one caller may do to one record, as the server resolved it.

    `can_read_private` is the private side of the definition (drafts, GM-only preparation,
    revisions, provenance, sources, the review queue); `can_edit` is writing the definition;
    `can_review` is moving it through review, publication and archive. All three also require
    the caller's campaign `canon.edit`, because authoring routes are campaign-scoped.
    `campaign_originated` says the record is one of the exceptions, so the portal explains and
    links it as a campaign record without knowing which categories those are.

    These are eligibility previews for presentation. The command or endpoint re-checks under its
    own lock; a flag here never authorizes anything."""

    campaign_originated: bool
    can_read_private: bool
    can_edit: bool
    can_review: bool

    def as_json(self) -> dict[str, bool]:
        return {
            "campaign_originated": self.campaign_originated,
            "can_read_private": self.can_read_private,
            "can_edit": self.can_edit,
            "can_review": self.can_review,
        }

    def holds(self, action: str) -> bool:
        needed = RECORD_ACTION_CAPABILITIES.get(action)
        if needed is None:
            return False
        if needed == WORLD_CANON_EDIT:
            return self.can_edit
        return self.can_review


NO_AUTHORING = RecordAuthoring(
    campaign_originated=False, can_read_private=False, can_edit=False, can_review=False
)


def record_authoring(
    *, entity_type_code: str, has_campaign_canon_edit: bool, authority: WorldAuthority | None
) -> RecordAuthoring:
    """Resolve one caller's eligibility for one record. A caller without campaign `canon.edit`
    holds nothing here whatever their world roles are (a world Editor who is only a Player in
    this campaign cannot author through it)."""
    originated = is_campaign_originated(entity_type_code)
    if not has_campaign_canon_edit:
        return RecordAuthoring(
            campaign_originated=originated,
            can_read_private=False,
            can_edit=False,
            can_review=False,
        )

    def holds(capability: str) -> bool:
        return originated or (authority is not None and authority.has_capability(capability))

    return RecordAuthoring(
        campaign_originated=originated,
        can_read_private=holds(WORLD_CANON_READ_PRIVATE),
        can_edit=holds(WORLD_CANON_EDIT),
        can_review=holds(WORLD_CANON_REVIEW),
    )


class _HasAction(Protocol):
    @property
    def action(self) -> str: ...


def authorized_record_actions[B: _HasAction](
    available: list[str], blocked: list[B], *, authoring: RecordAuthoring
) -> tuple[list[str], list[B]]:
    """Keep only the actions this caller holds, from both `available_actions` and
    `blocked_actions`: a Reviewer is not "blocked" from editing, the action simply is not
    theirs. An action outside the vocabulary is dropped (deny by default)."""
    return (
        [action for action in available if authoring.holds(action)],
        [item for item in blocked if item.action == ALL_ACTIONS or authoring.holds(item.action)],
    )
