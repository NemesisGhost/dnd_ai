#!/usr/bin/env python3
"""
Script to prepare the database initialization Lambda function.
This script packages the Lambda function with all SQL files.
"""

import os
import sys
import zipfile
import shutil
from pathlib import Path

def main():
    """Main function to prepare the Lambda deployment package."""
    
    # Get project root directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    database_dir = project_root / "Database"
    module_dir = project_root / "terraform" / "modules" / "database"
    
    print(f"Project root: {project_root}")
    print(f"Database dir: {database_dir}")
    print(f"Module dir: {module_dir}")
    
    # Create temporary directory for Lambda package
    temp_dir = module_dir / "lambda_package"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    
    try:
        # Copy Lambda function
        lambda_file = module_dir / "db_init_lambda.py"
        shutil.copy2(lambda_file, temp_dir / "index.py")
        
        # Install psycopg2 for Lambda
        print("Installing psycopg2-binary for Lambda...")
        os.system(f"pip install psycopg2-binary -t {temp_dir}")
        
        # Copy all SQL files
        sql_dir = temp_dir / "sql"
        sql_dir.mkdir()
        
        # Copy all .sql files recursively
        for sql_file in database_dir.rglob("*.sql"):
            # Get relative path from database directory
            rel_path = sql_file.relative_to(database_dir)
            
            # Create target directory if needed
            target_file = sql_dir / rel_path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy file
            shutil.copy2(sql_file, target_file)
            print(f"Copied: {rel_path}")
        
        # Update Lambda function to read from embedded SQL files
        update_lambda_function(temp_dir / "index.py", sql_dir)
        
        # Create ZIP file
        zip_path = module_dir / "db_init_lambda.zip"
        if zip_path.exists():
            zip_path.unlink()
            
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in temp_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(temp_dir)
                    zipf.write(file_path, arcname)
                    
        print(f"Created Lambda package: {zip_path}")
        print(f"Package size: {zip_path.stat().st_size / 1024 / 1024:.2f} MB")
        
    finally:
        # Clean up temporary directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

def update_lambda_function(lambda_file_path, sql_dir):
    """Update the Lambda function to read SQL files from the package."""
    
    # Read the current Lambda function
    with open(lambda_file_path, 'r') as f:
        content = f.read()
    
    # Replace the get_sql_content function
    new_get_sql_content = '''def get_sql_content(file_path):
    """
    Get SQL content for a given file path from embedded files.
    """
    
    if file_path == "create_timestamp_function.sql":
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
    
    try:
        # Read SQL file from embedded directory
        sql_file_path = Path(__file__).parent / "sql" / file_path
        if sql_file_path.exists():
            with open(sql_file_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            print(f"Warning: SQL file not found: {file_path}")
            return None
    except Exception as e:
        print(f"Error reading SQL file {file_path}: {str(e)}")
        return None'''
    
    # Replace the function in the content
    start_marker = "def get_sql_content(file_path):"
    end_marker = "    return None"
    
    start_idx = content.find(start_marker)
    if start_idx != -1:
        # Find the end of the function
        lines = content[start_idx:].split('\n')
        end_idx = start_idx
        for i, line in enumerate(lines):
            if i > 0 and line and not line.startswith('    ') and not line.startswith('\t'):
                end_idx = start_idx + len('\n'.join(lines[:i]))
                break
        else:
            end_idx = len(content)
        
        # Replace the function
        new_content = content[:start_idx] + new_get_sql_content + content[end_idx:]
        
        # Add Path import at the top
        if "from pathlib import Path" not in new_content:
            import_idx = new_content.find("import os")
            if import_idx != -1:
                new_content = new_content[:import_idx] + "from pathlib import Path\n" + new_content[import_idx:]
        
        # Write updated content
        with open(lambda_file_path, 'w') as f:
            f.write(new_content)

if __name__ == "__main__":
    main()