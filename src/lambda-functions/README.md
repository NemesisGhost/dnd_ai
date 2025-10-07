# Lambda Functions

Structure:
- Each function lives under `src/lambda-functions/<function_name>`.
- Python entrypoint must be `app.py` with `handler(event, context)`.

Build:
- Use `scripts/build_lambda.ps1 -FunctionName <function_name>` to generate `dist/lambdas/<function_name>.zip` for Terraform.

Runtime dependencies:
- Put a `layer/requirements.txt` next to the function (e.g., `src/lambda-functions/<name>/layer/requirements.txt`).
- Build a layer zip with `scripts/build_layer.ps1 -FunctionName <name>`; artifact is emitted as `dist/layers/<name>-python-deps.zip`.
- Attach the resulting layer ARN to the function in Terraform.

Functions:
- db_schema_introspect: Introspect PostgreSQL (RDS) and return schemas, tables, columns, and comments. Requires env vars: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, optional DB_SCHEMAS.
