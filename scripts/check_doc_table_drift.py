"""Compare table names between docs/architecture/DATABASE_MODEL.md and the
live SQLAlchemy metadata (src/dnd_ai/persistence/tables), to catch the kind
of doc/schema drift CLAUDE.md §4 already names as a known failure mode: "If
PLAN.md and this document disagree ... this document wins and PLAN.md
should be corrected" implies DATABASE_MODEL.md itself needs to actually
stay current for that to mean anything.

This is a heuristic doc-hygiene check, not a CI gate. DATABASE_MODEL.md
also mentions schema-qualified function names (`rules.default_canon_status_id`)
and schema.table.column triples that this script cannot always distinguish
from a table reference by text pattern alone. Read both report sections
before acting on them — a "phantom" entry is a prompt to go look, not proof
the doc is wrong.

Usage: uv run python scripts/check_doc_table_drift.py
"""

import re
import sys
from pathlib import Path

from dnd_ai.persistence.tables import metadata

DOC_PATH = Path("docs/architecture/DATABASE_MODEL.md")

# Bounded schemas this project owns (docs/PLAN.md §3), mirroring
# tests/database/test_schema_documentation.py's PROJECT_SCHEMAS.
PROJECT_SCHEMAS = {
    "core",
    "security",
    "rules",
    "character",
    "world",
    "campaign",
    "narrative",
    "knowledge",
    "interaction",
    "ai",
    "audit",
    "import",
    "integration",
}

# A backtick-quoted two-part identifier: `schema.name` — not
# `schema.table.column` (three parts) and not `schema.function()` (has a
# paren), so most non-table mentions are already excluded by shape alone.
TWO_PART_BACKTICK = re.compile(r"`([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)`")


def mentioned_qualified_names(doc_text: str) -> set[str]:
    return {
        f"{schema}.{name}"
        for schema, name in TWO_PART_BACKTICK.findall(doc_text)
        if schema in PROJECT_SCHEMAS
    }


def main() -> int:
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    mentioned = mentioned_qualified_names(doc_text)
    live = {t.key for t in metadata.tables.values()}

    undocumented = sorted(live - mentioned)
    phantom = sorted(mentioned - live)

    if undocumented:
        print(f"Live tables not mentioned as `schema.table` anywhere in {DOC_PATH}:")
        for name in undocumented:
            print(f"  {name}")
    else:
        print(f"Every live table is mentioned somewhere in {DOC_PATH}.")

    print()
    if phantom:
        print(
            f"`schema.table`-shaped mentions in {DOC_PATH} with no matching live "
            "table (functions, renamed/removed tables, or a false positive from "
            "this heuristic — check before acting):"
        )
        for name in phantom:
            print(f"  {name}")
    else:
        print("No schema.table-shaped mention points at a nonexistent table.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
