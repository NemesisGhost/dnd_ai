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

from pathlib import Path
from typing import Any

import yaml
from alembic.operations import Operations


# Seed data directory relative to this file
SEEDS_DIR = Path(__file__).parent.parent.parent.parent / "database" / "seeds"


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
    
    Uses PostgreSQL INSERT ... ON CONFLICT DO NOTHING for idempotency. If the seed
    contains rows with the same key as existing data, they are skipped.
    
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
    
    # Build INSERT statement
    columns = list(rows[0].keys())
    column_list = ", ".join(columns)
    qualified_table = f"{schema}.{table}"
    
    # Build conflict target (unique columns)
    conflict_target = ", ".join(key_columns)
    
    for row in rows:
        # Build value placeholders
        values = [_quote_value(row[col]) for col in columns]
        value_list = ", ".join(values)
        
        sql = f"""
            INSERT INTO {qualified_table} ({column_list})
            VALUES ({value_list})
            ON CONFLICT ({conflict_target}) DO NOTHING;
        """
        op.execute(sql)


def _quote_value(value: Any) -> str:
    """
    Quote a value for SQL insertion.
    
    This is a simple implementation for seed data. Production code should use
    proper parameter binding, but Alembic's execute with raw SQL needs strings.
    """
    if value is None:
        return "NULL"
    elif isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, str):
        # Escape single quotes
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    else:
        # For complex types, convert to string and quote
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"
