# =====================================================
# Networking Resources (VPC, Subnets, Security Groups)
# =====================================================

# Data source for availability zones
data "aws_availability_zones" "available" {
  state = "available"
}

# VPC for database (if not provided)
resource "aws_vpc" "main" {
  count = var.vpc_id == null ? 1 : 0

  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "${var.project_name}-${var.environment}-vpc"
    Project     = var.project_name
    Environment = var.environment
  }
}

# Internet Gateway (if creating VPC)
resource "aws_internet_gateway" "main" {
  count = var.vpc_id == null ? 1 : 0

  vpc_id = aws_vpc.main[0].id

  tags = {
    Name        = "${var.project_name}-${var.environment}-igw"
    Project     = var.project_name
    Environment = var.environment
  }
}

# Private subnets for database
resource "aws_subnet" "private" {
  count = 2

  vpc_id            = var.vpc_id != null ? var.vpc_id : aws_vpc.main[0].id
  cidr_block        = var.vpc_id != null ? var.private_subnet_cidrs[count.index] : cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name        = "${var.project_name}-${var.environment}-private-subnet-${count.index + 1}"
    Project     = var.project_name
    Environment = var.environment
    Type        = "Private"
  }
}

# Public subnets (if creating VPC)
resource "aws_subnet" "public" {
  count = var.vpc_id == null ? 2 : 0

  vpc_id                  = aws_vpc.main[0].id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name        = "${var.project_name}-${var.environment}-public-subnet-${count.index + 1}"
    Project     = var.project_name
    Environment = var.environment
    Type        = "Public"
  }
}

# NAT Gateway for private subnet internet access (if creating VPC and enabled)
resource "aws_eip" "nat" {
  count = var.vpc_id == null && var.use_nat_gateway ? 1 : 0

  domain = "vpc"
  depends_on = [aws_internet_gateway.main]

  tags = {
    Name        = "${var.project_name}-${var.environment}-nat-eip"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_nat_gateway" "main" {
  count = var.vpc_id == null && var.use_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name        = "${var.project_name}-${var.environment}-nat-gw"
    Project     = var.project_name
    Environment = var.environment
  }

  depends_on = [aws_internet_gateway.main]
}

# Route table for private subnets
resource "aws_route_table" "private" {
  vpc_id = var.vpc_id != null ? var.vpc_id : aws_vpc.main[0].id

  # Add route to NAT Gateway for internet access (if creating VPC and NAT Gateway enabled)
  dynamic "route" {
    for_each = var.vpc_id == null && var.use_nat_gateway ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.main[0].id
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-private-rt"
    Project     = var.project_name
    Environment = var.environment
  }
}

# Route table associations for private subnets
resource "aws_route_table_association" "private" {
  count = 2

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# Route table for public subnets (if creating VPC)
resource "aws_route_table" "public" {
  count = var.vpc_id == null ? 1 : 0

  vpc_id = aws_vpc.main[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main[0].id
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-public-rt"
    Project     = var.project_name
    Environment = var.environment
  }
}

# Route table associations for public subnets (if creating VPC)
resource "aws_route_table_association" "public" {
  count = var.vpc_id == null ? 2 : 0

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

# DB subnet group
resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-${var.environment}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name        = "${var.project_name}-${var.environment}-db-subnet-group"
    Project     = var.project_name
    Environment = var.environment
  }
}

# Security group for database
resource "aws_security_group" "db" {
  name_prefix = "${var.project_name}-${var.environment}-db-"
  vpc_id      = var.vpc_id != null ? var.vpc_id : aws_vpc.main[0].id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
    description = "PostgreSQL access from allowed CIDR blocks"
  }

  # Allow access from application security groups if provided
  dynamic "ingress" {
    for_each = var.allowed_security_group_ids
    content {
      from_port       = 5432
      to_port         = 5432
      protocol        = "tcp"
      security_groups = [ingress.value]
      description     = "PostgreSQL access from application"
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound traffic"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-db-sg"
    Project     = var.project_name
    Environment = var.environment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# VPC Endpoints for AWS services (more cost-effective than NAT Gateway)
resource "aws_vpc_endpoint" "secretsmanager" {
  count = var.create_vpc_endpoints ? 1 : 0

  vpc_id              = var.vpc_id != null ? var.vpc_id : aws_vpc.main[0].id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]

  private_dns_enabled = true

  tags = {
    Name        = "${var.project_name}-${var.environment}-secretsmanager-endpoint"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_vpc_endpoint" "kms" {
  count = var.create_vpc_endpoints ? 1 : 0

  vpc_id              = var.vpc_id != null ? var.vpc_id : aws_vpc.main[0].id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.kms"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]

  private_dns_enabled = true

  tags = {
    Name        = "${var.project_name}-${var.environment}-kms-endpoint"
    Project     = var.project_name
    Environment = var.environment
  }
}

# Security group for VPC endpoints
resource "aws_security_group" "vpc_endpoints" {
  count = var.create_vpc_endpoints ? 1 : 0

  name_prefix = "${var.project_name}-${var.environment}-vpc-endpoints-"
  vpc_id      = var.vpc_id != null ? var.vpc_id : aws_vpc.main[0].id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_id != null ? "10.0.0.0/16" : var.vpc_cidr]
    description = "HTTPS access from VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound traffic"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-vpc-endpoints-sg"
    Project     = var.project_name
    Environment = var.environment
  }

  lifecycle {
    create_before_destroy = true
  }
}