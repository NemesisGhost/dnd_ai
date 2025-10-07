"""
AWS Lambda: db_schema_introspect

Purpose: Return a JSON payload describing all tables in the configured PostgreSQL
RDS database, including columns and comments. Designed to be called via API Gateway
and to be MCP-friendly (simple JSON contract, deterministic output).

Dependencies: pg8000 (provided via Lambda Layer 'db-deps')

Environment variables required:
- DB_HOST: RDS hostname
- DB_PORT: RDS port (default: 5432)
- DB_NAME: Database name
- DB_USER: Database user
- DB_PASSWORD: Database password (or use AWS Secrets Manager via extension in future)
- DB_SCHEMAS: Optional comma-separated list of schemas to include (default: public)

Response contract:
{
  "ok": true,
  "engine": "postgres",
  "schemas": ["public"],
  "tables": [
    {
      "schema": "public",
      "name": "npcs",
      "comment": "...",
      "columns": [
        {"name": "id", "data_type": "uuid", "is_nullable": false, "default": "gen_random_uuid()", "comment": null},
        ...
      ]
    }
  ]
}

When an error occurs, returns statusCode 500 with payload:
{"ok": false, "error": "..."}
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pg8000  # provided by Lambda Layer
import boto3
import ssl


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

    # pg8000.connect returns a DB-API 2.0 connection
    return pg8000.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=token,
        ssl_context=ssl_ctx,
        timeout=15,
    )


def _fetch_schema_metadata(conn, schemas: List[str]) -> Dict[str, Any]:
    # Tables with comments
    tables_sql = """
        SELECT
            n.nspname AS schema,
            c.relname AS table_name,
            obj_description(c.oid, 'pg_class') AS table_comment
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r','p')
          AND n.nspname = ANY(%s)
        ORDER BY n.nspname, c.relname;
    """

    # Columns with details and comments
    columns_sql = """
        SELECT
            n.nspname AS schema,
            c.relname AS table_name,
            a.attname AS column_name,
            pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
            (NOT a.attnotnull) AS is_nullable,
            pg_get_expr(ad.adbin, ad.adrelid) AS column_default,
            col_description(a.attrelid, a.attnum) AS column_comment,
            a.attnum AS ordinal_position
        FROM pg_attribute a
        JOIN pg_class c ON a.attrelid = c.oid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
        WHERE a.attnum > 0
          AND NOT a.attisdropped
          AND c.relkind IN ('r','p')
          AND n.nspname = ANY(%s)
        ORDER BY n.nspname, c.relname, a.attnum;
    """

    with conn.cursor() as cur:
        cur.execute(tables_sql, (schemas,))
        tables = cur.fetchall()
        # rows: schema, table_name, table_comment

        cur.execute(columns_sql, (schemas,))
        columns = cur.fetchall()
        # rows: schema, table_name, column_name, data_type, is_nullable, column_default, column_comment, ordinal_position

    # Build map {(schema, table): table_info}
    table_map: Dict[tuple, Dict[str, Any]] = {}
    for schema, table_name, table_comment in tables:
        table_map[(schema, table_name)] = {
            "schema": schema,
            "name": table_name,
            "comment": table_comment,
            "columns": [],
        }

    for (
        schema,
        table_name,
        column_name,
        data_type,
        is_nullable,
        column_default,
        column_comment,
        ordinal_position,
    ) in columns:
        key = (schema, table_name)
        if key not in table_map:
            # In rare cases (e.g., race conditions), ensure table exists in map
            table_map[key] = {
                "schema": schema,
                "name": table_name,
                "comment": None,
                "columns": [],
            }
        table_map[key]["columns"].append(
            {
                "name": column_name,
                "data_type": data_type,
                "is_nullable": bool(is_nullable),
                "default": column_default,
                "comment": column_comment,
                "ordinal_position": ordinal_position,
            }
        )

    # Sort columns by ordinal, drop ordinal in final output
    for v in table_map.values():
        v["columns"].sort(key=lambda c: c.get("ordinal_position", 0))
        for c in v["columns"]:
            c.pop("ordinal_position", None)

    # Return list sorted by schema, name
    tables_list = sorted(table_map.values(), key=lambda t: (t["schema"], t["name"]))
    return {
        "ok": True,
        "engine": "postgres",
        "schemas": schemas,
        "tables": tables_list,
    }


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


def handler(event, context):  # AWS Lambda entrypoint
    try:
        schemas_env = os.getenv("DB_SCHEMAS", "public")
        schemas = [s.strip() for s in schemas_env.split(",") if s.strip()]

        conn = _db_connect()
        try:
            payload = _fetch_schema_metadata(conn, schemas)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return _json_response(payload, 200)

    except Exception as e:
        # Avoid leaking secrets; include class and message only.
        return _json_response({"ok": False, "error": f"{e.__class__.__name__}: {e}"}, 500)


if __name__ == "__main__":
    # Simple local test harness (requires env vars and network access to DB)
    print(json.dumps(handler({}, None), indent=2))
