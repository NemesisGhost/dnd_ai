"""Item definition commands (Phase 15 checkpoint 15.3B-1a, decision D-22).

`create_item_definition` makes a homebrew definition owned by the campaign world, and
`update_item_definition` edits one against its `row_version`. Ruleset-wide (seeded) definitions
and other worlds' homebrew are never editable here and look like a missing definition. The code
is derived from the name and made unique within the world; an advisory transaction lock on the
world's definitions serializes two creates of the same name.

Lock order: authority scope, then the definition row `FOR UPDATE` (an update) or the world
definition advisory lock (a create).
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import AuthoringValidationError, StaleWriteError
from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.item_definition_authoring import (
    CODE_MAX_LENGTH,
    code_for_name,
    normalize_canon_state,
    normalize_cost,
    normalize_description,
    normalize_name,
    normalize_rarity,
    normalize_weight,
)

from ._content import EntityNotFoundError, lock_authoring_scope

Amount = Decimal | float | int | str | None


@dataclass(frozen=True)
class DefinitionResult:
    item_definition_id: uuid.UUID
    world_id: uuid.UUID
    row_version: int
    created: bool
    changed: bool
    changed_fields: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _Values:
    name: str
    category: str
    description: str | None
    rarity: str
    requires_attunement: bool
    weight: Decimal | None
    base_cost_gp: Decimal | None
    canon_status: str

    def as_fields(self) -> dict[str, object]:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "rarity": self.rarity,
            "requires_attunement": self.requires_attunement,
            "weight": None if self.weight is None else float(self.weight),
            "base_cost_gp": None if self.base_cost_gp is None else float(self.base_cost_gp),
            "canon_status": self.canon_status,
        }


def _clean(
    *,
    name: str,
    category: str,
    description: str | None,
    rarity: str,
    requires_attunement: bool,
    weight: Amount,
    base_cost_gp: Amount,
    canon_status: str,
) -> _Values:
    return _Values(
        name=normalize_name(name),
        category=category,
        description=normalize_description(description),
        rarity=normalize_rarity(rarity),
        requires_attunement=bool(requires_attunement),
        weight=normalize_weight(weight),
        base_cost_gp=normalize_cost(base_cost_gp),
        canon_status=normalize_canon_state(canon_status),
    )


def _category_id(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text("SELECT item_category_id FROM rules.item_categories WHERE code = :c AND is_active"),
        {"c": code},
    ).scalar()
    if value is None:
        raise AuthoringValidationError("category is not a known item category")
    assert isinstance(value, uuid.UUID)
    return value


def create_item_definition(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str,
    category: str,
    description: str | None = None,
    rarity: str = "common",
    requires_attunement: bool = False,
    weight: Amount = None,
    base_cost_gp: Amount = None,
    canon_status: str = "draft",
) -> DefinitionResult:
    values = _clean(
        name=name,
        category=category,
        description=description,
        rarity=rarity,
        requires_attunement=requires_attunement,
        weight=weight,
        base_cost_gp=base_cost_gp,
        canon_status=canon_status,
    )
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    category_id = _category_id(connection, values.category)
    version_id = connection.execute(
        text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar()
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"item_definitions:{scope.world_id}"},
    )
    base = code_for_name(values.name)
    code = base
    number = 1
    while connection.execute(
        text("""
            SELECT 1 FROM rules.item_definitions
            WHERE ruleset_version_id = :v AND code = :c
              AND (owning_world_id IS NULL OR owning_world_id = :w)
        """),
        {"v": version_id, "c": code, "w": scope.world_id},
    ).scalar():
        number += 1
        suffix = f"_{number}"
        code = base[: CODE_MAX_LENGTH - len(suffix)] + suffix
    row = connection.execute(
        text("""
            INSERT INTO rules.item_definitions
                (ruleset_version_id, owning_world_id, item_category_id, code, display_name,
                 description, rarity, requires_attunement, weight, base_cost_gp,
                 canon_status_id, created_by_user_id)
            VALUES (:v, :w, :cat, :code, :name, :description, :rarity, :attune, :weight, :cost,
                    (SELECT canon_status_id FROM core.canon_statuses WHERE code = :canon), :user)
            RETURNING item_definition_id, row_version
        """),
        {
            "v": version_id,
            "w": scope.world_id,
            "cat": category_id,
            "code": code,
            "name": values.name,
            "description": values.description,
            "rarity": values.rarity,
            "attune": values.requires_attunement,
            "weight": values.weight,
            "cost": values.base_cost_gp,
            "canon": values.canon_status,
            "user": actor_user_id,
        },
    ).one()
    return DefinitionResult(
        item_definition_id=row[0],
        world_id=scope.world_id,
        row_version=int(row[1]),
        created=True,
        changed=True,
        changed_fields=dict(initial_fields(values.as_fields())),
    )


def update_item_definition(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    item_definition_id: uuid.UUID,
    expected_row_version: int,
    name: str,
    category: str,
    description: str | None = None,
    rarity: str = "common",
    requires_attunement: bool = False,
    weight: Amount = None,
    base_cost_gp: Amount = None,
    canon_status: str = "draft",
) -> DefinitionResult:
    values = _clean(
        name=name,
        category=category,
        description=description,
        rarity=rarity,
        requires_attunement=requires_attunement,
        weight=weight,
        base_cost_gp=base_cost_gp,
        canon_status=canon_status,
    )
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    category_id = _category_id(connection, values.category)
    row = (
        connection.execute(
            text("""
                SELECT d.row_version, d.display_name, d.description, d.rarity,
                       d.requires_attunement, d.weight, d.base_cost_gp,
                       ic.code AS category, cs.code AS canon
                FROM rules.item_definitions d
                JOIN rules.item_categories ic ON ic.item_category_id = d.item_category_id
                JOIN core.canon_statuses cs ON cs.canon_status_id = d.canon_status_id
                WHERE d.item_definition_id = :d AND d.owning_world_id = :w
                FOR UPDATE OF d
            """),
            {"d": item_definition_id, "w": scope.world_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise EntityNotFoundError(f"item definition {item_definition_id} is not in this world")
    if int(row["row_version"]) != expected_row_version:
        raise StaleWriteError(f"item definition {item_definition_id} was changed")
    before = {
        "name": row["display_name"],
        "category": row["category"],
        "description": row["description"],
        "rarity": row["rarity"],
        "requires_attunement": row["requires_attunement"],
        "weight": None if row["weight"] is None else float(row["weight"]),
        "base_cost_gp": None if row["base_cost_gp"] is None else float(row["base_cost_gp"]),
        "canon_status": row["canon"],
    }
    changed = diff_fields(before, values.as_fields())
    if not changed:
        return DefinitionResult(
            item_definition_id=item_definition_id,
            world_id=scope.world_id,
            row_version=int(row["row_version"]),
            created=False,
            changed=False,
        )
    version = connection.execute(
        text("""
            UPDATE rules.item_definitions
            SET item_category_id = :cat, display_name = :name, description = :description,
                rarity = :rarity, requires_attunement = :attune, weight = :weight,
                base_cost_gp = :cost,
                canon_status_id = (SELECT canon_status_id FROM core.canon_statuses
                                   WHERE code = :canon)
            WHERE item_definition_id = :d
            RETURNING row_version
        """),
        {
            "d": item_definition_id,
            "cat": category_id,
            "name": values.name,
            "description": values.description,
            "rarity": values.rarity,
            "attune": values.requires_attunement,
            "weight": values.weight,
            "cost": values.base_cost_gp,
            "canon": values.canon_status,
        },
    ).scalar()
    assert version is not None
    return DefinitionResult(
        item_definition_id=item_definition_id,
        world_id=scope.world_id,
        row_version=int(version),
        created=False,
        changed=True,
        changed_fields=dict(changed),
    )
