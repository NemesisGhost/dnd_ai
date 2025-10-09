
#!/usr/bin/env python3
"""
CLI to validate a JSON query spec and compile it to parameterized SQL.

Usage:
  python compile_query.py --spec path/to/query.json [--schema path/to/schema.json]
                          [--param-style psycopg|qmark|named] [--quote]

Exit codes:
  0 - success
  2 - validation error
  3 - compilation error
  4 - IO / usage error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict

from src.shared.query_spec_validator import QuerySpecValidator, load_query_schema, ValidationError
from src.shared.query_to_sql import compile_query, IdentifierResolver, ParamStyle


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate and compile a JSON query spec.")
    p.add_argument("--no-validate", action="store_true", help="Skip JSON Schema validation")
    p.add_argument("--spec", required=True, help="Path to query JSON file")
    p.add_argument("--schema", help="Path to JSON schema (optional)")
    p.add_argument("--param-style", choices=[ParamStyle.PSYCOPG, ParamStyle.QMARK, ParamStyle.NAMED],
                   default=ParamStyle.PSYCOPG, help="Parameter style to use in generated SQL")
    p.add_argument("--quote", action="store_true", help="Quote identifiers (PostgreSQL-style double quotes)")
    args = p.parse_args(argv)

    try:
        with open(args.spec, "r", encoding="utf-8") as f:
            spec: Dict[str, Any] = json.load(f)
    except Exception as e:
        print(f"[IO] Failed to read spec: {e}", file=sys.stderr)
        return 4

    # Load schema once; validator caches internally
    if not args.no_validate:
        try:
            schema = load_query_schema(args.schema) if args.schema else load_query_schema()
            validator = QuerySpecValidator(schema)
        except Exception as e:
            print(f"[IO] Failed to load schema: {e}", file=sys.stderr)
            return 4

        try:
            validator.validate(spec)
        except ValidationError as ve:
            print("[VALIDATION] Query spec failed validation:\n", validator.explain_errors(spec), file=sys.stderr)
            return 2

    try:
        sql = compile_query(spec, idr=IdentifierResolver(quote=args.quote), param_style=args.param_style)
    except Exception as ce:
        print(f"[COMPILE] Failed to compile spec: {ce}", file=sys.stderr)
        return 3

    # Pretty output for piping
    print(sql.text)
    print("\n-- params:", json.dumps(sql.params, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
