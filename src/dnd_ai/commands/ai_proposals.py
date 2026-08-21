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

`advance_quest_objective` additionally re-derives and re-checks, immediately
before dispatch and in the same transaction, every fact its own
`advanceable_objectives` candidate set (`dnd_ai.domain.context_assembly`)
was originally built from — never trusting `proposed_arguments` as
authoritative for anything current relational state can instead answer.
Between a proposal's creation and its review, arbitrary time can pass: the
NPC may stop participating in the quest, the objective's visibility may
narrow to `gm_only`, the party may leave the campaign, or (in a branching-
timeline world) the campaign's own pinned timeline may change. None of
those are caught by `_advance_objective_impl`'s own guards, which only
re-check the objective's terminal/non-terminal status — so
`_revalidate_advance_quest_objective` below reapplies the campaign/
timeline/party/quest-participation/visibility chain itself, failing the
whole review transaction closed (never partially) if anything no longer
holds. See that function's own docstring for the exact chain and why the
objective row is locked before any of it is read.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError
from dnd_ai.queries.quest import get_quest_view

from ._shared import validate_campaign_party as _validate_campaign_party
from .knowledge import _reveal_knowledge_to_party_impl
from .quests import _TERMINAL_OBJECTIVE_STATUSES, _advance_objective_impl


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
        args = _parse_advance_quest_objective_arguments(proposed_arguments)
        actor_entity_id = _revalidate_advance_quest_objective(
            connection,
            ai_proposed_change_id=ai_proposed_change_id,
            campaign_id=campaign_id,
            args=args,
        )
        objective_result = _advance_objective_impl(
            connection,
            quest_objective_id=args.quest_objective_id,
            timeline_id=args.timeline_id,
            world_time_id=args.world_time_id,
            new_status_code=args.new_status_code,
            party_id=args.party_id,
            actor_entity_id=actor_entity_id,
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


# The exact, closed set of keys dnd_ai.commands.ai_npc.request_npc_
# conversation_turn writes for an advance_quest_objective proposal — never
# a subset (a caller/tampered row missing one) or a superset (one carrying
# an extra key nothing here would ever read, which is exactly as suspect
# as a missing one for a payload only this codebase's own command layer
# ever writes).
_ADVANCE_QUEST_OBJECTIVE_KEYS = frozenset(
    {
        "quest_objective_id",
        "new_status_code",
        "party_id",
        "timeline_id",
        "world_time_id",
        "actor_entity_id",
    }
)
_ADVANCEABLE_STATUS_CODES = frozenset({"completed", "failed"})


@dataclass(frozen=True)
class _AdvanceQuestObjectiveArguments:
    """The strictly-typed result of parsing an advance_quest_objective
    proposal's stored `proposed_arguments` — see
    `_parse_advance_quest_objective_arguments`'s own docstring. Every
    field here is required and non-`None`; there is no optional field
    (unlike `_advance_objective_impl`'s own signature, which allows
    `party_id`/`actor_entity_id` to default to `None` for its other,
    human-driven callers) — a proposal drawn from `advanceable_objectives`
    always has a real party and NPC behind it, and party_id=None would
    silently widen `_advance_objective_impl`'s write from this specific
    party's own `campaign.objective_state` row to the campaign-wide one,
    a materially different scope this proposal was never checked
    against."""

    quest_objective_id: uuid.UUID
    new_status_code: str
    party_id: uuid.UUID
    timeline_id: uuid.UUID
    world_time_id: uuid.UUID
    actor_entity_id: uuid.UUID


def _parse_uuid_argument(proposed_arguments: Mapping[str, object], key: str) -> uuid.UUID:
    """A required `proposed_arguments` value that must parse as a UUID —
    `None` (a JSON `null`, e.g. a key present but unset) is rejected the
    same way any other malformed value is: `uuid.UUID(str(None))` raises
    `ValueError` on `"None"` not being a valid UUID string, so a `null`
    can never silently become Python `None` here the way `.get()` would
    let it."""
    value = _require_argument(proposed_arguments, key)
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"proposed_arguments[{key!r}] is not a valid UUID: {value!r}") from exc


def _parse_advance_quest_objective_arguments(
    proposed_arguments: Mapping[str, object],
) -> _AdvanceQuestObjectiveArguments:
    """Strict, exact-shape parse of an advance_quest_objective proposal's
    stored arguments — the only place this JSONB payload is trusted to
    have a specific shape at all. Requires exactly the keys in
    `_ADVANCE_QUEST_OBJECTIVE_KEYS`: a missing key and an unexpected extra
    key are both rejected, not just a missing one, since nothing about a
    payload this codebase's own command layer wrote should ever carry an
    extra field to begin with (a tampered row or a future upstream bug
    are exactly the cases worth failing loudly on, not silently
    ignoring). `new_status_code` is restricted to `_ADVANCEABLE_STATUS_
    CODES` here too — `_advance_objective_impl` re-checks this itself,
    but failing before any lock is taken or any row is touched is
    strictly better than relying on that second check alone."""
    actual_keys = set(proposed_arguments)
    if actual_keys != _ADVANCE_QUEST_OBJECTIVE_KEYS:
        missing = _ADVANCE_QUEST_OBJECTIVE_KEYS - actual_keys
        unexpected = actual_keys - _ADVANCE_QUEST_OBJECTIVE_KEYS
        detail = "; ".join(
            part
            for part in (
                f"missing {sorted(missing)}" if missing else "",
                f"unexpected {sorted(unexpected)}" if unexpected else "",
            )
            if part
        )
        raise ValueError(
            "advance_quest_objective proposed_arguments must contain exactly "
            f"{sorted(_ADVANCE_QUEST_OBJECTIVE_KEYS)} ({detail})"
        )

    new_status_code = str(proposed_arguments["new_status_code"])
    if new_status_code not in _ADVANCEABLE_STATUS_CODES:
        raise ValueError(
            f"new_status_code must be one of {sorted(_ADVANCEABLE_STATUS_CODES)}, "
            f"got {new_status_code!r}"
        )

    return _AdvanceQuestObjectiveArguments(
        quest_objective_id=_parse_uuid_argument(proposed_arguments, "quest_objective_id"),
        new_status_code=new_status_code,
        party_id=_parse_uuid_argument(proposed_arguments, "party_id"),
        timeline_id=_parse_uuid_argument(proposed_arguments, "timeline_id"),
        world_time_id=_parse_uuid_argument(proposed_arguments, "world_time_id"),
        actor_entity_id=_parse_uuid_argument(proposed_arguments, "actor_entity_id"),
    )


def _revalidate_advance_quest_objective(
    connection: Connection,
    *,
    ai_proposed_change_id: uuid.UUID,
    campaign_id: uuid.UUID,
    args: _AdvanceQuestObjectiveArguments,
) -> uuid.UUID:
    """Immediately before dispatching to `_advance_objective_impl`, in the
    same transaction as the review decision itself, re-derives and
    re-checks every fact `advanceable_objectives` (`dnd_ai.domain.
    context_assembly`) was originally built from — never trusting
    `proposed_arguments` as authoritative for anything current relational
    state can instead answer. Any failure here raises a generic
    `ValueError` (or, for a cross-world quest, `dnd_ai.queries.quest.
    QuestNotFoundError`, itself a non-disclosing `DomainAuthorizationError`
    — `get_quest_view`'s own contract) — never text describing which
    specific check failed or any attribute of a foreign resource, so a
    proposal engineered to probe another campaign/quest/party's existence
    learns nothing beyond "this proposal can no longer be applied." Since
    this runs inside `review_proposed_change`'s own transaction, any
    exception here rolls back the whole review — the `ai.change_reviews`
    insert included — exactly like `_advance_objective_impl`'s own
    "already terminal" guard already does.

    Checks, in order:
    1. The proposal's own audit chain (`ai.proposed_changes ->
       .generated_outputs -> .context_requests -> .agent_assignments`)
       resolves to an assignment in this same campaign, with a real NPC
       entity — the source of truth for "who is speaking," never
       `proposed_arguments['actor_entity_id']` (still required and
       UUID-validated above, but its *value* is never used for the
       actual call below).
    2. `args.timeline_id` still matches the campaign's own currently
       pinned timeline (`campaign.campaigns.timeline_id`) — a campaign's
       pinned timeline can change (e.g. a branch becomes the new active
       play timeline); a proposal created against a timeline the
       campaign has since moved off of must not silently apply against
       stale timeline-scoped state.
    3. `args.party_id` still belongs to `campaign_id`
       (`_validate_campaign_party` — the same check `_advance_objective_
       impl` itself applies, run here too so a failure here never even
       reaches locking the objective row for a party that has already
       left).
    4. The objective row is locked (`FOR UPDATE`) before anything about
       it is read — the same row `_advance_objective_impl`'s own
       `_lock_quest_objective` locks before touching `campaign.
       objective_state` (a lock already held by this same transaction is
       a no-op to re-acquire, per PostgreSQL's own reentrant-lock
       semantics), so a concurrent change to *this row's own columns*
       (`visibility_policy`) between this check and `_advance_objective_
       impl`'s later re-acquisition of the identical lock cannot leave a
       window where this function's own read is already stale by the
       time the objective is actually advanced.
    5. The NPC (from the audit chain, not the JSON) still participates
       in the locked objective's owning quest
       (`narrative.quest_participants`) — participation can be revoked
       independently of anything else checked here.
    6. `get_quest_view(..., party_id=args.party_id, include_hidden=False)`
       — the exact same party-scoped, non-GM query `dnd_ai.domain.
       context_assembly._advanceable_objectives` used to build the
       original candidate set — still lists this objective, with a
       still-non-terminal status. Reusing this query (rather than
       re-deriving visibility here) is what guarantees this recheck can
       never drift from what the original candidate set itself meant by
       "eligible": a `'gm_only'` objective, one hidden from this party,
       or one that has gone terminal are all excluded identically,
       whether checked at proposal-creation time or here.

    Returns the audit-chain-derived NPC `entity_id` — the actor
    `_advance_objective_impl` records for the resulting event.
    """
    chain = connection.execute(
        text("""
            SELECT aa.campaign_id AS assignment_campaign_id, aa.entity_id AS npc_entity_id
            FROM ai.proposed_changes pc
            JOIN ai.generated_outputs go ON go.generated_output_id = pc.generated_output_id
            JOIN ai.context_requests cr ON cr.context_request_id = go.context_request_id
            JOIN ai.agent_assignments aa ON aa.agent_assignment_id = cr.agent_assignment_id
            WHERE pc.ai_proposed_change_id = :proposal
        """),
        {"proposal": ai_proposed_change_id},
    ).one_or_none()
    if chain is None or chain.assignment_campaign_id != campaign_id or chain.npc_entity_id is None:
        raise ValueError(
            f"proposal {ai_proposed_change_id} does not resolve to a same-campaign agent "
            "assignment with an NPC entity"
        )
    npc_entity_id = chain.npc_entity_id
    assert isinstance(npc_entity_id, uuid.UUID)

    campaign_timeline_id = connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :campaign"),
        {"campaign": campaign_id},
    ).scalar()
    if campaign_timeline_id != args.timeline_id:
        raise ValueError(
            f"proposal {ai_proposed_change_id}'s stored timeline no longer matches campaign "
            f"{campaign_id}'s current pinned timeline"
        )

    _validate_campaign_party(connection, campaign_id=campaign_id, party_id=args.party_id)

    quest_row = connection.execute(
        text("""
            SELECT qs.quest_id
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            WHERE qo.quest_objective_id = :objective
            FOR UPDATE OF qo
        """),
        {"objective": args.quest_objective_id},
    ).one_or_none()
    if quest_row is None:
        raise ValueError(
            f"proposal {ai_proposed_change_id} names an objective that no longer exists"
        )
    quest_id = quest_row.quest_id
    assert isinstance(quest_id, uuid.UUID)

    still_participates = connection.execute(
        text("""
            SELECT 1 FROM narrative.quest_participants
            WHERE quest_id = :quest AND participant_entity_id = :npc
        """),
        {"quest": quest_id, "npc": npc_entity_id},
    ).scalar()
    if still_participates is None:
        raise ValueError(
            f"proposal {ai_proposed_change_id}'s NPC no longer participates in the objective's quest"
        )

    expected_world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :timeline"),
        {"timeline": campaign_timeline_id},
    ).scalar()
    if expected_world_id is None:
        raise ValueError(f"proposal {ai_proposed_change_id}'s campaign has no resolvable world")

    quest_view = get_quest_view(
        connection,
        quest_id=quest_id,
        timeline_id=args.timeline_id,
        expected_world_id=expected_world_id,
        party_id=args.party_id,
        include_hidden=False,
    )
    still_eligible = any(
        objective.quest_objective_id == args.quest_objective_id
        and objective.status_code not in _TERMINAL_OBJECTIVE_STATUSES
        for stage in quest_view.stages
        for objective in stage.objectives
    )
    if not still_eligible:
        raise ValueError(
            f"proposal {ai_proposed_change_id}'s objective is no longer an eligible, "
            "party-visible, non-terminal candidate"
        )

    return npc_entity_id


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
