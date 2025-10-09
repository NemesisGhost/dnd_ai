# Shared Query Utilities

This folder contains utilities to validate query specifications (JSON) against the project schema and to compile them into parameterized PostgreSQL SQL.

Contents:
- `query_spec_validator.py`: Loads `Database/query_json_schema.json` and validates payloads.
- `query_to_sql.py`: Compiles validated specs to SQL text + params.

CLI Helper:
- `src/tools/compile_query.py`: Validate and compile a JSON spec file.

Dependencies:
- `jsonschema` (install in your environment, or add to a Lambda Layer)

Quick start (PowerShell):
```powershell
pip install jsonschema
python -m src.tools.compile_query .\examples\npc_query.json
```

Notes:
- Identifier validation is pluggable; in production, provide a resolver that checks table/column names against your introspected schema and returns safely quoted identifiers.
- one-to-many and many-to-many relationships currently produce flat rows; clients can group/aggregate as needed. JSON aggregation can be added later.
