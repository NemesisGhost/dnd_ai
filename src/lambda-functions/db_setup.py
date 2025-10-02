import json
import os
import boto3
import psycopg2
import logging
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """
    Lambda function to initialize the PostgreSQL database with schema and initial data.
    """
    try:
        # Get database connection info from Secrets Manager
        secret_arn = os.environ['SECRET_ARN']
        logger.info(f"Retrieving database credentials from: {secret_arn}")
        
        # Initialize boto3 client for Secrets Manager
        secrets_client = boto3.client('secretsmanager')
        
        # Get the secret value
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response['SecretString'])
        
        # Extract connection parameters
        db_host = secret['host']
        db_port = secret['port']
        db_name = secret['dbname']
        db_user = secret['username']
        db_password = secret['password']
        
        logger.info(f"Connecting to database: {db_host}:{db_port}/{db_name}")
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            database=db_name,
            user=db_user,
            password=db_password
        )
        
        # Create a cursor
        cur = conn.cursor()
        
        # Test the connection
        cur.execute("SELECT version();")
        version = cur.fetchone()
        logger.info(f"Connected to PostgreSQL: {version[0]}")
        
        # Create a simple test table to verify the connection works
        cur.execute("""
            CREATE TABLE IF NOT EXISTS connection_test (
                id SERIAL PRIMARY KEY,
                test_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Insert a test record
        cur.execute("""
            INSERT INTO connection_test (test_message) 
            VALUES ('Database initialization successful!');
        """)
        
        # Commit the transaction
        conn.commit()
        
        # Close the cursor and connection
        cur.close()
        conn.close()
        
        logger.info("Database initialization completed successfully!")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Database initialization completed successfully!',
                'database': f"{db_host}:{db_port}/{db_name}",
                'postgresql_version': version[0]
            })
        }
        
    except ClientError as e:
        logger.error(f"AWS Secrets Manager error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Failed to retrieve database credentials',
                'details': str(e)
            })
        }
        
    except psycopg2.Error as e:
        logger.error(f"PostgreSQL error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Database connection or query failed',
                'details': str(e)
            })
        }
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Unexpected error occurred',
                'details': str(e)
            })
        }