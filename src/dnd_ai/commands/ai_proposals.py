"""ReviewProposedChange and ApplyApprovedProposal — the human-review half of
the Generated -> Proposed -> Validated -> Approved -> Applied lifecycle
(docs/ENTITY_LIFECYCLE.md §10). `dnd_ai.commands.ai_npc` handles the
auto-approve path inline (a proposal never sits `pending` at all when
policy already cleared it); this module is reached for every
`requires_approval` proposal, plus the auto-approve path's own apply step
(both call `_apply_proposal` directly, on the same open transaction).

`_apply_proposal()` deliberately dispatches on `proposal_kind` by an
explicit `if`/`elif` chain, never a generic "call a function named by this
string" registry — the set of proposal kinds is small, closed, and owned
entirely by this codebase (docs/architecture/DATABASE_MODEL.md §18's own
"policy engine determines whether a proposal may be applied automatically"
reads naturally as a small, explicit decision table, not indirection over
arbitrary caller-supplied strings). Two kinds are wired today:
`reveal_knowledge` (`dnd_ai.commands.knowledge.reveal_knowledge_to_party`)
and `advance_quest_objective` (`dnd_ai.commands.quests._advance_objective_
impl`) — both existing canonical commands, never a duplicate mutation path
written for this module. Each branch re-parses `proposed_arguments` (a
`Mapping[str, object]` read back from JSONB) into that command's own typed
keyword arguments, raising `ValueError` for a missing or malformed key
(`_apply_proposal` runs inside the caller's own transaction — see
`review_proposed_change` below — so that `ValueError` rolls the whole
review-and-apply transaction back, never leaving a proposal half-applied).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

from .knowledge import _reveal_knowledge_to_party_impl
from .quests import _advance_objective_impl


class ProposedChangeNotFoundError(DomainAuthorizationError):
    """Raised for an `ai_proposed_change_id` that does not resolve to an
    existing `ai.proposed_changes` row belonging exactly to the caller's
    own `campaign_id` — including a nonexistent proposal and one belonging
    to a different campaign, identically (the same `SessionNotInCampaignError`/
    `PartyNotInCampaignError` reasoning `dnd_ai.commands._shared` already
    documents: a caller-supplied resource id is never trusted on its own,
    even after the API layer's own campaign-scoped `canon.edit` check —
    without this, a GM of one campaign could review/apply a pending
    proposal belonging to a campaign they hold no capability in at all,
    simply by guessing or observing another campaign's `ai_proposed_
    change_id`). Fixed, non-disclosing 404 — a proposal can concern
    sensitive, not-yet-revealed knowledge, so its existence is not
    confirmed to an unauthorized caller. The supplied ids are included
    only in the constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


class ProposedChangeNotPendingError(SafeMessageError):
    """Raised when `review_proposed_change()` is called against a proposal
    whose `status` is not `'pending'` — already decided, applied, or
    withdrawn. A proposal is reviewed exactly once."""

    safe_status_code = 409
    safe_error_code = "proposed_change_not_pending"
    safe_message = "This proposed change has already been decided."


@dataclass(frozen=True)
class ReviewProposedChangeResult:
    ai_change_review_id: uuid.UUID
    status: str
    applied_event_id: uuid.UUID | None


def _lock_pending_proposal(
    connection: Connection, *, ai_proposed_change_id: uuid.UUID, campaign_id: uuid.UUID
) -> tuple[str, dict[str, object]]:
    row = connection.execute(
        text("""
            SELECT status, campaign_id, proposed_arguments
            FROM ai.proposed_changes
            WHERE ai_proposed_change_id = :id
            FOR UPDATE
        """),
        {"id": ai_proposed_change_id},
    ).one_or_none()
    if row is None or row.campaign_id != campaign_id:
        raise ProposedChangeNotFoundError(
            f"proposed change {ai_proposed_change_id} not found for campaign {campaign_id} "
            f"(actual campaign: {row.campaign_id if row is not None else None})"
        )
    if row.status != "pending":
        raise ProposedChangeNotPendingError()
    return row.status, row.proposed_arguments


def _apply_proposal(
    connection: Connection,
    *,
    ai_proposed_change_id: uuid.UUID,
    proposal_kind: str,
    proposed_arguments: Mapping[str, object],
    campaign_id: uuid.UUID,
) -> uuid.UUID:
    """Dispatch an approved (or auto-approved) proposal to its target
    domain command, on the caller's own connection/transaction — the
    "applying a proposal uses the same domain command path as human-
    authored changes" rule (docs/ENTITY_LIFECYCLE.md §10). Returns the
    resulting `narrative.events.event_id`."""
    if proposal_kind == "reveal_knowledge":
        result = _reveal_knowledge_to_party_impl(
            connection,
            knowledge_item_id=uuid.UUID(str(proposed_arguments["knowledge_item_id"])),
            party_id=uuid.UUID(str(proposed_arguments["party_id"])),
            timeline_id=uuid.UUID(str(proposed_arguments["timeline_id"])),
            world_time_id=uuid.UUID(str(proposed_arguments["world_time_id"])),
            campaign_id=campaign_id,
        )
        if result.event_id is None:
            # Already known by the time this proposal was applied (e.g. a
            # second, independent path revealed it first) — the proposal
            # still resolves to 'applied' with no new event, matching
            # reveal_knowledge_to_party's own idempotency contract; there
            # is nothing unsafe about approving a proposal that turns out
            # to be a no-op.
            existing_event_id = connection.execute(
                text(
                    "SELECT last_event_id FROM campaign.party_knowledge "
                    "WHERE party_knowledge_id = :id"
                ),
                {"id": result.party_knowledge_id},
            ).scalar()
            assert isinstance(existing_event_id, uuid.UUID)
            return existing_event_id
        return result.event_id
    if proposal_kind == "advance_quest_objective":
        objective_result = _advance_objective_impl(
            connection,
            quest_objective_id=uuid.UUID(
                str(_require_argument(proposed_arguments, "quest_objective_id"))
            ),
            timeline_id=uuid.UUID(str(_require_argument(proposed_arguments, "timeline_id"))),
            world_time_id=uuid.UUID(str(_require_argument(proposed_arguments, "world_time_id"))),
            new_status_code=str(_require_argument(proposed_arguments, "new_status_code")),
            party_id=_optional_uuid_argument(proposed_arguments, "party_id"),
            actor_entity_id=_optional_uuid_argument(proposed_arguments, "actor_entity_id"),
            campaign_id=campaign_id,
        )
        return objective_result.event_id
    # The database CHECK constraint on ai.proposed_changes.proposal_kind
    # closes this vocabulary — this is defense in depth, not a path any
    # currently-committed row can reach, since every value the constraint
    # allows has a branch above.
    raise ValueError(
        f"unknown proposal_kind {proposal_kind!r} for proposal {ai_proposed_change_id}"
    )


def _require_argument(proposed_arguments: Mapping[str, object], key: str) -> object:
    """A `proposed_arguments` value that must be present — raises
    `ValueError` (not `KeyError`) for a missing key, so a malformed or
    tampered-with proposal row fails the same "unclassified domain
    ValueError -> 400, transaction rolled back" way every other invalid
    request does (`dnd_ai.api.errors.handle_value_error`), rather than an
    unclassified `KeyError` falling through to the generic 500 handler."""
    if key not in proposed_arguments:
        raise ValueError(f"proposed_arguments is missing required key {key!r}")
    return proposed_arguments[key]


def _optional_uuid_argument(proposed_arguments: Mapping[str, object], key: str) -> uuid.UUID | None:
    value = proposed_arguments.get(key)
    if value is None:
        return None
    return uuid.UUID(str(value))


def review_proposed_change(
    engine: Engine,
    *,
    ai_proposed_change_id: uuid.UUID,
    campaign_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    decision: str,
    comments: str | None = None,
) -> ReviewProposedChangeResult:
    """Record a human reviewer's decision on a `requires_approval`
    proposal, and apply it immediately if approved — atomically, one
    transaction. `decision` is `'approve'` or `'reject'`
    (`ai.change_reviews.decision`'s own CHECK). `campaign_id` is always the
    caller's own already-authorized campaign (the API layer's URL path,
    never trusted from the proposal row alone) — see
    `ProposedChangeNotFoundError`'s own docstring for why."""
    with engine.begin() as connection:
        _, proposed_arguments = _lock_pending_proposal(
            connection, ai_proposed_change_id=ai_proposed_change_id, campaign_id=campaign_id
        )

        proposal_kind = connection.execute(
            text("SELECT proposal_kind FROM ai.proposed_changes WHERE ai_proposed_change_id = :id"),
            {"id": ai_proposed_change_id},
        ).scalar()
        assert isinstance(proposal_kind, str)

        review_id = connection.execute(
            text("""
                INSERT INTO ai.change_reviews
                    (ai_proposed_change_id, reviewer_user_id, decision, comments)
                VALUES (:proposal, :reviewer, :decision, :comments)
                RETURNING ai_change_review_id
            """),
            {
                "proposal": ai_proposed_change_id,
                "reviewer": reviewer_user_id,
                "decision": decision,
                "comments": comments,
            },
        ).scalar()
        assert isinstance(review_id, uuid.UUID)

        if decision == "reject":
            connection.execute(
                text("""
                    UPDATE ai.proposed_changes
                    SET status = 'rejected', decided_by_user_id = :reviewer, decided_at = now()
                    WHERE ai_proposed_change_id = :id
                """),
                {"reviewer": reviewer_user_id, "id": ai_proposed_change_id},
            )
            return ReviewProposedChangeResult(
                ai_change_review_id=review_id, status="rejected", applied_event_id=None
            )

        applied_event_id = _apply_proposal(
            connection,
            ai_proposed_change_id=ai_proposed_change_id,
            proposal_kind=proposal_kind,
            proposed_arguments=proposed_arguments,
            campaign_id=campaign_id,
        )
        connection.execute(
            text("""
                UPDATE ai.proposed_changes
                SET status = 'applied', decided_by_user_id = :reviewer, decided_at = now(),
                    applied_event_id = :event
                WHERE ai_proposed_change_id = :id
            """),
            {"reviewer": reviewer_user_id, "event": applied_event_id, "id": ai_proposed_change_id},
        )
        return ReviewProposedChangeResult(
            ai_change_review_id=review_id, status="applied", applied_event_id=applied_event_id
        )
