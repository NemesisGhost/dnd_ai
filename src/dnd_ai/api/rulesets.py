"""Ruleset options for world and campaign setup (Phase 14).

    GET /rulesets    rulesets a new world may allow-list

Reference data, not a world-scoped or campaign-scoped resource: any human
principal may read the catalog of canon rulesets that have a current version.
Foundry device principals are rejected. Read-only, so no idempotency, CSRF, or
audit concerns.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from .auth import require_human_user_id
from .deps import get_connection

router = APIRouter(tags=["rulesets"])


@router.get("/rulesets")
def list_rulesets_endpoint(
    _user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> dict[str, Any]:
    rows = connection.execute(
        text("""
            SELECT rs.ruleset_id, rs.code, rs.display_name, rs.description,
                   rv.ruleset_version_id, rv.version_label
            FROM rules.rulesets rs
            JOIN core.canon_statuses cs ON cs.canon_status_id = rs.canon_status_id
            JOIN rules.ruleset_versions rv ON rv.ruleset_id = rs.ruleset_id AND rv.is_current
            WHERE cs.code = 'canon'
            ORDER BY rs.display_name, rs.ruleset_id
        """)
    ).all()
    return {
        "items": [
            {
                "ruleset_id": str(row.ruleset_id),
                "code": row.code,
                "display_name": row.display_name,
                "description": row.description,
                "current_versions": [
                    {
                        "ruleset_version_id": str(row.ruleset_version_id),
                        "version_label": row.version_label,
                    }
                ],
            }
            for row in rows
        ]
    }
