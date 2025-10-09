
"""
Query spec validator utilities (draft-07).

- Loads and caches a JSON Schema for the query-spec once at import time (good for AWS Lambda).
- Provides a small wrapper class to validate and summarize errors nicely.

Env var override:
  QUERY_SCHEMA_PATH: absolute/relative path to a JSON schema file. If not set,
  we try common locations: ./Database/query_json_schema.json or ./query_json_schema.json

External dependency: jsonschema
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, Optional

try:
    from jsonschema import Draft7Validator, ValidationError  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "jsonschema package is required. Install with 'pip install jsonschema' or add to your Lambda layer."
    ) from exc


def _discover_schema_path(start: Optional[str] = None) -> Optional[str]:
    """Find a likely schema path by walking up a few directories."""
    start = start or os.path.dirname(os.path.abspath(__file__))
    cur = start
    for _ in range(8):  # guard against runaway
        candidate = os.path.join(cur, "Database", "query_json_schema.json")
        if os.path.isfile(candidate):
            return candidate
        candidate2 = os.path.join(cur, "query_json_schema.json")
        if os.path.isfile(candidate2):
            return candidate2
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


@lru_cache(maxsize=1)
def load_query_schema(schema_path: Optional[str] = None) -> Dict[str, Any]:
    """Load the JSON schema file and cache it. Raises on any error."""
    schema_path = schema_path or os.getenv("QUERY_SCHEMA_PATH") or _discover_schema_path()
    if not schema_path or not os.path.isfile(schema_path):
        raise FileNotFoundError(
            f"Query schema not found. Set QUERY_SCHEMA_PATH or place Database/query_json_schema.json nearby. "
            f"Tried: {schema_path!r}"
        )
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


class QuerySpecValidator:
    """Thin wrapper around jsonschema.Draft7Validator with friendly helpers."""

    def __init__(self, schema: Optional[Dict[str, Any]] = None) -> None:
        schema = schema or load_query_schema()
        self.validator = Draft7Validator(schema)

    def validate(self, spec: Dict[str, Any]) -> None:
        """Raise ValidationError if invalid."""
        self.validator.validate(spec)

    def is_valid(self, spec: Dict[str, Any]) -> bool:
        return self.validator.is_valid(spec)

    def explain_errors(self, spec: Dict[str, Any]) -> str:
        lines = []
        for err in self.validator.iter_errors(spec):
            path = ".".join(str(p) for p in err.path) or "<root>"
            lines.append(f"{path}: {err.message}")
        return "\n".join(lines)


__all__ = ["QuerySpecValidator", "load_query_schema", "ValidationError"]
