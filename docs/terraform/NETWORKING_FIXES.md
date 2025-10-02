# Database Module Networking Fixes

## Problem
The Lambda function for database initialization was failing with the error:
```
Database initialization failed: Could not connect to the endpoint URL: "https://secretsmanager.us-east-1.amazonaws.com"
```

## Root Cause
The Lambda function is deployed in a VPC's private subnets but lacks internet connectivity to reach AWS services like Secrets Manager and KMS. When a Lambda function is in a VPC, it loses access to the internet unless explicitly configured.

## Solutions Implemented

### 1. VPC Endpoints (Recommended - Default)
- **Cost-effective**: No data transfer charges for AWS service calls
- **Secure**: Traffic stays within AWS network
- **Limited scope**: Only provides access to specific AWS services

**Services configured:**
- Secrets Manager VPC Endpoint
- KMS VPC Endpoint

**Variables:**
- `create_vpc_endpoints = true` (default)

### 2. NAT Gateway (Alternative)
- **Higher cost**: Charges for NAT Gateway and data transfer
- **Full internet access**: Allows access to any internet resources
- **More bandwidth**: Better for high-throughput scenarios

**Variables:**
- `use_nat_gateway = true`
- `create_vpc_endpoints = false` (when using NAT Gateway)

## Configuration Options

### Use VPC Endpoints (Default - Recommended)
```hcl
module "database" {
  source = "./modules/database"
  
  # Default settings - VPC endpoints enabled
  create_vpc_endpoints = true
  use_nat_gateway     = false
  
  # Other variables...
}
```

### Use NAT Gateway
```hcl
module "database" {
  source = "./modules/database"
  
  # Use NAT Gateway instead
  create_vpc_endpoints = false
  use_nat_gateway     = true
  
  # Other variables...
}
```

### Disable Both (Lambda outside VPC)
If you don't need the Lambda in VPC, you can modify the Lambda configuration to remove the `vpc_config` block entirely.

## Security Groups Updated

1. **Lambda Security Group**: Created separate security group for Lambda with specific egress rules
2. **VPC Endpoints Security Group**: Allows HTTPS access from within VPC
3. **Database Security Group**: Unchanged - still restricts access to port 5432

## Deployment Steps

1. **Update Terraform configuration** with the networking fixes
2. **Run terraform plan** to see the changes
3. **Run terraform apply** to implement the fixes
4. **Test the Lambda function** again from AWS console

## Cost Considerations

- **VPC Endpoints**: ~$7-15/month per endpoint
- **NAT Gateway**: ~$45/month + data transfer costs
- **Recommendation**: Use VPC endpoints for this use case

## Troubleshooting

If issues persist after applying these fixes:

1. Check VPC endpoint DNS resolution
2. Verify security group rules
3. Check Lambda function logs in CloudWatch
4. Ensure Lambda execution role has proper permissions

## Future Enhancements

Consider adding VPC endpoints for other AWS services as needed:
- CloudWatch Logs
- S3 (for document processing)
- Lambda (for function-to-function calls)