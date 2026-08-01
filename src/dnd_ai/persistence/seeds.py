"""Seed data infrastructure.

This module provides the infrastructure for idempotent lookup-table seeding per
docs/DATABASE_CONVENTIONS.md §25.4.

Seed data lives in database/seeds/ as YAML files, one per table. Each file contains
a list of rows with stable codes or identifiers. Seeds are applied through normal
Alembic revisions — never as a separate untracked process.

Seeds must be idempotent: running twice must produce the same result. Use INSERT
with ON CONFLICT DO NOTHING or UPDATE to achieve this.

Example seed file (database/seeds/core.canon_statuses.yaml):
```yaml
- code: draft
  name: Draft
  description: Not yet ready for review
- code: proposed
  name: Proposed
  description: Submitted for GM or validation review
- code: approved
  name: Approved
  description: Reviewed and ready to apply
```

Example migration using seeds:
```python
from dnd_ai.persistence.seeds import apply_seed

def upgrade():
    apply_seed(op, 'core', 'canon_statuses')
```
"""

import json
import os
from pathlib import Path
from typing import Any

import yaml
from alembic.operations import Operations
from sqlalchemy import text

# Seed data directory. Alembic (and the migration runner in docs/PLAN.md §29.6)
# always runs with the repo's `database/` directory as a sibling of the working
# directory, so resolve relative to the current working directory first — this
# also holds once the runner installs dnd_ai into site-packages, where a path
# derived from this file's own location would no longer point at database/seeds.
# DND_AI_SEEDS_DIR overrides both for non-standard layouts.


def _default_seeds_dir() -> Path:
    override = os.environ.get("DND_AI_SEEDS_DIR")
    if override:
        return Path(override)

    cwd_candidate = Path.cwd() / "database" / "seeds"
    if cwd_candidate.exists():
        return cwd_candidate

    # Fallback for a checkout where this module is imported from a different cwd.
    return Path(__file__).resolve().parent.parent.parent.parent / "database" / "seeds"


SEEDS_DIR = _default_seeds_dir()


def load_seed_data(schema: str, table: str) -> list[dict[str, Any]]:
    """
    Load seed data from YAML file.

    Args:
        schema: Schema name (e.g., "core")
        table: Table name (e.g., "canon_statuses")

    Returns:
        List of row dictionaries

    Raises:
        FileNotFoundError: If the seed file does not exist
        yaml.YAMLError: If the file is not valid YAML
    """
    seed_file = SEEDS_DIR / f"{schema}.{table}.yaml"
    if not seed_file.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_file}")

    with seed_file.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, list):
        raise ValueError(f"Seed file must contain a list of rows: {seed_file}")

    return data


def apply_seed(
    op: Operations,
    schema: str,
    table: str,
    *,
    key_columns: list[str] | None = None,
) -> None:
    """
    Apply seed data to a table idempotently.

    Uses PostgreSQL INSERT ... ON CONFLICT DO NOTHING for idempotency, with
    values passed as bound parameters (not string-interpolated) so quoting and
    escaping are handled by the driver rather than by hand.

    Args:
        op: Alembic operations context
        schema: Schema name (e.g., "core")
        table: Table name (e.g., "canon_statuses")
        key_columns: Columns that form the unique key (default: ["code"])
                     Must match a unique constraint or primary key on the table

    Example:
        apply_seed(op, "core", "canon_statuses")
        apply_seed(op, "rules", "abilities", key_columns=["code"])
    """
    if key_columns is None:
        key_columns = ["code"]

    rows = load_seed_data(schema, table)
    if not rows:
        return

    columns = list(rows[0].keys())
    column_list = ", ".join(columns)
    param_list = ", ".join(f":{col}" for col in columns)
    conflict_target = ", ".join(key_columns)
    qualified_table = f"{schema}.{table}"

    statement = text(
        f"""
        INSERT INTO {qualified_table} ({column_list})
        VALUES ({param_list})
        ON CONFLICT ({conflict_target}) DO NOTHING
        """
    )

    for row in rows:
        params = {col: _adapt_value(row[col]) for col in columns}
        op.execute(statement.bindparams(**params))


def _adapt_value(value: Any) -> Any:
    """
    Adapt a YAML-parsed value for parameter binding.

    Mappings and sequences (destined for JSON/JSONB columns) are serialized to
    JSON text, since the driver cannot bind a raw dict/list directly without
    table metadata declaring the column type. Scalars pass through unchanged
    for the driver to bind natively.
    """
    if isinstance(value, dict | list):
        return json.dumps(value)
    return value
