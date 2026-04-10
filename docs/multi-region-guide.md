# Multi-Region Deployment Guide

This guide explains how to deploy Puch AI Voice Server across multiple AWS regions with automatic failover and read-only replicas.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                       Route53 (Global DNS)                      │
│          Geolocation routing + Health checks + Failover         │
└────┬──────────────────────────────────────────────────┬─────────┘
     │                                                  │
     ▼                                                  ▼
┌──────────────────────┐              ┌──────────────────────┐
│  PRIMARY REGION      │              │  SECONDARY REGION    │
│  (us-east-1)         │              │  (eu-west-1)         │
│                      │              │                      │
│  ┌────────────────┐  │              │  ┌────────────────┐  │
│  │   ALB + 3x     │  │              │  │   ALB + 3x     │  │
│  │   API Server   │  │              │  │   API Server   │  │
│  └────────────────┘  │              │  └────────────────┘  │
│       ↓              │              │       ↓              │
│  ┌────────────────┐  │              │  ┌────────────────┐  │
│  │  RDS Primary   │──┼──Replicate──▶│  │  RDS Replica   │  │
│  │  (write)       │  │              │  │  (read-only)   │  │
│  └────────────────┘  │              │  └────────────────┘  │
│       ↓              │              │       ↓              │
│  ┌────────────────┐  │              │  ┌────────────────┐  │
│  │  Redis Multi   │  │              │  │  Redis Replica │  │
│  │  (primary)     │  │              │  │  (replica)     │  │
│  └────────────────┘  │              │  └────────────────┘  │
└──────────────────────┘              └──────────────────────┘

Failover Flow:
1. Primary region health check fails
2. Route53 detects failure (3 health check failures = ~90 seconds)
3. Traffic automatically routed to secondary region
4. Secondary region promotes DB to writable mode
5. Operators can restore primary or switch permanently
```

## Prerequisites

- AWS CLI configured with credentials
- Terraform >= 1.0
- Domain registered and hosted on Route53
- IAM permissions for EC2, RDS, ElastiCache, Route53, VPC, IAM

## Deployment Steps

### 1. Initialize Terraform

```bash
cd ops
terraform init

# Verify setup
terraform validate
terraform plan -var environment=prod
```

### 2. Customize Variables

Create `terraform.tfvars`:

```hcl
project_name = "puch-ai"
environment  = "prod"

regions = {
  primary   = "us-east-1"
  secondary = "eu-west-1"
  tertiary  = "ap-south-1"
}

instance_count      = 3
instance_type       = "t3.medium"
rds_instance_class  = "db.t3.large"
redis_node_type     = "cache.r6g.xlarge"

deletion_protection = true
backup_retention_days = 30
```

### 3. Deploy Infrastructure

```bash
# Primary + Secondary + Tertiary regions
terraform apply

# Outputs:
# - primary_rds_endpoint
# - primary_redis_endpoint
# - route53_zone_id
# - vpc_id
```

### 4. Configure Application

Update server environment variables in each region:

**Primary Region:**
```bash
# RDS primary (write operations)
DATABASE_URL=postgresql://puch_admin:PASSWORD@puch-ai-db-cluster-primary.us-east-1.rds.amazonaws.com:5432/puch_ai_db

# Redis primary
REDIS_URL=redis://puch-ai-redis-primary.us-east-1.cache.amazonaws.com:6379/0

# Failover config
REGION=us-east-1
REGION_ROLE=primary
```

**Secondary Region:**
```bash
# RDS read-only replica
DATABASE_URL=postgresql://puch_admin:PASSWORD@puch-ai-db-cluster-secondary.eu-west-1.rds.amazonaws.com:5432/puch_ai_db?APPLICATION_NAME=readonly

# Redis replica
REDIS_URL=redis://puch-ai-redis-secondary.eu-west-1.cache.amazonaws.com:6379/0

# Read-only mode
REGION=eu-west-1
REGION_ROLE=secondary
DATABASE_READ_ONLY=true
```

### 5. Configure Route53 Failover

Update Route53 records with geolocation routing:

```bash
# Primary: route traffic from us-east, ca, mx
aws route53 change-resource-record-sets \
  --hosted-zone-id ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "api.puch-ai.example.com",
        "Type": "A",
        "SetIdentifier": "Primary-US",
        "GeolocationLocation": {
          "CountryCode": "US"
        },
        "AliasTarget": {
          "HostedZoneId": "Z1234567890ABC",
          "DNSName": "puch-alb-primary.us-east-1.elb.amazonaws.com",
          "EvaluateTargetHealth": true
        }
      }
    }]
  }'

# Secondary: route traffic from europe
aws route53 change-resource-record-sets \
  --hosted-zone-id ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "api.puch-ai.example.com",
        "Type": "A",
        "SetIdentifier": "Secondary-EU",
        "GeolocationLocation": {
          "CountryCode": "GB"
        },
        "AliasTarget": {
          "HostedZoneId": "Z0987654321DEF",
          "DNSName": "puch-alb-secondary.eu-west-1.elb.amazonaws.com",
          "EvaluateTargetHealth": true
        }
      }
    }]
  }'

# Tertiary: route traffic from asia
# ... (same pattern)

# Default: any region not matched above
aws route53 change-resource-record-sets \
  --hosted-zone-id ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "api.puch-ai.example.com",
        "Type": "A",
        "SetIdentifier": "Default",
        "GeolocationLocation": {
          "CountryCode": "*"
        },
        "AliasTarget": {
          "HostedZoneId": "Z1234567890ABC",
          "DNSName": "puch-alb-primary.us-east-1.elb.amazonaws.com",
          "EvaluateTargetHealth": true
        }
      }
    }]
  }'
```

## Health Checks

### Route53 Health Checks

Every region has a health check that monitors the `/health` endpoint:

```bash
# Check status
aws route53 get-health-check-status \
  --health-check-id abc12345-1234-1234-1234-123456789012

# Expected response:
{
  "HealthCheckObservations": [
    {
      "Region": "us-east-1",
      "IPAddress": "203.0.113.45",
      "StatusReport": {
        "Status": "Success",
        "HealthChecks": [...]
      }
    }
  ]
}
```

### Configure Health Check Intervals

- **Interval**: 30 seconds (standard)
- **Failure threshold**: 3 consecutive failures
- **Failure detection**: ~90 seconds (3 × 30s)
- **Failover time**: ~120 seconds (includes Route53 cache invalidation)

## Database Replication

### RDS Replication Status

```bash
# Check replication lag
aws rds describe-db-clusters \
  --db-cluster-identifier puch-ai-db-cluster-secondary \
  --query 'DBClusters[0].ReplicationLag'

# Expected: < 100ms for synchronous replication
```

### Handling Replication Lag

- **Synchronous replication**: Writes wait for replica acknowledgment
- **Configuration**: Multi-region database cluster
- **Failure behavior**: Automatic failover with 0 data loss
- **RPO (Recovery Point Objective)**: 0 seconds
- **RTO (Recovery Time Objective)**: < 30 seconds

## Failover Scenarios

### Scenario 1: Region Outage

**What happens:**
1. Route53 health check fails (90s detection)
2. DNS records updated to point to secondary
3. Exotel calls reroute to secondary region
4. Calls in flight handled by ALB: keep-alive + graceful shutdown

**Actions:**
```bash
# Verify secondary is receiving traffic
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name RequestCount \
  --dimensions Name=LoadBalancer,Value=app/puch-alb-secondary

# Check database replication
aws rds describe-db-clusters --db-cluster-identifier puch-ai-db-cluster-secondary

# If primary doesn't recover, promote secondary:
# aws rds modify-db-cluster --db-cluster-identifier puch-ai-db-cluster-secondary \
#     --enable-iam-database-authentication

# Note: Test this procedure in non-production first!
```

### Scenario 2: Single Instance Failure

**What happens:**
1. ALB health check fails for instance
2. Instance removed from target group
3. ASG launches replacement instance
4. 1-2 minutes to full replacement

**Verification:**
```bash
# Check ASG status
aws autoscaling describe-auto-scaling-groups \
  --auto-scaling-group-names puch-api-asg-primary

# Check running instances
aws ec2 describe-instances \
  --filters Name=tag:Environment,Values=prod \
             Name=instance-state-name,Values=running
```

### Scenario 3: Database Replica Failure

**What happens:**
1. RDS multi-region cluster self-heals
2. Automatic failover within region
3. Secondary region still has writeable instance
4. Minimal impact (multi-AZ within region)

**Verification:**
```bash
# Check RDS cluster status
aws rds describe-db-clusters \
  --query 'DBClusters[*].[DBClusterIdentifier, Status]'

# Expected: available for all clusters
```

## Performance Optimization

### Read Replicas for Analytics

Use secondary region replicas for reporting:

```python
# Producer: write to primary
primary_db = connect('postgresql://primary-rds:5432/puch_ai_db')
primary_db.execute("INSERT INTO calls (stream_id, ...) VALUES (...)")

# Consumer: read from secondary/replica
replica_db = connect('postgresql://secondary-rds:5432/puch_ai_db')
stats = replica_db.execute("SELECT COUNT(*), AVG(duration) FROM calls WHERE date > NOW() - INTERVAL '1 day'")
```

### Connection Pooling

Use connection pooling to handle multi-region latency:

```python
# pgBouncer config for connection pooling
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 25
reserve_pool_size = 5
reserve_pool_timeout = 3
```

## Monitoring & Alerts

### CloudWatch Dashboards

```bash
# Create dashboard for multi-region monitoring
aws cloudwatch put-dashboard \
  --dashboard-name PuchAI-MultiRegion \
  --dashboard-body file://dashboard.json
```

### Key Metrics

- **RDS Replication Lag**: Should be < 100ms
- **ElastiCache Replication Lag**: Should be < 50ms
- **Route53 Health Check Status**: Should be "Healthy"
- **ALB Target Health**: Should be "Healthy" for all targets
- **Cross-region Latency**: Measure via CloudFront or Route53

### Alerts

```bash
# Replication lag alarm
aws cloudwatch put-metric-alarm \
  --alarm-name puch-ai-rds-replication-lag \
  --alarm-description "Alert if RDS replication lag > 1 second" \
  --metric-name ReplicationLag \
  --namespace AWS/RDS \
  --statistic Average \
  --period 60 \
  --threshold 1000 \
  --comparison-operator GreaterThanThreshold
```

## Disaster Recovery

### Backup & Restore

```bash
# RDS automated backups (retention: 30 days)
# S3 cross-region backup: puch-ai-backups-backup region

# Manual snapshot
aws rds create-db-cluster-snapshot \
  --db-cluster-snapshot-identifier puch-ai-backup-$(date +%Y%m%d)

# Restore from snapshot to new cluster
aws rds restore-db-cluster-from-snapshot \
  --db-cluster-identifier puch-ai-restored \
  --snapshot-identifier puch-ai-backup-20240410
```

### Data Retention Cleanup

```bash
# Automated cleanup job (runs daily)
# - Delete calls older than 90 days
# - Archive to S3 for compliance
# - PII masking before archival

DELETE FROM calls WHERE created_at < NOW() - INTERVAL '90 days';
VACUUM ANALYZE;
```

## Cost Estimation

### Monthly Cost (3 regions, 3 instances each)

| Component | per Region | 3x Regions | Notes |
|-----------|-----------|-----------|-------|
| EC2 (t3.medium) | $150 | $450 | 3 instances × 730 hours × $0.0416/hr |
| RDS (db.t3.large) | $350 | $1,050 | 2 instances (multi-AZ) × $0.173/hr |
| ElastiCache | $400 | $1,200 | r6g.xlarge × $0.184/hr |
| ALB | $25 | $75 | $0.0225/hr per region |
| NAT Gateway | $50 | $150 | $0.032/hr + data transfer |
| Route53 | - | $50 | $0.50 per hosted zone + health checks |
| Data Transfer | - | $200 | Cross-region replication + inter-AZ |
| **Total** | **$975** | **$3,175** | Plus RDS backups (~$200) |

### Cost Optimization

1. **Use spot instances** (ASG with 80% spot, 20% on-demand)
   - Savings: 40% on EC2 ($450 → $270/month)

2. **Reserved instances** (1-year commitment)
   - Savings: 35% on RDS + compute ($1,050 → $680/month)

3. **Smaller primary instance** (t3.small instead of t3.medium)
   - Savings: $180 → $120 per region

4. **Single replica per region** instead of 2
   - Savings: $350 per region

**Optimized 3-region cost: ~$2,000/month** (vs. $3,175 baseline)

## Troubleshooting

### Route53 Failover Not Triggering

```bash
# Check health check status
aws route53 get-health-check-status --health-check-id <id>

# Verify Route53 record set
aws route53 list-resource-record-sets --hosted-zone-id <id>

# Manual test
dig @route53-nameserver api.puch-ai.example.com
curl -i http://api.puch-ai.example.com/health
```

### Database Replication Lag

```bash
# Check lag
aws rds describe-db-cluster-endpoints \
  --db-cluster-identifier puch-ai-db-cluster-secondary \
  --query 'DBClusterEndpoints[0].CustomEndpointType'

# Increase IOPS if needed
aws rds modify-db-instance \
  --db-instance-identifier puch-ai-db-instance-secondary-1 \
  --iops 3000
```

### Calls Dropping During Failover

```bash
# Verify ALB stickiness
aws elbv2 describe-target-groups \
  --load-balancer-arn <lb-arn> \
  --query 'TargetGroups[0].TargetGroupAttributes'

# Check connection drain timeout (should be 30s)
# aws elbv2 modify-target-group-attributes \
#     --target-group-arn <tg-arn> \
#     --attributes Key=deregistration_delay.timeout_seconds,Value=30
```

## Next Steps

1. **Test failover** in staging environment
2. **Run load test** with 500 concurrent calls across 3 regions
3. **Document runbook** for emergency failover procedures
4. **Configure monitoring** dashboards and alerts
5. **Train team** on multi-region operations

## References

- [AWS RDS Multi-Region Database Clusters](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/multi-region-db.html)
- [Route53 Failover Routing](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/routing-policy-failover.html)
- [ElastiCache Replication](https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/Replication.html)
- [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
