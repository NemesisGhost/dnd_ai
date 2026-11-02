"""Effective-time party membership (B1-DEF7a): the one clock and the one predicate.

A `campaign.party_memberships` row is *current* when the timeline's effective campaign clock lies
in its stored half-open `effective_period` (`[join, leave)`): the join boundary is included, the
leave boundary is excluded, a future open-ended join is not current, and a finite interval that
contains the clock is. It is never "the end is absent" — that is only the storage representation of
an open interval (migration 009; ADR 0010).

With no effective clock (a root timeline with no `campaign.timeline_clocks` row) current
membership is *undetermined*: nothing is current, ended or upcoming, and nothing that is derived
from current membership is granted. There is no fallback to open-ended membership.

Membership rows stay timeline-scoped. A branch inherits its parent's *clock* (bounded at the branch
point, `resolve_effective_clock`), not its parent's membership rows.

The status is computed at read time and never stored or cached across requests: each request (each
campaign, in the session bootstrap) resolves one `MembershipClock` and every membership decision in
it uses that value, so lists, counts, details and authorization agree. As-of / historical reads
keep their own requested time and do not use this module.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection

from dnd_ai.domain.relationship_authoring import relationship_period_status

from .campaign_clock import resolve_effective_clock


@dataclass(frozen=True)
class MembershipClock:
    sort_key: int | None  # None = no effective clock (current membership is undetermined)
    display: str | None  # the clock reading for `as_of`; None when unset

    @property
    def is_set(self) -> bool:
        return self.sort_key is not None


def resolve_membership_clock(connection: Connection, *, timeline_id: uuid.UUID) -> MembershipClock:
    """The only place the clock is read for membership decisions. Same resolver the relationship
    and organization rosters use, including the bounded branch fallback."""
    clock = resolve_effective_clock(connection, timeline_id=timeline_id)
    if clock is None:
        return MembershipClock(sort_key=None, display=None)
    return MembershipClock(sort_key=clock.sort_key, display=clock.display)


# The one SQL predicate, over `campaign.party_memberships` aliased `pm`. Bind the clock's key as
# `:membership_clock_key` (NULL when unset, which makes the predicate false).
CURRENT_PARTY_MEMBERSHIP_SQL = (
    "(CAST(:membership_clock_key AS bigint) IS NOT NULL "
    "AND pm.effective_period @> CAST(:membership_clock_key AS bigint))"
)


def membership_clock_params(clock: MembershipClock) -> dict[str, object]:
    return {"membership_clock_key": clock.sort_key}


def membership_period_status(start_key: int, end_key: int | None, clock: MembershipClock) -> str:
    """`in_effect`, `not_started`, `ended`, or `clock_unset` (undetermined) — the shared
    relationship vocabulary and half-open rule. `end_key` is `upper(effective_period)`, NULL for an
    open end. The lower bound is never NULL, so `undated` cannot occur."""
    return relationship_period_status(start_key, end_key, clock.sort_key)
