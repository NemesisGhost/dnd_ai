"""Building blocks for R01 requirements whose refusal depends on the snapshot (plan section 6.2).

`Requirement.refusal` takes no argument, because most early checks raise one fixed error. Some early
checks raise a different error depending on *what* failed (the D8 edit rule is 403 for a caller who can
still read, 404 for anyone else; the route capability is 404 for no access and 403 for a missing
capability). `judged_requirement` builds a `Requirement` from one `decide(snapshot)` function that
returns the exact exception the early check would raise, or `None` when the decision holds. The plan
judges `predicate` and then calls `refusal()` immediately on a failure, so the refusal is always the one
derived from the snapshot the predicate saw; the two never disagree.

A requirement is built per request and is not shared between threads.
"""

import uuid
from collections.abc import Callable

from .access import AuthoritySnapshot
from .authorization import Requirement


class _Judgement:
    """One requirement's decision and the verdict of its last evaluation. A class rather than a closure
    so the decision is called as an attribute, which the R01 route manifest's tracer reads as a method
    call and not as an unresolved bare name."""

    __slots__ = ("_decide", "_verdict")

    def __init__(self, decide: Callable[[AuthoritySnapshot], BaseException | None]) -> None:
        self._decide = decide
        self._verdict: BaseException | None = None

    def predicate(self, snapshot: AuthoritySnapshot) -> bool:
        self._verdict = self._decide(snapshot)
        return self._verdict is None

    def refusal(self) -> BaseException:
        if (
            self._verdict is None
        ):  # unreachable through the plan: `refusal` follows a failed predicate
            raise RuntimeError("a requirement was refused without a failed decision")
        return self._verdict


def judged_requirement(
    name: str,
    decide: Callable[[AuthoritySnapshot], BaseException | None],
    *,
    world_id: uuid.UUID | None = None,
    reveal: bool = False,
) -> Requirement:
    """A requirement that holds when `decide(snapshot)` is `None` and otherwise refuses with the
    exception `decide` returned. `world_id` and `reveal` declare the extra sources `decide` reads."""
    judgement = _Judgement(decide)
    return Requirement(
        name=name,
        predicate=judgement.predicate,
        refusal=judgement.refusal,
        world_id=world_id,
        reveal=reveal,
    )
