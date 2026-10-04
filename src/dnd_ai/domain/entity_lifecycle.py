"""Shared canon-lifecycle policy for entity definitions (Phase 14).

Pure and framework-free. Two things live here, both consulted by the
lifecycle commands *and* by the read model that tells the portal which
buttons to render, so a preview can never drift from enforcement
(docs/PLAN.md Phase 14, decision D14):

1. **The eligibility registry.** Canon lifecycle applies to `core.entities`
   *definitions* only, and only to the entity types whose lifecycle is a pure
   definition lifecycle. Types with their own status machine, with
   authorization side effects, or with an unreviewed structural guard are
   excluded on purpose (each reason is recorded beside its code below).
   Adding a type is a reviewed change: it must also extend read-side
   visibility gating (`dnd_ai.queries.world_explorer`) to every surface the
   type appears on.

2. **The transition table** (docs/ENTITY_LIFECYCLE.md §3, with the D8
   archive/restore rules):

   ```text
   draft     --submit-->           proposed
   draft     --reject(abandon)-->  rejected
   proposed  --return_to_draft-->  draft
   proposed  --approve-->          approved
   proposed  --reject-->           rejected
   approved  --publish-->          canon
   approved  --return_to_draft-->  draft
   rejected  --return_to_draft-->  draft
   canon     --supersede-->        superseded   (replacement approved|canon)
   any except proposed/approved, lifecycle active  --archive-->  archived
   lifecycle archived  --restore-->  active (canon status unchanged)
   draft|rejected (unreferenced)  --delete_draft-->  physical delete
   ```

   `deprecated` has no transitions in Phase 14. Every transition other than
   restore and delete-draft additionally requires lifecycle `active`.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from .authoring import LifecycleNotSupportedError, LifecycleTransitionNotAllowedError

# --- Eligibility registry -----------------------------------------------------

# Pure definitions surfaced by the World Explorer, with no conflicting status
# machine and no authorization side effect from archiving.
ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES: frozenset[str] = frozenset(
    {
        # Places
        "location",
        "settlement",
        "building",
        "plane",
        "continent",
        "nation",
        "region",
        "district",
        "geographic_feature",
        "realm",
        # Organizations
        "organization",
        "business",
        "government",
        "religious_organization",
        "military_unit",
        "political_faction",
        # Beliefs
        "religion",
        # Characters (Phase 15.1 NPC identity; player characters stay excluded)
        "npc",
        # Narrative definitions (Phase 15.1; progress is timeline state, never here)
        "quest",
    }
)

# Deliberately excluded, each for a model reason (docs/PLAN.md Phase 14, D5).
ENTITY_LIFECYCLE_EXCLUDED_TYPE_CODES: dict[str, str] = {
    "character": "archiving revokes relationship-derived capabilities; PC identity is Phase 16 (an NPC archive is guarded instead)",
    "player_character": "PC identity and build approval are Phase 16",
    "event": "has its own draft/recorded/voided/corrected status machine (Phase 15E)",
    "knowledge_item": "truth/knowledge semantics (Phase 15E)",
    "item_instance": "instance/state/inventory semantics (Phase 15F)",
    "dungeon": "structural-mutation guards and discovery state (Phase 15A)",
    "dungeon_area": "structural-mutation guards and discovery state (Phase 15A)",
}


# Entity types that state-changing campaign commands may target only while the
# definition is published (`canon`) and operational (`active`). Phase 15.1 makes
# drafts routine, so a draft or archived definition must not become reachable
# through movement, reveal, advancement, transfer, or event participation. The
# lifecycle-eligible types are included (that now includes `npc` and `quest`);
# `knowledge_item` is included from the checkpoint that lets a GM create it.
STATE_TARGET_GUARDED_TYPE_CODES: frozenset[str] = frozenset(
    ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES | {"knowledge_item"}
)


def is_lifecycle_eligible(entity_type_code: str) -> bool:
    return entity_type_code in ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES


def require_lifecycle_eligible(entity_type_code: str) -> None:
    if not is_lifecycle_eligible(entity_type_code):
        raise LifecycleNotSupportedError(f"entity type {entity_type_code!r} is not eligible")


# --- Transition table ---------------------------------------------------------

SUBMIT_FOR_REVIEW = "submit_for_review"
RETURN_TO_DRAFT = "return_to_draft"
APPROVE = "approve"
REJECT = "reject"
PUBLISH = "publish"
SUPERSEDE = "supersede"
ARCHIVE = "archive"
RESTORE = "restore"
DELETE_DRAFT = "delete_draft"

ALL_ACTIONS: tuple[str, ...] = (
    SUBMIT_FOR_REVIEW,
    RETURN_TO_DRAFT,
    APPROVE,
    REJECT,
    PUBLISH,
    SUPERSEDE,
    ARCHIVE,
    RESTORE,
    DELETE_DRAFT,
)

CANON_DRAFT = "draft"
CANON_PROPOSED = "proposed"
CANON_APPROVED = "approved"
CANON_CANON = "canon"
CANON_SUPERSEDED = "superseded"
CANON_REJECTED = "rejected"

LIFECYCLE_ACTIVE = "active"
LIFECYCLE_ARCHIVED = "archived"

# action -> {from canon status: to canon status}
_CANON_TRANSITIONS: dict[str, dict[str, str]] = {
    SUBMIT_FOR_REVIEW: {CANON_DRAFT: CANON_PROPOSED},
    RETURN_TO_DRAFT: {
        CANON_PROPOSED: CANON_DRAFT,
        CANON_APPROVED: CANON_DRAFT,
        CANON_REJECTED: CANON_DRAFT,
    },
    APPROVE: {CANON_PROPOSED: CANON_APPROVED},
    REJECT: {CANON_DRAFT: CANON_REJECTED, CANON_PROPOSED: CANON_REJECTED},
    PUBLISH: {CANON_APPROVED: CANON_CANON},
    SUPERSEDE: {CANON_CANON: CANON_SUPERSEDED},
}

_ARCHIVE_BLOCKED_CANON_STATUSES = frozenset({CANON_PROPOSED, CANON_APPROVED})
_DELETABLE_CANON_STATUSES = frozenset({CANON_DRAFT, CANON_REJECTED})

# Closed set of reasons a blocked action may report.
BLOCKED_WRONG_CANON_STATUS = "wrong_canon_status"
BLOCKED_ENTITY_ARCHIVED = "entity_archived"
BLOCKED_ENTITY_NOT_ARCHIVED = "entity_not_archived"
BLOCKED_REVIEW_IN_PROGRESS = "review_in_progress"
BLOCKED_NOT_SUPPORTED = "lifecycle_not_supported"


@dataclass(frozen=True)
class BlockedAction:
    action: str
    reason: str


def target_canon_status(action: str, canon_status: str) -> str | None:
    """The canon status `action` produces from `canon_status`, or `None` when
    the action does not change canon status or is not legal from there."""
    return _CANON_TRANSITIONS.get(action, {}).get(canon_status)


def blocked_reason(action: str, canon_status: str, lifecycle_status: str) -> str | None:
    """Why `action` is not legal from this state, or `None` when it is."""
    if action == RESTORE:
        return None if lifecycle_status == LIFECYCLE_ARCHIVED else BLOCKED_ENTITY_NOT_ARCHIVED
    if action == DELETE_DRAFT:
        if lifecycle_status not in (LIFECYCLE_ACTIVE, LIFECYCLE_ARCHIVED):
            return BLOCKED_ENTITY_ARCHIVED
        return None if canon_status in _DELETABLE_CANON_STATUSES else BLOCKED_WRONG_CANON_STATUS
    if lifecycle_status != LIFECYCLE_ACTIVE:
        return BLOCKED_ENTITY_ARCHIVED
    if action == ARCHIVE:
        if canon_status in _ARCHIVE_BLOCKED_CANON_STATUSES:
            return BLOCKED_REVIEW_IN_PROGRESS
        return None
    if canon_status in _CANON_TRANSITIONS.get(action, {}):
        return None
    return BLOCKED_WRONG_CANON_STATUS


def require_transition(action: str, canon_status: str, lifecycle_status: str) -> None:
    """Raise `LifecycleTransitionNotAllowedError` unless `action` is legal
    from the given state. The reason is server-side detail only."""
    reason = blocked_reason(action, canon_status, lifecycle_status)
    if reason is not None:
        raise LifecycleTransitionNotAllowedError(
            f"{action} not allowed from canon={canon_status} lifecycle={lifecycle_status}: {reason}"
        )


def evaluate_actions(
    *,
    entity_type_code: str,
    canon_status: str,
    lifecycle_status: str,
    extra_blocked: Mapping[str, str] | None = None,
) -> tuple[list[str], list[BlockedAction]]:
    """`(available_actions, blocked_actions)` for the read model. Produced by
    the same `blocked_reason` the commands call, so a preview cannot disagree
    with enforcement. An ineligible type reports one blocked pseudo-action
    `all`. `extra_blocked` (action -> reason) carries type-specific blocks such
    as an unpublished parent blocking `publish`; it only ever blocks an action
    the state table already allows."""
    if not is_lifecycle_eligible(entity_type_code):
        return [], [BlockedAction(action="all", reason=BLOCKED_NOT_SUPPORTED)]
    available: list[str] = []
    blocked: list[BlockedAction] = []
    for action in ALL_ACTIONS:
        reason = blocked_reason(action, canon_status, lifecycle_status)
        if reason is None and extra_blocked and action in extra_blocked:
            reason = extra_blocked[action]
        if reason is None:
            available.append(action)
        else:
            blocked.append(BlockedAction(action=action, reason=reason))
    return available, blocked
