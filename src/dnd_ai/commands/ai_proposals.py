"""ReviewProposedChange and ApplyApprovedProposal — the human-review half of
the Generated -> Proposed -> Validated -> Approved -> Applied lifecycle
(docs/ENTITY_LIFECYCLE.md §10). `dnd_ai.commands.ai_npc` handles the
auto-approve path inline (a proposal never sits `pending` at all when
policy already cleared it); this module is only ever reached for a
`requires_approval` proposal.

`apply_approved_proposal()` deliberately dispatches on `proposal_kind` by an
explicit `if`, never a generic "call a function named by this string"
registry — the set of proposal kinds is small, closed, and owned entirely
by this codebase (docs/architecture/DATABASE_MODEL.md §18's own "policy
engine determines whether a proposal may be applied automatically" reads
naturally as a small, explicit decision table, not indirection over
arbitrary caller-supplied strings).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

from .knowledge import _reveal_knowledge_to_party_impl


class ProposedChangeNotFoundError(DomainAuthorizationError):
    """Raised for an `ai_proposed_change_id` that does not resolve to an
    existing `ai.proposed_changes` row. Fixed, non-disclosing 404 — a
    proposal can concern sensitive, not-yet-revealed knowledge, so its
    existence is not confirmed to an unauthorized caller (the API layer's
    own campaign-scoped capability check is what actually authorizes this;
    this error only covers "doesn't exist at all")."""


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
    connection: Connection, ai_proposed_change_id: uuid.UUID
) -> tuple[str, uuid.UUID, dict[str, object]]:
    row = connection.execute(
        text("""
            SELECT status, campaign_id, proposed_arguments
            FROM ai.proposed_changes
            WHERE ai_proposed_change_id = :id
            FOR UPDATE
        """),
        {"id": ai_proposed_change_id},
    ).one_or_none()
    if row is None:
        raise ProposedChangeNotFoundError(f"proposed change {ai_proposed_change_id} not found")
    if row.status != "pending":
        raise ProposedChangeNotPendingError()
    return row.status, row.campaign_id, row.proposed_arguments


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
    # pragma: no cover — proposal_kind is a closed database CHECK set; unreachable in practice.
    raise ValueError(
        f"unknown proposal_kind {proposal_kind!r} for proposal {ai_proposed_change_id}"
    )


def review_proposed_change(
    engine: Engine,
    *,
    ai_proposed_change_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    decision: str,
    comments: str | None = None,
) -> ReviewProposedChangeResult:
    """Record a human reviewer's decision on a `requires_approval`
    proposal, and apply it immediately if approved — atomically, one
    transaction. `decision` is `'approve'` or `'reject'`
    (`ai.change_reviews.decision`'s own CHECK)."""
    with engine.begin() as connection:
        _, campaign_id, proposed_arguments = _lock_pending_proposal(
            connection, ai_proposed_change_id
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
