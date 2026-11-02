"""Editor read models for item definitions (Phase 15 checkpoint 15.3B-1a, D-22).

`canon.edit` only. A campaign sees the ruleset-wide (seeded) definitions of its ruleset version
and the homebrew definitions its own world owns, never another world's. Only owned definitions
are editable.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class ItemDefinitionView:
    item_definition_id: uuid.UUID
    code: str
    name: str
    category: str
    category_label: str
    description: str | None
    rarity: str
    requires_attunement: bool
    weight: Decimal | None
    base_cost_gp: Decimal | None
    canon_status: str
    row_version: int
    is_homebrew: bool


_SELECT = """
    SELECT d.item_definition_id, d.code, d.display_name, ic.code AS category,
           ic.display_name AS category_label, d.description, d.rarity, d.requires_attunement,
           d.weight, d.base_cost_gp, cs.code AS canon, d.row_version,
           d.owning_world_id IS NOT NULL AS is_homebrew
    FROM rules.item_definitions d
    JOIN rules.item_categories ic ON ic.item_category_id = d.item_category_id
    JOIN core.canon_statuses cs ON cs.canon_status_id = d.canon_status_id
    JOIN campaign.campaigns c ON c.ruleset_version_id = d.ruleset_version_id
    WHERE c.campaign_id = :campaign
      AND (d.owning_world_id IS NULL OR d.owning_world_id = :world)
"""


def _view(r: Any) -> ItemDefinitionView:
    return ItemDefinitionView(
        item_definition_id=r["item_definition_id"],
        code=r["code"],
        name=r["display_name"],
        category=r["category"],
        category_label=r["category_label"],
        description=r["description"],
        rarity=r["rarity"],
        requires_attunement=r["requires_attunement"],
        weight=r["weight"],
        base_cost_gp=r["base_cost_gp"],
        canon_status=r["canon"],
        row_version=int(r["row_version"]),
        is_homebrew=r["is_homebrew"],
    )


def list_item_definitions(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    world_id: uuid.UUID,
    category: str | None = None,
    homebrew_only: bool = False,
) -> list[ItemDefinitionView]:
    sql = _SELECT
    params: dict[str, object] = {"campaign": campaign_id, "world": world_id}
    if category is not None:
        sql += " AND ic.code = :category"
        params["category"] = category
    if homebrew_only:
        sql += " AND d.owning_world_id IS NOT NULL"
    sql += " ORDER BY d.display_name, d.code"
    return [_view(row) for row in connection.execute(text(sql), params).mappings()]


def get_item_definition(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    world_id: uuid.UUID,
    item_definition_id: uuid.UUID,
) -> ItemDefinitionView | None:
    row = (
        connection.execute(
            text(_SELECT + " AND d.item_definition_id = :definition"),
            {"campaign": campaign_id, "world": world_id, "definition": item_definition_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _view(row)


def list_item_categories(connection: Connection) -> list[tuple[str, str]]:
    return [
        (r[0], r[1])
        for r in connection.execute(
            text(
                "SELECT code, display_name FROM rules.item_categories WHERE is_active "
                "ORDER BY sort_order, code"
            )
        )
    ]
