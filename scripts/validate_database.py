#!/usr/bin/env python3
"""
Database Schema Validation Script (Local + API)

Enhancements:
- Calls the db-schema-introspect Lambda REST API and compares its schema output
    with the expected schema parsed from local SQL DDL files under the Database/ directory.
- Keeps the existing direct DB validation checks (optional), using local JSON secrets.

Secrets file expected shape (example):
{
    "database": {
        "host": "...", "port": 5432, "username": "...", "password": "...", "dbname": "..."
    },
    "api": {
        "invoke_url": "https://<api-id>.execute-api.<region>.amazonaws.com/dev/db-schema",
        "api_key": "<value>",
        "basic_auth": {"username": "<user>", "password": "<pass>"}
    },
    "ddl_path": "./Database"  # optional override; defaults to repo Database/ folder
}
"""

import json
import re
import sys
import base64
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Optional imports; guarded to allow running only API/DDL mode without DB driver present
try:
        import psycopg2  # type: ignore
except Exception:  # pragma: no cover - optional
        psycopg2 = None

try:
        import requests  # type: ignore
except Exception as _e:
        requests = None

def load_local_secrets(secrets_file: Path) -> Dict:
    """Load secrets from a local JSON file."""
    try:
        data = json.loads(secrets_file.read_text(encoding="utf-8"))
        return data
    except FileNotFoundError:
        print(f"Secrets file not found: {secrets_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in secrets file {secrets_file}: {e}")
        sys.exit(1)

def get_database_credentials_from_local(secrets: Dict) -> Dict:
    """Extract DB credentials from the local secrets structure."""
    db = secrets.get("database")
    if not db:
        print("Missing 'database' section in secrets file. See secrets.local.json.example for structure.")
        sys.exit(1)
    required = ["host", "port", "username", "password", "dbname"]
    missing = [k for k in required if k not in db or db[k] in (None, "")]
    if missing:
        print(f"Missing required database fields in secrets file: {', '.join(missing)}")
        sys.exit(1)
    return db

def connect_to_database(credentials: Dict):
    """Connect to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=credentials['host'],
            port=credentials['port'],
            database=credentials['dbname'],
            user=credentials['username'],
            password=credentials['password']
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

def validate_basic_connection(cursor) -> bool:
    """Test basic database connectivity and PostgreSQL version."""
    try:
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"✓ Database connection successful")
        print(f"  PostgreSQL version: {version.split()[1]}")
        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False

def validate_timestamp_function(cursor) -> bool:
    """Verify the update_timestamp function exists."""
    try:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_proc p 
                JOIN pg_namespace n ON n.oid = p.pronamespace 
                WHERE n.nspname = 'public' AND p.proname = 'update_timestamp'
            );
        """)
        exists = cursor.fetchone()[0]
        if exists:
            print("✓ update_timestamp() function exists")
            return True
        else:
            print("✗ update_timestamp() function missing")
            return False
    except Exception as e:
        print(f"✗ Error checking timestamp function: {e}")
        return False

def validate_lookup_tables(cursor) -> bool:
    """Validate that all lookup tables exist and have data."""
    lookup_tables = [
        'tag_categories', 'age_categories', 'climate_zones', 'races',
        'settlement_types', 'location_types', 'terrain_types', 'languages',
        'social_statuses'
    ]
    
    all_valid = True
    
    for table in lookup_tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM public.{table};")
            count = cursor.fetchone()[0]
            if count > 0:
                print(f"✓ {table}: {count} records")
            else:
                print(f"✗ {table}: No records found")
                all_valid = False
        except Exception as e:
            print(f"✗ {table}: Error - {e}")
            all_valid = False
    
    return all_valid

def validate_core_tables(cursor) -> bool:
    """Validate that core entity tables exist."""
    core_tables = [
        'tags', 'resources', 'occupations', 'locations', 'nations',
        'settlements', 'npc_dispositions', 'npc_statuses', 'npcs',
        'organizations', 'businesses'
    ]
    
    all_valid = True
    
    for table in core_tables:
        try:
            cursor.execute(f"""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name = '{table}'
                );
            """)
            exists = cursor.fetchone()[0]
            if exists:
                cursor.execute(f"SELECT COUNT(*) FROM public.{table};")
                count = cursor.fetchone()[0]
                print(f"✓ {table}: Table exists ({count} records)")
            else:
                print(f"✗ {table}: Table missing")
                all_valid = False
        except Exception as e:
            print(f"✗ {table}: Error - {e}")
            all_valid = False
    
    return all_valid

def validate_foreign_keys(cursor) -> bool:
    """Validate that foreign key relationships are properly set up."""
    try:
        cursor.execute("""
            SELECT 
                tc.table_name, 
                tc.constraint_name,
                ccu.table_name AS referenced_table
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu 
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = 'public'
            ORDER BY tc.table_name;
        """)
        
        foreign_keys = cursor.fetchall()
        
        if foreign_keys:
            print(f"✓ Found {len(foreign_keys)} foreign key constraints:")
            for table, constraint, ref_table in foreign_keys[:10]:  # Show first 10
                print(f"  {table} → {ref_table}")
            if len(foreign_keys) > 10:
                print(f"  ... and {len(foreign_keys) - 10} more")
            return True
        else:
            print("✗ No foreign key constraints found")
            return False
            
    except Exception as e:
        print(f"✗ Error checking foreign keys: {e}")
        return False

def validate_indexes(cursor) -> bool:
    """Validate that important indexes exist."""
    try:
        cursor.execute("""
            SELECT 
                schemaname,
                tablename,
                indexname
            FROM pg_indexes 
            WHERE schemaname = 'public'
                AND indexname NOT LIKE '%_pkey'
            ORDER BY tablename, indexname;
        """)
        
        indexes = cursor.fetchall()
        
        if indexes:
            print(f"✓ Found {len(indexes)} custom indexes")
            # Check for some specific important indexes
            index_names = [idx[2] for idx in indexes]
            important_indexes = [
                'idx_npcs_name_search',
                'idx_tags_category',
                'idx_npcs_current_location'
            ]
            
            for idx in important_indexes:
                if idx in index_names:
                    print(f"  ✓ {idx}")
                else:
                    print(f"  ✗ {idx} missing")
            
            return True
        else:
            print("✗ No custom indexes found")
            return False
            
    except Exception as e:
        print(f"✗ Error checking indexes: {e}")
        return False

def validate_triggers(cursor) -> bool:
    """Validate that update triggers exist."""
    try:
        cursor.execute("""
            SELECT 
                event_object_table,
                trigger_name
            FROM information_schema.triggers
            WHERE trigger_schema = 'public'
                AND trigger_name LIKE '%updated_at%'
            ORDER BY event_object_table;
        """)
        
        triggers = cursor.fetchall()
        
        if triggers:
            print(f"✓ Found {len(triggers)} update timestamp triggers:")
            for table, trigger in triggers:
                print(f"  {table}")
            return True
        else:
            print("✗ No update timestamp triggers found")
            return False
            
    except Exception as e:
        print(f"✗ Error checking triggers: {e}")
        return False

def run_database_validation(db_credentials: Dict):
    """Run all database validation checks."""
    print("=" * 60)
    print("D&D AI Database Schema Validation")
    print("=" * 60)
    
    # Get credentials and connect
    print("\n1. Database Connection")
    print("-" * 30)
    conn = connect_to_database(db_credentials)
    cursor = conn.cursor()
    
    # Run validation tests
    tests = [
        ("2. Basic Connectivity", validate_basic_connection),
        ("3. Timestamp Function", validate_timestamp_function),
        ("4. Lookup Tables", validate_lookup_tables),
        ("5. Core Entity Tables", validate_core_tables),
        ("6. Foreign Key Relationships", validate_foreign_keys),
        ("7. Database Indexes", validate_indexes),
        ("8. Update Triggers", validate_triggers),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n{test_name}")
        print("-" * 30)
        try:
            result = test_func(cursor)
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ Test failed with exception: {e}")
            results.append((test_name, False))
    
    # Close connection
    cursor.close()
    conn.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{status:4} {test_name}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All validation tests passed! Database is ready for use.")
        return True
    else:
        print("⚠️  Some validation tests failed. Check the database setup.")
        return False

# ------------------------------
# API call and DDL parsing logic
# ------------------------------

def call_schema_api(url: str, api_key: str, username: str, password: str) -> Dict:
    """Call the db-schema-introspect API and return the parsed JSON body.

    Expects API Gateway with API Key and Basic Auth authorizer. Returns dict with keys:
    { ok, engine, schemas, tables: [ {schema,name,comment,columns:[{name,data_type,is_nullable,default,comment}]} ] }
    """
    auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    headers = {
        "x-api-key": api_key,
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }
    # No body needed; Lambda ignores event
    resp = requests.post(url, headers=headers, json={})
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:256]}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected API response shape (not a JSON object)")
    if not payload.get("ok"):
        raise RuntimeError(f"API returned error: {payload}")
    return payload


def load_expected_schema_from_sql(ddl_root: Path) -> Dict[Tuple[str, str], Dict]:
    """Scan the Database folder for CREATE TABLE statements and produce expected schema mapping.

    Returns mapping of (schema, table) -> {
        'schema': str, 'name': str, 'columns': { col_name: { 'data_type': str|None, 'is_nullable': bool|None, 'default': str|None } }
    }
    """
    if not ddl_root.exists():
        raise RuntimeError(f"DDL path not found: {ddl_root}")

    table_map: Dict[Tuple[str, str], Dict] = {}

    for sql_file in ddl_root.rglob("*.sql"):
        try:
            text = sql_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Remove block comments and line comments for simpler parsing
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
        text = re.sub(r"--.*?$", " ", text, flags=re.MULTILINE)

        for match in re.finditer(r"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?([\w\"]+\.)?([\w\"]+)\s*\(", text, flags=re.IGNORECASE):
            start = match.end()
            schema_part = match.group(2) or "public."
            schema = schema_part[:-1].strip('"') if schema_part else "public"
            table = match.group(3).strip('"')

            # Extract the balanced parentheses content of column/constraint list
            cols_block, end_idx = _extract_parentheses_block(text, start - 1)
            if cols_block is None:
                continue

            # Parse columns from block
            columns = _parse_columns_from_block(cols_block)
            key = (schema, table)
            if key not in table_map:
                table_map[key] = {"schema": schema, "name": table, "columns": {}}
            for col in columns:
                table_map[key]["columns"][col["name"]] = {
                    "data_type": col.get("data_type"),
                    "is_nullable": col.get("is_nullable"),
                    "default": col.get("default"),
                }

    return table_map


def _extract_parentheses_block(text: str, open_paren_idx: int) -> Tuple[Optional[str], Optional[int]]:
    """Given text and index of '(' (or just after), return content inside matching parentheses and end index.
    If not found, returns (None, None).
    """
    # Find the '(' to start
    i = open_paren_idx
    while i < len(text) and text[i] != '(':
        i += 1
    if i >= len(text) or text[i] != '(':
        return None, None
    depth = 0
    start = i + 1
    for j in range(i, len(text)):
        c = text[j]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return text[start:j], j
    return None, None


def _parse_columns_from_block(block: str) -> List[Dict[str, Optional[str]]]:
    """Parse column definitions from the inside of a CREATE TABLE (...) block.
    Ignores table-level constraints. Returns list of {name,data_type,is_nullable,default}.
    """
    # Split by commas at top-level (ignore parentheses in types/defaults)
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    for ch in block:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)

    columns: List[Dict[str, Optional[str]]] = []
    for raw_line in parts:
        line = re.sub(r"\s+", " ", raw_line.strip())
        if not line:
            continue
        # Skip table-level constraints
        if re.match(r"(?i)^(CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\b", line):
            continue

        # Extract column name (quoted or unquoted)
        m = re.match(r"^\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s+(.*)$", line)
        if not m:
            continue
        col_name = m.group(1)
        rest = m.group(2)

        # Tokenize rest to obtain data type until a known keyword
        tokens = rest.split()
        type_tokens: List[str] = []
        i = 0
        while i < len(tokens):
            t = tokens[i].lower()
            if t in {"constraint", "primary", "not", "null", "default", "unique", "references", "check"}:
                break
            type_tokens.append(tokens[i])
            i += 1
        data_type = ' '.join(type_tokens)

        # Detect NOT NULL
        is_nullable = None
        if re.search(r"(?i)\bNOT\s+NULL\b", rest):
            is_nullable = False
        elif re.search(r"(?i)\bNULL\b", rest):
            is_nullable = True

        # Detect DEFAULT ... (greedy to end; lightweight)
        default_expr = None
        mdef = re.search(r"(?i)\bDEFAULT\s+(.+)$", rest)
        if mdef:
            default_expr = mdef.group(1).strip().rstrip(',')

        columns.append({
            "name": col_name,
            "data_type": data_type if data_type else None,
            "is_nullable": is_nullable,
            "default": default_expr,
        })

    return columns


def compare_expected_vs_actual(expected: Dict[Tuple[str, str], Dict], api_schema: Dict) -> bool:
    """Compare expected DDL (from SQL files) with actual API schema. Print differences and return True if OK."""
    print("\n1. Loading API schema and building maps")
    tables_api = api_schema.get("tables") or []
    actual_tables: Dict[Tuple[str, str], Dict] = {}
    for t in tables_api:
        key = (t.get("schema"), t.get("name"))
        cols = {c.get("name"): c for c in (t.get("columns") or [])}
        actual_tables[key] = {"schema": t.get("schema"), "name": t.get("name"), "columns": cols}
    print(f"- API tables: {len(actual_tables)}")
    print(f"- Expected tables (from SQL): {len(expected)}")

    def norm_type(s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        x = s.strip().lower()
        # normalize common synonyms
        x = x.replace("character varying", "varchar")
        x = x.replace("timestamp with time zone", "timestamptz")
        x = x.replace("timestamp without time zone", "timestamp")
        x = re.sub(r"\s+", " ", x)
        return x

    def norm_default(s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        x = s.strip().rstrip(';').strip()
        # Normalize common casts and spacing
        x = re.sub(r"::[a-zA-Z_][a-zA-Z0-9_]*", "", x)
        x = re.sub(r"\s+", " ", x)
        return x.lower()

    print("\n2. Comparing table and column definitions")
    all_ok = True
    missing_tables: List[Tuple[str, str]] = []
    column_issues: List[str] = []

    # Check every expected table exists with expected columns
    for key, expected_tbl in sorted(expected.items()):
        if key not in actual_tables:
            missing_tables.append(key)
            all_ok = False
            continue
        act_tbl = actual_tables[key]
        # Compare columns
        for col_name, exp_col in expected_tbl["columns"].items():
            act_col = act_tbl["columns"].get(col_name)
            if not act_col:
                column_issues.append(f"{key[0]}.{key[1]}: missing column '{col_name}'")
                all_ok = False
                continue
            # Type
            e_type = norm_type(exp_col.get("data_type"))
            a_type = norm_type(act_col.get("data_type"))
            if e_type and a_type and e_type != a_type:
                column_issues.append(f"{key[0]}.{key[1]}:{col_name} type mismatch (expected '{e_type}', got '{a_type}')")
                all_ok = False
            # Nullability (only if specified in DDL parse)
            e_null = exp_col.get("is_nullable")
            a_null = act_col.get("is_nullable")
            if e_null is not None and a_null is not None and bool(e_null) != bool(a_null):
                column_issues.append(f"{key[0]}.{key[1]}:{col_name} nullability mismatch (expected {'NULL' if e_null else 'NOT NULL'}, got {'NULL' if a_null else 'NOT NULL'})")
                all_ok = False
            # Default (best-effort)
            e_def = norm_default(exp_col.get("default"))
            a_def = norm_default(act_col.get("default"))
            if e_def and a_def and e_def != a_def:
                column_issues.append(f"{key[0]}.{key[1]}:{col_name} default mismatch (expected '{e_def}', got '{a_def}')")
                all_ok = False

    # Report
    if missing_tables:
        print(f"✗ Missing tables in DB (per API): {len(missing_tables)}")
        for s, t in missing_tables[:20]:
            print(f"  - {s}.{t}")
        if len(missing_tables) > 20:
            print(f"  ... and {len(missing_tables)-20} more")
    else:
        print("✓ All expected tables are present")

    if column_issues:
        print(f"✗ Column mismatches: {len(column_issues)}")
        for msg in column_issues[:30]:
            print("  - " + msg)
        if len(column_issues) > 30:
            print(f"  ... and {len(column_issues)-30} more")
    else:
        print("✓ All expected columns match (type/nullability/default where parsed)")

    return all_ok


if __name__ == "__main__":
    # Usage: python validate_database.py <path-to-secrets.local.json>
    if len(sys.argv) != 2:
        print("Usage: python validate_database.py <path-to-secrets.local.json>")
        print("Example: python validate_database.py ./terraform/environments/dev/secrets.local.json")
        sys.exit(1)

    secrets_path = Path(sys.argv[1]).resolve()
    secrets = load_local_secrets(secrets_path)

    # 1) API-based schema introspection and DDL comparison
    print("\n" + "=" * 60)
    print("SCHEMA VS DDL VALIDATION (API → Database/ SQL)")
    print("=" * 60)
    api_ok = False
    try:
        api_cfg = secrets.get("api")
        if not api_cfg:
            raise RuntimeError("Missing 'api' section in secrets file; cannot call schema introspection API.")

        if requests is None:
            raise RuntimeError("'requests' package not available. Install with: pip install requests")

        invoke_url: str = api_cfg.get("invoke_url")
        api_key: str = api_cfg.get("api_key")
        basic_auth: Dict[str, str] = api_cfg.get("basic_auth") or {}
        if not invoke_url or not api_key or not basic_auth.get("username") or not basic_auth.get("password"):
            raise RuntimeError("API config requires invoke_url, api_key, and basic_auth {username,password}.")

        api_schema = call_schema_api(
            url=invoke_url,
            api_key=api_key,
            username=basic_auth["username"],
            password=basic_auth["password"],
        )

        ddl_root = Path(secrets.get("ddl_path") or (Path(__file__).resolve().parents[1] / "Database"))
        expected_schema = load_expected_schema_from_sql(ddl_root)

        api_ok = compare_expected_vs_actual(expected_schema, api_schema)
    except Exception as e:
        print(f"✗ API/DDL validation failed: {e}")
        api_ok = False

    # 2) Optional: direct DB checks if credentials present and driver available
    db_ok = True
    db_section = secrets.get("database")
    if db_section:
        if psycopg2 is None:
            print("⚠ psycopg2 not available; skipping direct DB checks.")
        else:
            db_credentials = get_database_credentials_from_local(secrets)
            db_ok = run_database_validation(db_credentials)
    else:
        print("(Skipping direct DB checks: no 'database' section in secrets)")

    overall = api_ok and db_ok
    print("\n" + "=" * 60)
    print(f"OVERALL RESULT: {'PASS' if overall else 'FAIL'}")
    print("=" * 60)
    sys.exit(0 if overall else 1)