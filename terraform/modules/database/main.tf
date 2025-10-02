# =====================================================
# D&D AI Database Module - PostgreSQL on AWS RDS
# =====================================================
# This module creates a PostgreSQL database with associated 
# networking, security, and secrets management resources.
# 
# Components are organized in separate files:
# - networking.tf: VPC, subnets, security groups, endpoints
# - secrets.tf: KMS encryption and Secrets Manager
# - rds.tf: PostgreSQL database and parameter groups
# =====================================================

# Note: This main.tf file serves as the entry point and 
# documentation for the module. The actual resources are 
# defined in the component-specific files listed above.