"""Item definition authoring policy (Phase 15 checkpoint 15.3B-1a, decision D-22).

A definition is the reusable mechanical concept of an item (a longsword, a healing potion). The
seeded generic definitions are ruleset-wide and read-only here; a GM authors homebrew definitions
that one world owns. Only two canon states are authored: `draft` (not yet usable for new item
instances) and `canon`.
"""

import re
from decimal import Decimal, InvalidOperation

from .authoring import AuthoringValidationError

RARITIES = (
    ("common", "Common"),
    ("uncommon", "Uncommon"),
    ("rare", "Rare"),
    ("very_rare", "Very rare"),
    ("legendary", "Legendary"),
    ("artifact", "Artifact"),
    ("varies", "Varies"),
)
RARITY_CODES = frozenset(code for code, _ in RARITIES)
CANON_STATES = (("draft", "Draft"), ("canon", "Canon"))
CANON_STATE_CODES = frozenset(code for code, _ in CANON_STATES)

NAME_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 4000
CODE_MAX_LENGTH = 60
_WEIGHT_MAX = Decimal("999999.99")
_COST_MAX = Decimal("9999999999.99")


def normalize_name(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise AuthoringValidationError("name is required")
    if len(clean) > NAME_MAX_LENGTH:
        raise AuthoringValidationError(f"name must be at most {NAME_MAX_LENGTH} characters")
    return clean


def normalize_description(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if len(clean) > DESCRIPTION_MAX_LENGTH:
        raise AuthoringValidationError(
            f"description must be at most {DESCRIPTION_MAX_LENGTH} characters"
        )
    return clean


def normalize_rarity(value: str) -> str:
    if value not in RARITY_CODES:
        raise AuthoringValidationError("rarity is not a known rarity")
    return value


def normalize_canon_state(value: str) -> str:
    if value not in CANON_STATE_CODES:
        raise AuthoringValidationError("canon_status must be draft or canon")
    return value


def normalize_amount(
    value: Decimal | float | int | str | None, *, field: str, maximum: Decimal
) -> Decimal | None:
    """An optional non-negative amount with at most two decimal places."""
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise AuthoringValidationError(f"{field} must be a number") from exc
    if not amount.is_finite() or amount < 0 or amount > maximum:
        raise AuthoringValidationError(f"{field} is out of range")
    if amount != amount.quantize(Decimal("0.01")):
        raise AuthoringValidationError(f"{field} has at most two decimal places")
    return amount.quantize(Decimal("0.01"))


def normalize_weight(value: Decimal | float | int | str | None) -> Decimal | None:
    return normalize_amount(value, field="weight", maximum=_WEIGHT_MAX)


def normalize_cost(value: Decimal | float | int | str | None) -> Decimal | None:
    return normalize_amount(value, field="base_cost_gp", maximum=_COST_MAX)


def code_for_name(name: str) -> str:
    """A lowercase `snake_case` code derived from the display name."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"item_{slug}".rstrip("_")
    return slug[:CODE_MAX_LENGTH].rstrip("_")
