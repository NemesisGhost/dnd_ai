# lambda-api module

Provisions a Lambda function fronted by API Gateway (REST) with:
- Lambda Request Authorizer (Basic Auth) backed by AWS Secrets Manager
- API Key and Usage Plan with throttling
- Optional CORS preflight (OPTIONS) support and default 4XX/5XX gateway responses with CORS headers
- Optional IAM DB auth permissions for the Lambda (rds:GenerateDbAuthToken and rds-db:connect)

Inputs: see variables.tf
Outputs: see outputs.tf
