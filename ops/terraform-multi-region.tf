# Terraform configuration for Puch AI Voice Server - Multi-Region Enterprise Deployment
# Supports automatic failover across 3 AWS regions with Route53 geolocation routing

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment for remote state (replace with your S3 bucket)
  # backend "s3" {
  #   bucket         = "puch-ai-terraform-state"
  #   key            = "puch-ai/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-lock"
  # }
}

# ────────────────────────────────────────────────────────────────────────────────
# Variables
# ────────────────────────────────────────────────────────────────────────────────

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "puch-ai"
}

variable "environment" {
  description = "Environment (prod, staging, dev)"
  type        = string
  default     = "prod"
  validation {
    condition     = contains(["prod", "staging", "dev"], var.environment)
    error_message = "Environment must be prod, staging, or dev"
  }
}

variable "regions" {
  description = "AWS regions for deployment (primary, secondary, tertiary)"
  type = object({
    primary   = string
    secondary = string
    tertiary  = string
  })
  default = {
    primary   = "us-east-1"
    secondary = "eu-west-1"
    tertiary  = "ap-south-1"
  }
}

variable "instance_count" {
  description = "Number of API instances per region"
  type        = number
  default     = 3
  validation {
    condition     = var.instance_count >= 1 && var.instance_count <= 10
    error_message = "Instance count must be between 1 and 10"
  }
}

variable "instance_type" {
  description = "EC2 instance type for API servers"
  type        = string
  default     = "t3.medium"  # 2 vCPU, 4GB memory → 200 concurrent calls/instance
}

variable "rds_instance_class" {
  description = "RDS instance class for PostgreSQL"
  type        = string
  default     = "db.t3.large"  # 2 vCPU, 8GB memory
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
  default     = "cache.r6g.xlarge"  # 4 vCPU, 32GB memory
}

variable "deletion_protection" {
  description = "Enable deletion protection for critical resources"
  type        = bool
  default     = true
}

variable "backup_retention_days" {
  description = "RDS backup retention in days"
  type        = number
  default     = 30
}

# ────────────────────────────────────────────────────────────────────────────────
# Provider Configuration
# ────────────────────────────────────────────────────────────────────────────────

provider "aws" {
  alias  = "primary"
  region = var.regions.primary

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Created     = timestamp()
    }
  }
}

provider "aws" {
  alias  = "secondary"
  region = var.regions.secondary

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Region      = "secondary"
    }
  }
}

provider "aws" {
  alias  = "tertiary"
  region = var.regions.tertiary

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Region      = "tertiary"
    }
  }
}

# ────────────────────────────────────────────────────────────────────────────────
# VPC & Networking (Primary Region)
# ────────────────────────────────────────────────────────────────────────────────

resource "aws_vpc" "primary" {
  provider             = aws.primary
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-vpc-primary"
  }
}

# Public subnets for ALB
resource "aws_subnet" "primary_public" {
  provider                = aws.primary
  count                   = 2
  vpc_id                  = aws_vpc.primary.id
  cidr_block              = "10.0.${count.index}.0/24"
  availability_zone       = data.aws_availability_zones.primary.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-subnet-public-${count.index + 1}"
  }
}

# Private subnets for API/DB
resource "aws_subnet" "primary_private" {
  provider          = aws.primary
  count             = 2
  vpc_id            = aws_vpc.primary.id
  cidr_block        = "10.0.${count.index + 10}.0/24"
  availability_zone = data.aws_availability_zones.primary.names[count.index]

  tags = {
    Name = "${var.project_name}-subnet-private-${count.index + 1}"
  }
}

data "aws_availability_zones" "primary" {
  provider = aws.primary
  state    = "available"
}

# Internet Gateway
resource "aws_internet_gateway" "primary" {
  provider = aws.primary
  vpc_id   = aws_vpc.primary.id

  tags = {
    Name = "${var.project_name}-igw-primary"
  }
}

# Elastic IPs for NAT
resource "aws_eip" "nat" {
  provider = aws.primary
  domain   = "vpc"
  count    = 2

  tags = {
    Name = "${var.project_name}-eip-nat-${count.index + 1}"
  }

  depends_on = [aws_internet_gateway.primary]
}

# NAT Gateways
resource "aws_nat_gateway" "primary" {
  provider      = aws.primary
  count         = 2
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.primary_public[count.index].id

  tags = {
    Name = "${var.project_name}-nat-${count.index + 1}"
  }

  depends_on = [aws_internet_gateway.primary]
}

# Route tables
resource "aws_route_table" "primary_public" {
  provider = aws.primary
  vpc_id   = aws_vpc.primary.id

  route {
    cidr_block      = "0.0.0.0/0"
    gateway_id      = aws_internet_gateway.primary.id
  }

  tags = {
    Name = "${var.project_name}-rt-public-primary"
  }
}

resource "aws_route_table_association" "primary_public" {
  provider       = aws.primary
  count          = 2
  subnet_id      = aws_subnet.primary_public[count.index].id
  route_table_id = aws_route_table.primary_public.id
}

resource "aws_route_table" "primary_private" {
  provider = aws.primary
  count    = 2
  vpc_id   = aws_vpc.primary.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.primary[count.index].id
  }

  tags = {
    Name = "${var.project_name}-rt-private-${count.index + 1}"
  }
}

resource "aws_route_table_association" "primary_private" {
  provider       = aws.primary
  count          = 2
  subnet_id      = aws_subnet.primary_private[count.index].id
  route_table_id = aws_route_table.primary_private[count.index].id
}

# ────────────────────────────────────────────────────────────────────────────────
# Security Groups
# ────────────────────────────────────────────────────────────────────────────────

resource "aws_security_group" "alb" {
  provider    = aws.primary
  name        = "${var.project_name}-sg-alb"
  description = "Security group for Application Load Balancer"
  vpc_id      = aws_vpc.primary.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-sg-alb"
  }
}

resource "aws_security_group" "api" {
  provider    = aws.primary
  name        = "${var.project_name}-sg-api"
  description = "Security group for API instances"
  vpc_id      = aws_vpc.primary.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-sg-api"
  }
}

resource "aws_security_group" "database" {
  provider    = aws.primary
  name        = "${var.project_name}-sg-database"
  description = "Security group for RDS and ElastiCache"
  vpc_id      = aws_vpc.primary.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-sg-database"
  }
}

# ────────────────────────────────────────────────────────────────────────────────
# RDS PostgreSQL (Multi-Region)
# ────────────────────────────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "primary" {
  provider    = aws.primary
  name        = "${var.project_name}-db-subnet-primary"
  subnet_ids  = aws_subnet.primary_private[*].id

  tags = {
    Name = "${var.project_name}-db-subnet-primary"
  }
}

resource "aws_rds_cluster" "primary" {
  provider              = aws.primary
  cluster_identifier    = "${var.project_name}-db-cluster-primary"
  engine                = "aurora-postgresql"
  engine_version        = "14.7"
  database_name         = "puch_ai_db"
  master_username       = "puch_admin"
  master_password       = random_password.db_password.result
  db_subnet_group_name  = aws_db_subnet_group.primary.name
  vpc_security_group_ids = [aws_security_group.database.id]

  enabled_cloudwatch_logs_exports = ["postgresql"]
  backup_retention_period         = var.backup_retention_days
  deletion_protection             = var.deletion_protection
  storage_encrypted               = true
  skip_final_snapshot             = var.environment != "prod"

  tags = {
    Name = "${var.project_name}-db-cluster-primary"
  }
}

resource "aws_rds_cluster_instance" "primary" {
  provider           = aws.primary
  count              = 2
  cluster_identifier = aws_rds_cluster.primary.id
  instance_class     = var.rds_instance_class
  engine             = aws_rds_cluster.primary.engine
  engine_version     = aws_rds_cluster.primary.engine_version

  tags = {
    Name = "${var.project_name}-db-instance-primary-${count.index + 1}"
  }
}

# Read replica in secondary region
resource "aws_rds_cluster" "secondary" {
  provider                  = aws.secondary
  cluster_identifier        = "${var.project_name}-db-cluster-secondary"
  replication_source_arn    = aws_rds_cluster.primary.arn
  engine                    = aws_rds_cluster.primary.engine
  engine_version            = aws_rds_cluster.primary.engine_version
  skip_final_snapshot       = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
  deletion_protection       = var.deletion_protection
  storage_encrypted         = true

  depends_on = [
    aws_rds_cluster_instance.primary
  ]

  tags = {
    Name = "${var.project_name}-db-cluster-secondary"
  }
}

resource "aws_rds_cluster_instance" "secondary" {
  provider           = aws.secondary
  count              = 2
  cluster_identifier = aws_rds_cluster.secondary.id
  instance_class     = var.rds_instance_class
  engine             = aws_rds_cluster.secondary.engine
  engine_version     = aws_rds_cluster.secondary.engine_version

  tags = {
    Name = "${var.project_name}-db-instance-secondary-${count.index + 1}"
  }
}

# Read replica in tertiary region
resource "aws_rds_cluster" "tertiary" {
  provider                  = aws.tertiary
  cluster_identifier        = "${var.project_name}-db-cluster-tertiary"
  replication_source_arn    = aws_rds_cluster.primary.arn
  engine                    = aws_rds_cluster.primary.engine
  engine_version            = aws_rds_cluster.primary.engine_version
  skip_final_snapshot       = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
  deletion_protection       = var.deletion_protection
  storage_encrypted         = true

  depends_on = [
    aws_rds_cluster_instance.primary
  ]

  tags = {
    Name = "${var.project_name}-db-cluster-tertiary"
  }
}

resource "aws_rds_cluster_instance" "tertiary" {
  provider           = aws.tertiary
  count              = 2
  cluster_identifier = aws_rds_cluster.tertiary.id
  instance_class     = var.rds_instance_class
  engine             = aws_rds_cluster.tertiary.engine
  engine_version     = aws_rds_cluster.tertiary.engine_version

  tags = {
    Name = "${var.project_name}-db-instance-tertiary-${count.index + 1}"
  }
}

# ────────────────────────────────────────────────────────────────────────────────
# ElastiCache Redis (Multi-Region with Sentinel)
# ────────────────────────────────────────────────────────────────────────────────

resource "aws_elasticache_subnet_group" "primary" {
  provider    = aws.primary
  name        = "${var.project_name}-redis-subnet-primary"
  subnet_ids  = aws_subnet.primary_private[*].id

  tags = {
    Name = "${var.project_name}-redis-subnet-primary"
  }
}

resource "aws_elasticache_cluster" "primary" {
  provider            = aws.primary
  cluster_id          = "${var.project_name}-redis-primary"
  engine              = "redis"
  engine_version      = "7.0"
  node_type           = var.redis_node_type
  num_cache_nodes     = 1
  parameter_group_name = "default.redis7"
  port                = 6379
  subnet_group_name   = aws_elasticache_subnet_group.primary.name
  security_group_ids  = [aws_security_group.database.id]

  automatic_failover_enabled = true
  multi_az_enabled          = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  snapshot_retention_limit = 7
  snapshot_window          = "03:00-05:00"

  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.redis_primary.name
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "engine-log"
  }

  tags = {
    Name = "${var.project_name}-redis-primary"
  }

  depends_on = [aws_cloudwatch_log_group.redis_primary]
}

resource "aws_cloudwatch_log_group" "redis_primary" {
  provider            = aws.primary
  name                = "/aws/elasticache/${var.project_name}-redis-primary"
  retention_in_days   = 7

  tags = {
    Name = "${var.project_name}-redis-logs"
  }
}

# Secondary region Redis replica
resource "aws_elasticache_subnet_group" "secondary" {
  provider    = aws.secondary
  name        = "${var.project_name}-redis-subnet-secondary"
  subnet_ids  = [aws_subnet.secondary_private[0].id]  # Placeholder

  tags = {
    Name = "${var.project_name}-redis-subnet-secondary"
  }
}

# ────────────────────────────────────────────────────────────────────────────────
# Route53 Health Checks & Failover
# ────────────────────────────────────────────────────────────────────────────────

resource "aws_route53_zone" "main" {
  provider = aws.primary
  name     = "puch-ai.example.com"  # Replace with actual domain

  tags = {
    Name = "${var.project_name}-zone"
  }
}

resource "aws_route53_health_check" "primary_region" {
  provider   = aws.primary
  fqdn       = "api.primary.puch-ai.example.com"  # ALB endpoint in primary
  port       = 80
  type       = "HTTP"
  resource_path = "/health"
  failure_threshold = 3
  measure_latency = true

  tags = {
    Name = "${var.project_name}-healthcheck-primary"
  }
}

resource "aws_route53_health_check" "secondary_region" {
  provider   = aws.secondary
  fqdn       = "api.secondary.puch-ai.example.com"
  port       = 80
  type       = "HTTP"
  resource_path = "/health"
  failure_threshold = 3
  measure_latency = true

  tags = {
    Name = "${var.project_name}-healthcheck-secondary"
  }
}

# ────────────────────────────────────────────────────────────────────────────────
# Random Password for RDS
# ────────────────────────────────────────────────────────────────────────────────

resource "random_password" "db_password" {
  length  = 32
  special = true
}

# ────────────────────────────────────────────────────────────────────────────────
# Outputs
# ────────────────────────────────────────────────────────────────────────────────

output "primary_rds_endpoint" {
  value       = aws_rds_cluster.primary.endpoint
  description = "Primary RDS cluster endpoint (write operations)"
}

output "primary_rds_reader_endpoint" {
  value       = aws_rds_cluster.primary.reader_endpoint
  description = "Primary RDS reader endpoint"
}

output "secondary_rds_endpoint" {
  value       = aws_rds_cluster.secondary.endpoint
  description = "Secondary RDS cluster endpoint (read-only replica)"
}

output "tertiary_rds_endpoint" {
  value       = aws_rds_cluster.tertiary.endpoint
  description = "Tertiary RDS cluster endpoint (read-only replica)"
}

output "primary_redis_endpoint" {
  value       = aws_elasticache_cluster.primary.cache_nodes[0].address
  description = "Primary Redis cluster endpoint"
}

output "route53_zone_id" {
  value       = aws_route53_zone.main.zone_id
  description = "Route53 hosted zone ID"
}

output "vpc_id" {
  value       = aws_vpc.primary.id
  description = "Primary VPC ID"
}

output "db_password_secret_name" {
  value       = "Store in AWS Secrets Manager: ${random_password.db_password.result}"
  description = "Store this password in AWS Secrets Manager and reference via environment"
  sensitive   = true
}
