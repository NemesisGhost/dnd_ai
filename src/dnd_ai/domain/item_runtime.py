"""Item instance and item runtime policy (Phase 15 checkpoint 15.3B-1b).

An item instance is a particular object in the world (a named sword, one healing potion in a
chest). Authoring it writes a lifecycle-managed definition row; where it is, who owns and carries
it, and its condition, charges, equipped and destroyed state are timeline state that only the
operations here change, one causal event each.

`item_state.last_event_id` is the item's single optimistic token ("last event seen"): every
operation, including a placement or an attunement, writes it, so a caller that read the item
before another operation ran is stale whichever table that operation touched.
"""

from .authoring import AuthoringValidationError
from .errors import SafeMessageError

ORIGIN_NOTES_MAX_LENGTH = 4000
QUANTITY_MAX = 9999
MAX_ATTUNEMENTS_PER_CHARACTER = 3
HOLDER_TYPE_CODES = frozenset({"npc", "player_character", "character"})

# operation name -> (event type recorded, event display name)
OPERATION_EVENTS: dict[str, tuple[str, str]] = {
    "award": ("item_acquired", "Item awarded"),
    "transfer": ("item_transferred", "Item transferred"),
    "equip": ("item_equipped", "Item equipped"),
    "unequip": ("item_unequipped", "Item unequipped"),
    "consume": ("item_consumed", "Item consumed"),
    "damage": ("item_damaged", "Item damaged"),
    "repair": ("item_repaired", "Item repaired"),
    "destroy": ("item_destroyed", "Item destroyed"),
    "attune": ("item_attuned", "Item attuned"),
    "end_attunement": ("item_attunement_ended", "Item attunement ended"),
}


def normalize_origin_notes(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if len(clean) > ORIGIN_NOTES_MAX_LENGTH:
        raise AuthoringValidationError(
            f"origin_notes must be at most {ORIGIN_NOTES_MAX_LENGTH} characters"
        )
    return clean


def normalize_quantity(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= QUANTITY_MAX:
        raise AuthoringValidationError(f"quantity must be between 1 and {QUANTITY_MAX}")
    return value


def normalize_percentage_amount(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise AuthoringValidationError("amount must be a whole number from 1 to 100")
    return value


class ItemDefinitionInvalidError(SafeMessageError):
    """The definition is not a published one this world can use."""

    safe_status_code = 400
    safe_error_code = "item_definition_invalid"
    safe_message = "Choose a published item definition available to this world."


class ItemHolderInvalidError(SafeMessageError):
    """The holder, container or place is not a published thing of this world."""

    safe_status_code = 400
    safe_error_code = "item_destination_invalid"
    safe_message = "Choose a published character, container item or place in this world."


class ItemContainerInvalidError(SafeMessageError):
    """The container is not a container, or placing the item in it would form a loop."""

    safe_status_code = 400
    safe_error_code = "item_container_invalid"
    safe_message = "That item cannot be placed in that container."


class ItemDestroyedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "item_destroyed"
    safe_message = "This item is destroyed."


class ItemAlreadyPlacedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "item_already_placed"
    safe_message = "This item already has a place; transfer it instead."


class ItemNotHeldError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "item_not_held"
    safe_message = "This item must be carried by a character for that."


class ItemEquippedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "item_equipped"
    safe_message = "Unequip this item first."


class ItemAttunedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "item_attuned"
    safe_message = "End this item's attunement first."


class ItemOperationInvalidError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "item_operation_invalid"
    safe_message = "That cannot be done to this item as it is now."


class AttunementNotAllowedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "attunement_not_allowed"
    safe_message = "This item cannot be attuned right now."
