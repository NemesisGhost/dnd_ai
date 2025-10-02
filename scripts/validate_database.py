#!/usr/bin/env python3
"""
Database Schema Validation Script
This script validates that the D&D AI database was created correctly.
Run after Terraform deployment to verify the Lambda function executed successfully.
"""

import boto3
import psycopg2
import json
import sys
from typing import Dict, List, Tuple

def get_database_credentials(secret_name: str) -> Dict:
    """Get database credentials from AWS Secrets Manager."""
    try:
        secrets_client = boto3.client('secretsmanager')
        response = secrets_client.get_secret_value(SecretId=secret_name)
        return json.loads(response['SecretString'])
    except Exception as e:
        print(f"Error getting database credentials: {e}")
        sys.exit(1)

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

def run_database_validation(secret_name: str):
    """Run all database validation checks."""
    print("=" * 60)
    print("D&D AI Database Schema Validation")
    print("=" * 60)
    
    # Get credentials and connect
    print("\n1. Database Connection")
    print("-" * 30)
    credentials = get_database_credentials(secret_name)
    conn = connect_to_database(credentials)
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

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate_database.py <secrets_manager_secret_name>")
        print("Example: python validate_database.py dnd-ai/dev/database/credentials")
        sys.exit(1)
    
    secret_name = sys.argv[1]
    success = run_database_validation(secret_name)
    sys.exit(0 if success else 1)