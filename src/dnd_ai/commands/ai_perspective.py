"""R01 E2: what the two AI engine commands share about authorization (design 3.1, 5 and 13.3).

Each of the two commands (`ai_npc`, `ai_synthesis`) runs two engine transactions, T1 (the context, committed
before the provider is called) and T2 (the output). Each opens its own `authorized_transaction`, so each is
judged by its own post-write final check:

- the command is handed a **factory** (`requirements`) and calls it once per transaction, so no `Requirement`
  (and no verdict it holds) is ever reused by another transaction;
- the factory must return something: `AuthorizationPlan.finalize` on a plan with no requirement silently
  passes, so an empty factory is refused before any statement (`register_requirements`);
- the party perspective is read twice inside the transaction that judges it: early (`read_perspective_facts`, so the
  domain refusal precedes any disclosure and the refusal order is unchanged) and by the final statement itself, which
  evaluates the campaign-party association and the membership at the campaign clock in the same statement and MVCC
  snapshot as the capability checks (R01 E2 correction C-1). The final decision uses only the snapshot's values.

Only identifiers cross a transaction boundary.
"""

import uuid
from collections.abc import Callable, Sequence

from sqlalchemy import Connection

from dnd_ai.domain.access import AuthoritySnapshot
from dnd_ai.domain.authorization import AuthorizationPlan, Requirement
from dnd_ai.domain.authorization_requirements import judged_requirement
from dnd_ai.domain.errors import DomainAuthorizationError
from dnd_ai.queries.party_membership_period import PerspectiveFacts, read_perspective_facts

#: The perspective's own capability: the rule's default (`resolve_party_perspective`), never `character.interact`.
PERSPECTIVE_CAPABILITY = "character.view_knowledge"

RequirementFactory = Callable[[], Sequence[Requirement]]


class PartyPerspectiveRefusedError(DomainAuthorizationError):
    """A party perspective that is not proved: a missing `character.view_knowledge` for the character, a party
    outside the campaign, or a character not currently a member (no effective clock included). One
    non-disclosing 404, the same response `PartyPerspectiveNotAuthorizedError` gives."""


def register_requirements(
    connection: Connection, plan: AuthorizationPlan, requirements: RequirementFactory
) -> None:
    """Register a fresh set of requirements on this transaction's plan. An empty set would let `finalize` pass
    without judging anything, so it is refused before any statement."""
    fresh = tuple(requirements())
    if not fresh:
        raise ValueError("an engine transaction needs at least one authorization requirement")
    for requirement in fresh:
        plan.require(connection, requirement)


def perspective_facts_or_refuse(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    party_id: uuid.UUID,
) -> PerspectiveFacts:
    """Read the facts and refuse (404) when they do not hold. Called before the context is assembled or the
    output is written, so a refused perspective discloses and persists nothing."""
    facts = read_perspective_facts(
        connection,
        campaign_id=campaign_id,
        timeline_id=timeline_id,
        character_id=character_id,
        party_id=party_id,
    )
    if not (facts.party_in_campaign and facts.member_now):
        raise PartyPerspectiveRefusedError(
            f"party {party_id} is not an authorized perspective for character {character_id}"
        )
    return facts


def party_perspective_requirement(
    *, name: str, character_id: uuid.UUID, party_id: uuid.UUID
) -> Requirement:
    """The perspective as a requirement of the final check (decision G-2: no `canon.edit` bypass). The requirement
    declares the party and the character as inputs of the final statement, which evaluates in that one statement and
    MVCC snapshot: the caller's capabilities, the campaign-party association and the membership at the campaign
    clock (R01 E2 correction C-1). It holds only when the snapshot gives the caller `character.view_knowledge` for the
    character and both facts are true. A refusal is the early refusal."""

    def decide(snapshot: AuthoritySnapshot) -> BaseException | None:
        access = snapshot.access
        facts = snapshot.perspective
        if (
            access is None
            or facts is None
            or not access.has_capability(PERSPECTIVE_CAPABILITY, character_id=character_id)
            or not facts.party_in_campaign
            or not facts.member_now
        ):
            return PartyPerspectiveRefusedError("party perspective not authorized")
        return None

    return judged_requirement(name, decide, perspective=(party_id, character_id))


def register_perspective(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    name: str,
    character_id: uuid.UUID,
    party_id: uuid.UUID,
) -> None:
    """Register the perspective requirement on this transaction's plan (after the route requirements, so the
    refusal order is the early one). Its facts are read by the final statement, never by an earlier read."""
    plan.require(
        connection,
        party_perspective_requirement(name=name, character_id=character_id, party_id=party_id),
    )
