#!/usr/bin/env python3
"""
Script to build the database initialization Lambda deployment package.
This script packages the Lambda function with all SQL scripts embedded.
"""

import os
import sys
import zipfile
import shutil
from pathlib import Path

def build_lambda_package():
    """Build the Lambda deployment package with embedded SQL scripts."""
    
    # Paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    database_dir = project_root / "Database"
    terraform_module_dir = project_root / "terraform" / "modules" / "database"
    lambda_dir = script_dir / "lambda_build"
    zip_path = terraform_module_dir / "db_init_lambda.zip"
    
    print(f"Script directory: {script_dir}")
    print(f"Database directory: {database_dir}")
    print(f"Lambda build directory: {lambda_dir}")
    
    # Clean and create build directory
    if lambda_dir.exists():
        shutil.rmtree(lambda_dir)
    lambda_dir.mkdir()
    
    # Copy the Lambda function
    lambda_py_content = '''
import json
import boto3
import psycopg2
import os
import sys

def handler(event, context):
    """
    Lambda function to initialize the D&D AI database with schema and data.
    This function runs all SQL scripts in the correct order.
    """
    
    # Get database connection info from Secrets Manager
    secrets_client = boto3.client('secretsmanager')
    secret_arn = os.environ['SECRET_ARN']
    
    try:
        # Get database credentials
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        credentials = json.loads(response['SecretString'])
        
        # Connect to database
        conn = psycopg2.connect(
            host=credentials['host'],
            port=credentials['port'],
            database=credentials['dbname'],
            user=credentials['username'],
            password=credentials['password']
        )
        
        # Enable autocommit for DDL operations
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Connected to database successfully")
        
        # SQL scripts in execution order (dependencies considered)
        sql_files = [
            # Basic setup
            ("create_timestamp_function", create_timestamp_function_sql()),
            
            # Level 1: Lookup tables (no dependencies)
            ("lookups/tag_categories", get_sql_content("lookups/tag_categories.sql")),
            ("lookups/age_categories", get_sql_content("lookups/age_categories.sql")),
            ("lookups/climate_zones", get_sql_content("lookups/climate_zones.sql")),
            ("lookups/races", get_sql_content("lookups/races.sql")),
            ("lookups/settlement_types", get_sql_content("lookups/settlement_types.sql")),
            ("lookups/location_types", get_sql_content("lookups/location_types.sql")),
            ("lookups/terrain_types", get_sql_content("lookups/terrain_types.sql")),
            ("lookups/languages", get_sql_content("lookups/languages.sql")),
            ("lookups/social_statuses", get_sql_content("lookups/social_statuses.sql")),
            
            # Level 2: Core shared entities that depend on lookups
            ("tags", get_sql_content("tags.sql")),
            ("world/resources", get_sql_content("world/resources.sql")),
            ("world/occupations", get_sql_content("world/occupations.sql")),
            
            # Level 3: Geographic entities
            ("locations/locations", get_sql_content("locations/locations.sql")),
            ("world/nations", get_sql_content("world/nations.sql")),
            ("settlements/settlements", get_sql_content("settlements/settlements.sql")),
            
            # Level 4: NPC support tables
            ("npcs/npc_dispositions", get_sql_content("npcs/npc_dispositions.sql")),
            ("npcs/npc_statuses", get_sql_content("npcs/npc_statuses.sql")),
            
            # Level 5: Main entity tables
            ("npcs/npcs", get_sql_content("npcs/npcs.sql")),
            ("organizations/organizations", get_sql_content("organizations/organizations.sql")),
            ("business/businesses", get_sql_content("business/businesses.sql")),
        ]
        
        executed_files = []
        failed_files = []
        
        for sql_name, sql_content in sql_files:
            try:
                if sql_content:
                    print(f"Executing {sql_name}...")
                    cursor.execute(sql_content)
                    executed_files.append(sql_name)
                    print(f"Successfully executed {sql_name}")
                else:
                    print(f"Warning: No content found for {sql_name}")
                    
            except Exception as e:
                error_msg = f"Error executing {sql_name}: {str(e)}"
                print(error_msg)
                failed_files.append({"file": sql_name, "error": str(e)})
                # Continue with next file rather than failing completely
        
        # Close database connection
        cursor.close()
        conn.close()
        
        response_body = {
            "message": "Database initialization completed",
            "executed_files": len(executed_files),
            "total_files": len(sql_files),
            "failed_files": failed_files,
            "status": "success" if len(failed_files) == 0 else "partial_success"
        }
        
        print(f"Database initialization completed. Executed: {len(executed_files)}, Failed: {len(failed_files)}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(response_body)
        }
        
    except Exception as e:
        error_msg = f"Database initialization failed: {str(e)}"
        print(error_msg)
        return {
            'statusCode': 500,
            'body': json.dumps({
                "message": error_msg,
                "status": "error"
            })
        }

def create_timestamp_function_sql():
    """Return the timestamp function SQL."""
    return """
    -- Create the update_timestamp function used by triggers
    CREATE OR REPLACE FUNCTION update_timestamp()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# SQL Content embedded in the function
SQL_CONTENT = {
'''
    
    # Read SQL files and embed them
    sql_files_to_read = [
        "lookups/tag_categories.sql",
        "tags.sql",
        "lookups/age_categories.sql",
        "lookups/climate_zones.sql", 
        "lookups/races.sql",
        "lookups/settlement_types.sql",
        "lookups/location_types.sql",
        "lookups/terrain_types.sql",
        "lookups/languages.sql",
        "lookups/social_statuses.sql",
        "world/resources.sql",
        "world/occupations.sql",
        "locations/locations.sql",
        "world/nations.sql",
        "settlements/settlements.sql",
        "npcs/npc_dispositions.sql",
        "npcs/npc_statuses.sql",
        "npcs/npcs.sql",
        "organizations/organizations.sql",
        "business/businesses.sql"
    ]
    
    for sql_file in sql_files_to_read:
        sql_path = database_dir / sql_file
        if sql_path.exists():
            with open(sql_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Escape quotes and add to lambda content
                escaped_content = content.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                lambda_py_content += f'    "{sql_file}": """{content}""",\n'
        else:
            print(f"Warning: SQL file not found: {sql_path}")
            lambda_py_content += f'    "{sql_file}": None,  # File not found\n'
    
    lambda_py_content += '''
}

def get_sql_content(file_path):
    """Get SQL content for a given file path."""
    return SQL_CONTENT.get(file_path)
'''
    
    # Write the Lambda function
    with open(lambda_dir / "index.py", 'w', encoding='utf-8') as f:
        f.write(lambda_py_content)
    
    # Create requirements.txt for psycopg2
    with open(lambda_dir / "requirements.txt", 'w') as f:
        f.write("psycopg2-binary==2.9.7\n")
    
    # Create the zip file
    if zip_path.exists():
        zip_path.unlink()
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add the Lambda function
        zipf.write(lambda_dir / "index.py", "index.py")
        zipf.write(lambda_dir / "requirements.txt", "requirements.txt")
    
    print(f"Lambda package created: {zip_path}")
    print(f"Package size: {zip_path.stat().st_size / 1024:.1f} KB")
    
    # Clean up
    shutil.rmtree(lambda_dir)
    
    return zip_path

if __name__ == "__main__":
    build_lambda_package()