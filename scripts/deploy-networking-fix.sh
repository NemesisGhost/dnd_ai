#!/usr/bin/env bash
# Database Module Networking Fix Deployment Script

set -e

echo "🔧 Applying Database Module Networking Fixes..."

# Change to terraform directory
cd "$(dirname "$0")"

# Check if we're in the right directory
if [ ! -f "main.tf" ]; then
    echo "❌ Error: main.tf not found. Make sure you're in the database module directory."
    exit 1
fi

echo "📋 Planning Terraform changes..."
terraform plan -out=networking-fix.tfplan

echo ""
echo "📊 Review the plan above. The following resources should be created/modified:"
echo "  ✅ VPC Endpoints for Secrets Manager and KMS"
echo "  ✅ Security groups for Lambda and VPC endpoints"
echo "  ✅ Updated Lambda function with new security group"
echo "  ✅ Optional NAT Gateway resources (if enabled)"

echo ""
read -p "🤔 Do you want to apply these changes? (y/N): " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 Applying changes..."
    terraform apply networking-fix.tfplan
    
    echo ""
    echo "✅ Networking fixes applied successfully!"
    echo ""
    echo "📝 Next steps:"
    echo "  1. Wait a few minutes for VPC endpoints to be fully available"
    echo "  2. Test the Lambda function from AWS Console"
    echo "  3. Check CloudWatch logs if issues persist"
    echo ""
    echo "🔍 Troubleshooting resources:"
    echo "  - VPC Endpoints: Check AWS Console > VPC > Endpoints"
    echo "  - Lambda logs: CloudWatch > Log Groups > /aws/lambda/[function-name]"
    echo "  - Security groups: EC2 > Security Groups"
    
    # Clean up plan file
    rm -f networking-fix.tfplan
else
    echo "❌ Deployment cancelled. Cleaning up plan file..."
    rm -f networking-fix.tfplan
fi