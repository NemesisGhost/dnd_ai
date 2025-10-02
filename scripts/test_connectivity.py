import json
import boto3
import os

def handler(event, context):
    """
    Test Lambda function to verify networking and Secrets Manager connectivity.
    """
    
    # Get database connection info from Secrets Manager
    secrets_client = boto3.client('secretsmanager')
    secret_arn = os.environ['SECRET_ARN']
    
    try:
        print("Testing Secrets Manager connectivity...")
        
        # Get database credentials
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        credentials = json.loads(response['SecretString'])
        
        print("✅ Successfully retrieved database credentials from Secrets Manager!")
        print(f"Host: {credentials['host']}")
        print(f"Port: {credentials['port']}")
        print(f"Database: {credentials['dbname']}")
        print(f"Username: {credentials['username']}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                "message": "✅ Networking fixes successful! Can connect to Secrets Manager.",
                "status": "success",
                "host": credentials['host'],
                "port": credentials['port'],
                "database": credentials['dbname']
            })
        }
        
    except Exception as e:
        error_msg = f"❌ Test failed: {str(e)}"
        print(error_msg)
        return {
            'statusCode': 500,
            'body': json.dumps({
                "message": error_msg,
                "status": "error"
            })
        }