"""Quest runtime policy (Phase 15 checkpoint 15.2E-2b, decision D-16).

Quest and objective progress is timeline state. Under D-16 (option a) only explicit GM
commands change it: nothing cascades, so finishing every required objective does not
complete the quest; the read model says "all required objectives are complete" and the
GM decides. Every change records one causal event and the matching effect, atomically.

A quest moves between `active`, `suspended` and the terminal `completed`, `failed` and
`abandoned`; a quest with no state row (or `available` / `unavailable`) is activated. An
objective moves from unseen or `hidden` through `available` and `active` to the terminal
`completed`, `failed` or `skipped`. The caller names the status it saw
(`expected_status`), which is the optimistic token: a quest that moved meanwhile is a
stale write.
"""

from .errors import SafeMessageError

# action -> (statuses it may start from, the status it ends in, the event type recorded)
# `None` stands for "no state row yet".
QUEST_ACTIONS: dict[str, tuple[frozenset[str | None], str, str]] = {
    "activate": (frozenset({None, "unavailable", "available"}), "active", "quest_activated"),
    "complete": (frozenset({"active"}), "completed", "quest_completed"),
    "fail": (frozenset({"active"}), "failed", "quest_failed"),
    "suspend": (frozenset({"active"}), "suspended", "quest_suspended"),
    "resume": (frozenset({"suspended"}), "active", "quest_resumed"),
    "abandon": (frozenset({"active", "suspended"}), "abandoned", "quest_abandoned"),
}

QUEST_TERMINAL = frozenset({"completed", "failed", "abandoned"})

_OPEN_OBJECTIVE = frozenset({None, "hidden", "available", "active"})

# new status -> (statuses it may start from, the event type recorded)
OBJECTIVE_TARGETS: dict[str, tuple[frozenset[str | None], str]] = {
    "available": (frozenset({None, "hidden"}), "objective_activated"),
    "active": (frozenset({None, "hidden", "available"}), "objective_activated"),
    "completed": (_OPEN_OBJECTIVE, "objective_completed"),
    "failed": (_OPEN_OBJECTIVE, "objective_failed"),
    "skipped": (_OPEN_OBJECTIVE, "objective_skipped"),
}

OBJECTIVE_TERMINAL = frozenset({"completed", "failed", "skipped", "superseded"})


def quest_actions_from(status: str | None) -> list[str]:
    """The quest actions the GM may take from `status`, in the table's order."""
    return [action for action, (starts, _, _) in QUEST_ACTIONS.items() if status in starts]


def objective_targets_from(status: str | None) -> list[str]:
    """The statuses an objective may move to from `status`."""
    return [target for target, (starts, _) in OBJECTIVE_TARGETS.items() if status in starts]


class QuestTransitionInvalidError(SafeMessageError):
    """The quest's current status does not allow that action."""

    safe_status_code = 409
    safe_error_code = "quest_transition_invalid"
    safe_message = "The quest is not in a state that allows that."


class QuestNotActiveError(SafeMessageError):
    """Objectives change only while their quest is active for that audience."""

    safe_status_code = 409
    safe_error_code = "quest_not_active"
    safe_message = (
        "Activate the quest, and resume it if it is suspended, before changing its objectives."
    )


class ObjectiveTransitionInvalidError(SafeMessageError):
    """The objective's current status does not allow that change."""

    safe_status_code = 409
    safe_error_code = "objective_transition_invalid"
    safe_message = "The objective is not in a state that allows that."
