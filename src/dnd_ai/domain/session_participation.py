"""Which session participation roles a character may take (Phase 15 CP-1).

A participant's *role in the session* is not the character's identity. Identity is the entity
subtype (`player_character` or `npc`); the session role says how the character takes part. A
character may take the role that matches its own kind, or `guest`. Observer, controller and GM
are account roles in the access model and are never participation roles.

The command validates with this policy and the session read model publishes it, so the form can
only offer what the server accepts.
"""

from __future__ import annotations

# Entity subtypes that can be session participants.
PARTICIPANT_KINDS: tuple[str, ...] = ("player_character", "npc")

_GUEST = "guest"


def participant_roles_for_kind(character_kind: str | None) -> tuple[str, ...]:
    """The roles a character of this kind may take, matching role first; none for an
    unknown or unusable kind."""
    if character_kind in PARTICIPANT_KINDS:
        return (character_kind, _GUEST)
    return ()


def participant_role_options() -> dict[str, list[str]]:
    """The catalog published to clients, keyed by character kind."""
    return {kind: list(participant_roles_for_kind(kind)) for kind in PARTICIPANT_KINDS}


__all__ = ["PARTICIPANT_KINDS", "participant_role_options", "participant_roles_for_kind"]
