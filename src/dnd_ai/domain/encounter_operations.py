"""Encounter operation policy (Phase 15 checkpoint 15.3B-2b).

An encounter moves `pending` -> `active` -> `completed` (ended with outcomes), or from `pending`
or `active` to `aborted` (ended without a result). Preparation is 15.3B-2a; the turn and the end
commands are in `commands.encounters`, shared with the Foundry combat sync.
"""

from .errors import SafeMessageError

ACTION_KINDS = (
    ("attack", "Attack"),
    ("cast_spell", "Cast a spell"),
    ("dodge", "Dodge"),
    ("dash", "Dash"),
    ("disengage", "Disengage"),
    ("help", "Help"),
    ("hide", "Hide"),
    ("ready", "Ready an action"),
    ("use_item", "Use an item"),
    ("other", "Other"),
)
OUTCOMES = (
    ("defeated", "Defeated"),
    ("escaped", "Escaped"),
    ("surrendered", "Surrendered"),
    ("captured", "Captured"),
)


class EncounterNotReadyError(SafeMessageError):
    """An encounter with nobody in it cannot start."""

    safe_status_code = 409
    safe_error_code = "encounter_not_ready"
    safe_message = "Add at least one participant before starting the encounter."


class EncounterFinishedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "encounter_finished"
    safe_message = "This encounter has already finished."
