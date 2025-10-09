Query Runner Lambda

Accepts a JSON query spec, validates against the JSON Schema, compiles to SQL,
executes against PostgreSQL (RDS via IAM auth), and returns rows as JSON.

Env vars:
- DB_HOST, DB_PORT, DB_NAME, DB_USER
- QUERY_SCHEMA_PATH (optional; defaults to the bundled Database/query_json_schema.json)

Build artifacts:
- Function: scripts/build_lambda.ps1 -FunctionName query_runner
- Layer:    scripts/build_layer.ps1 -FunctionName query_runner

API Contract:
- Request body: the JSON spec defined by Database/query_json_schema.json
- Response: { ok, row_count, columns, rows, sql, params }