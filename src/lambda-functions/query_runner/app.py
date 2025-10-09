"""
AWS Lambda: query_runner

Purpose: Accept a JSON payload that matches the query JSON Schema, validate it,
compile it to parameterized SQL, execute against PostgreSQL (RDS), and return
the result set as JSON.

Highlights
- Uses shared compiler and validator logic (vendored in this package via imports)
- Secure identifier handling and parameterized SQL
- Connects to RDS using IAM auth token (no static DB password required)
- Returns a compact, unambiguous result shape with labeled columns

Expected request (via API Gateway):
- event["body"] is a JSON string containing the query spec
- Direct invocation may pass the spec dict as the event itself

Environment variables:
- DB_HOST, DB_PORT, DB_NAME, DB_USER
- AWS_REGION (or AWS_DEFAULT_REGION)
- QUERY_SCHEMA_PATH: optional override path to bundled schema (defaults to local file)

Response shape (success):
{
  "ok": true,
  "row_count": <int>,
  "columns": ["alias__column", ...],
  "rows": [[...], ...],
  "sql": "SELECT ...",
  "params": [ ... ]
}

Errors return HTTP 400 for validation errors or 500 otherwise with
{"ok": false, "error": "<Class>: <message>"}
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

import boto3
import pg8000  # provided by Lambda Layer
import ssl

# Import shared compilation/validation utilities
# Use local copies of shared utilities bundled with this function package
from shared.query_spec_validator import QuerySpecValidator, load_query_schema, ValidationError
from shared.query_to_sql import compile_query, IdentifierResolver, ParamStyle


def _json_response(body: Dict[str, Any], status: int = 200) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def _get_env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def _db_connect():
    host = _get_env("DB_HOST")
    port = int(os.getenv("DB_PORT", "5432"))
    database = _get_env("DB_NAME")
    user = _get_env("DB_USER")

    # Generate short-lived IAM auth token
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    rds = boto3.client("rds", region_name=region) if region else boto3.client("rds")
    token = rds.generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user)

    # Enforce TLS
    ssl_ctx = ssl.create_default_context()

    return pg8000.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=token,
        ssl_context=ssl_ctx,
        timeout=20,
    )


def _parse_event_body(event: Dict[str, Any]) -> Dict[str, Any]:
    # If API Gateway proxy integration, event has a "body" string
    if isinstance(event, dict) and "body" in event:
        body = event["body"]
        if isinstance(body, str):
            return json.loads(body or "{}")
        if isinstance(body, (bytes, bytearray)):
            return json.loads(body.decode("utf-8"))
        if isinstance(body, dict):
            return body
        raise ValueError("Unsupported body type")
    # Otherwise, treat the event itself as the spec
    if isinstance(event, dict):
        return event
    raise ValueError("Unsupported event type; expected API Gateway event or JSON dict")


def _label_select_columns(sql_text: str) -> Tuple[str, List[str]]:
    """
    Ensure unambiguous column labels by transforming each projection
    of the form alias.column into alias.column AS alias__column.

    Returns (new_sql_text, labels).
    """
    # Find the first FROM at top level and split the SELECT list
    m = re.search(r"\sFROM\s", sql_text, flags=re.IGNORECASE)
    if not m:
        return sql_text, []
    select_part = sql_text[len("SELECT "): m.start()]
    rest = sql_text[m.start():]

    parts = [p.strip() for p in select_part.split(",")]
    new_parts: List[str] = []
    labels: List[str] = []
    for p in parts:
        # Expect form: alias.column
        q = p
        # If it already has AS, respect it
        if re.search(r"\sAS\s", p, flags=re.IGNORECASE):
            new_parts.append(p)
            # Extract label after AS
            label = re.split(r"\sAS\s", p, flags=re.IGNORECASE)[-1].strip().strip('"')
            labels.append(label)
            continue
        m2 = re.match(r"([A-Za-z_][A-Za-z0-9_\"]*)\.([A-Za-z_][A-Za-z0-9_\"]*)$", p)
        if m2:
            head = m2.group(1).strip('"')
            col = m2.group(2).strip('"')
            label = f"{head}__{col}"
            q = f"{p} AS \"{label}\""
            labels.append(label)
        else:
            # Fallback: keep as-is and let DB label it
            labels.append(p)
        new_parts.append(q)

    new_sql = "SELECT " + ", ".join(new_parts) + rest
    return new_sql, labels


def handler(event, context):
    try:
        # Parse spec
        spec = _parse_event_body(event)

        # Load and validate against JSON Schema
        try:
            schema = load_query_schema(os.getenv("QUERY_SCHEMA_PATH"))
            validator = QuerySpecValidator(schema)
            validator.validate(spec)
        except ValidationError as ve:
            return _json_response({"ok": False, "error": f"ValidationError: {ve.message}", "details": validator.explain_errors(spec)}, 400)

        # Compile to SQL (PostgreSQL style placeholders %s)
        sql_prod = compile_query(spec, idr=IdentifierResolver(quote=False), param_style=ParamStyle.PSYCOPG)

        # Label columns to avoid name collisions across joins
        labeled_sql, labels = _label_select_columns(sql_prod.text)

        # Execute
        conn = _db_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(labeled_sql, sql_prod.params)
                rows = cur.fetchall()
                # Column labels from cursor.description if present; else use our labels
                desc = getattr(cur, "description", None)
                colnames = [d[0] for d in desc] if desc else labels
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return _json_response(
            {
                "ok": True,
                "row_count": len(rows),
                "columns": colnames or labels,
                "rows": rows,
                "sql": labeled_sql,
                "params": sql_prod.params,
            },
            200,
        )

    except Exception as e:
        return _json_response({"ok": False, "error": f"{e.__class__.__name__}: {e}"}, 500)


if __name__ == "__main__":
    # Local smoke test (requires env vars and DB connectivity)
    example = {
        "source_table": "npcs",
        "fields": ["id", "name"],
        "limit": 5,
    }
    print(json.dumps(handler({"body": json.dumps(example)}, None), indent=2))
