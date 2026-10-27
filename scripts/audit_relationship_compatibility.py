"""Read-only audit: relationships the current participant-compatibility policy would refuse.

Lists every relationship (active and archived, every world) whose type, roles or participants
the policy in `dnd_ai.domain.relationship_authoring` would not accept today, with the same plain
reasons the editor shows as `policy_conflicts`. It changes nothing: the connection is read-only,
and an incompatible record stays readable, correctable, endable and archivable. To connect
different records, end or archive the relationship and add a correct one (ADR 0017).

Usage (from the repository root):

    uv run python scripts/audit_relationship_compatibility.py

The database comes from DND_AI_DATABASE_URL, or DATABASE_URL when that is not set. The exit status is
0 whether or not conflicts are found; the summary line says how many.
"""

import os
import sys
from collections import defaultdict

from sqlalchemy import Connection, create_engine, text

from dnd_ai.domain.relationship_authoring import policy_conflicts

_ROWS = """
    SELECT r.relationship_id, p.entity_id, w.name AS world, rt.code AS type_code, rt.is_active,
           ls.code AS lifecycle, e.canonical_name, et.code AS entity_type, pr.code AS role
    FROM world.relationships r
    JOIN core.worlds w ON w.world_id = r.world_id
    JOIN world.relationship_types rt ON rt.relationship_type_id = r.relationship_type_id
    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = r.lifecycle_status_id
    JOIN world.relationship_participants p ON p.relationship_id = r.relationship_id
    JOIN core.entities e ON e.entity_id = p.entity_id
    JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
    JOIN world.relationship_participant_roles pr
      ON pr.relationship_participant_role_id = p.participant_role_id
    ORDER BY w.name, r.created_at, r.relationship_id, p.created_at
"""


def audit(connection: Connection) -> list[tuple[str, str, str, object, list[str]]]:
    """(world, type, lifecycle, relationship id, reasons) for each record the policy would refuse."""
    grouped: dict[object, list[tuple[str, str, str]]] = defaultdict(list)
    ids: dict[object, list[object]] = defaultdict(list)
    heads: dict[object, tuple[str, str, bool, str]] = {}
    for row in connection.execute(text(_ROWS)):
        heads[row.relationship_id] = (row.world, row.type_code, row.is_active, row.lifecycle)
        grouped[row.relationship_id].append((row.role, row.entity_type, row.canonical_name))
        ids[row.relationship_id].append(row.entity_id)
    found = []
    for relationship_id, participants in grouped.items():
        world, type_code, is_active, lifecycle = heads[relationship_id]
        reasons = policy_conflicts(
            type_code,
            participants,
            type_offered=bool(is_active),
            entity_ids=ids[relationship_id],
        )
        if reasons:
            found.append((world, type_code, lifecycle, relationship_id, reasons))
    return found


def main() -> int:
    url = os.environ.get("DND_AI_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("Set DND_AI_DATABASE_URL or DATABASE_URL.", file=sys.stderr)
        return 2
    engine = create_engine(url)
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        found = audit(connection)
        checked = connection.execute(text("SELECT count(*) FROM world.relationships")).scalar()
    for world, type_code, lifecycle, relationship_id, reasons in found:
        print(f"{world} | {type_code} | {lifecycle} | {relationship_id}")
        for reason in reasons:
            print(f"    {reason}")
    print(f"{checked} relationships checked, {len(found)} with policy conflicts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
