"""Pure contract for typed Organization and Religion authoring (Phase 15.1).

The closed catalog of organization kinds, the typed fields each carries, and
their validation. Framework-free; the commands, the read models, and the
portal's catalog endpoint all read the same descriptors, so a form can never
offer a field the command will refuse.

Two layers of "type" exist and the server fixes the relationship between them
(`docs/architecture/DATABASE_MODEL.md` §10.3):

- the **entity type** (`core.entity_types`), which selects the subtype table and
  is immutable after creation: `organization`, `business`, `government`,
  `religious_organization`, `military_unit`, `political_faction`;
- the descriptive **organization type** (`world.organization_types`): fixed to
  the kind for every kind except the generic `organization`, which chooses one
  of the four types that have no subtype table of their own. The database does
  not check this agreement, so the command does.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from .authoring import AuthoringValidationError

DESCRIPTION_FIELD_MAX_LENGTH = 4000
SHORT_FIELD_MAX_LENGTH = 200

ORGANIZATION_ENTITY_TYPE_CODES: frozenset[str] = frozenset(
    {
        "organization",
        "business",
        "government",
        "religious_organization",
        "military_unit",
        "political_faction",
    }
)

GENERIC_ORGANIZATION_TYPES: tuple[tuple[str, str], ...] = (
    ("guild", "Guild"),
    ("criminal_organization", "Criminal organization"),
    ("secret_society", "Secret society"),
    ("other", "Other"),
)

BUSINESS_OPERATING_STATUSES: tuple[tuple[str, str], ...] = (
    ("operating", "Operating"),
    ("closed", "Closed"),
    ("bankrupt", "Bankrupt"),
    ("relocated", "Relocated"),
)

REPUTATION_MIN = -100
REPUTATION_MAX = 100


@dataclass(frozen=True)
class OrganizationField:
    name: str
    kind: str  # "text" | "longtext" | "integer" | "select"
    label: str
    max_length: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    options: tuple[tuple[str, str], ...] = ()
    required: bool = False


@dataclass(frozen=True)
class OrganizationKind:
    code: str
    label: str
    # The `world.organization_types.code` this kind fixes, or None for the
    # generic kind, which selects one through its `organization_type` field.
    organization_type: str | None
    fields: tuple[OrganizationField, ...] = ()
    # True when the kind requires a religion (`religious_organization`).
    needs_religion: bool = False


_ORGANIZATION_TYPE_FIELD = OrganizationField(
    name="organization_type",
    kind="select",
    label="Kind of organization",
    options=GENERIC_ORGANIZATION_TYPES,
    required=True,
)

ORGANIZATION_KINDS: tuple[OrganizationKind, ...] = (
    OrganizationKind("organization", "Organization", None, (_ORGANIZATION_TYPE_FIELD,)),
    OrganizationKind(
        "business",
        "Business",
        "business",
        (
            OrganizationField("business_type", "text", "Kind of business", SHORT_FIELD_MAX_LENGTH),
            OrganizationField(
                "operating_status",
                "select",
                "Operating status",
                options=BUSINESS_OPERATING_STATUSES,
            ),
            OrganizationField(
                "reputation",
                "integer",
                "Reputation",
                minimum=REPUTATION_MIN,
                maximum=REPUTATION_MAX,
            ),
        ),
    ),
    OrganizationKind(
        "government",
        "Government",
        "government",
        (
            OrganizationField(
                "government_form", "text", "Form of government", SHORT_FIELD_MAX_LENGTH
            ),
        ),
    ),
    OrganizationKind(
        "military_unit",
        "Military unit",
        "military_unit",
        (OrganizationField("unit_type", "text", "Kind of unit", SHORT_FIELD_MAX_LENGTH),),
    ),
    OrganizationKind(
        "political_faction",
        "Political faction",
        "political_faction",
        (OrganizationField("ideology", "longtext", "Ideology", DESCRIPTION_FIELD_MAX_LENGTH),),
    ),
    OrganizationKind(
        "religious_organization",
        "Religious organization",
        "religious_organization",
        needs_religion=True,
    ),
)

_KIND_BY_CODE = {kind.code: kind for kind in ORGANIZATION_KINDS}
AUTHORABLE_ORGANIZATION_KINDS: frozenset[str] = frozenset(_KIND_BY_CODE)


def organization_kind(code: str) -> OrganizationKind:
    kind = _KIND_BY_CODE.get(code)
    if kind is None:
        raise AuthoringValidationError("kind is not an authorable organization kind")
    return kind


def normalize_optional_text(value: str | None, *, field: str, max_length: int) -> str | None:
    """Stripped; blank becomes NULL; over-long is a validation failure."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > max_length:
        raise AuthoringValidationError(f"{field} exceeds {max_length} characters")
    return stripped


def normalize_typed_fields(kind: OrganizationKind, raw: Mapping[str, object]) -> dict[str, object]:
    """Validate the kind's typed fields. Every key must be one the kind carries
    (an inapplicable non-null value is a validation failure, never ignored); a
    missing key is `None` (or the field's default is applied by the command).
    Returns exactly one entry per field the kind carries."""
    allowed = {f.name: f for f in kind.fields}
    for key, value in raw.items():
        if key not in allowed and value is not None:
            raise AuthoringValidationError(f"{key} does not apply to this kind")
    clean: dict[str, object] = {}
    for name, descriptor in allowed.items():
        value = raw.get(name)
        if descriptor.kind in ("text", "longtext"):
            if value is not None and not isinstance(value, str):
                raise AuthoringValidationError(f"{name} must be text")
            clean[name] = normalize_optional_text(
                value if isinstance(value, str) else None,
                field=name,
                max_length=descriptor.max_length or SHORT_FIELD_MAX_LENGTH,
            )
        elif descriptor.kind == "integer":
            if value is None:
                clean[name] = None
            elif isinstance(value, bool) or not isinstance(value, int):
                raise AuthoringValidationError(f"{name} must be an integer")
            elif (descriptor.minimum is not None and value < descriptor.minimum) or (
                descriptor.maximum is not None and value > descriptor.maximum
            ):
                raise AuthoringValidationError(f"{name} is out of range")
            else:
                clean[name] = value
        elif descriptor.kind == "select":
            choices = {option for option, _ in descriptor.options}
            if value is None:
                if descriptor.required:
                    raise AuthoringValidationError(f"{name} is required")
                clean[name] = None
            elif not isinstance(value, str) or value not in choices:
                raise AuthoringValidationError(f"{name} is not an allowed choice")
            else:
                clean[name] = value
        else:  # pragma: no cover - the catalog is closed
            raise AssertionError(descriptor.kind)
    return clean


def organization_type_for(kind: OrganizationKind, typed: Mapping[str, object]) -> str:
    """The `world.organization_types.code` the server stores for this kind."""
    if kind.organization_type is not None:
        return kind.organization_type
    value = typed.get("organization_type")
    assert isinstance(value, str)
    return value
