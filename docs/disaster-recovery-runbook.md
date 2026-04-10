# Disaster Recovery Runbook

## Overview

This document provides procedures for recovering the Exotel AgentStream Voice AI PoC from various disaster scenarios.

### Recovery Objectives
- **RTO (Recovery Time Objective):** < 1 hour
- **RPO (Recovery Point Objective):** < 5 minutes
- **Availability Target:** 99.5% uptime

## Quick Reference

| Scenario | RTO | RPO | Action | Page |
|----------|-----|-----|--------|------|
| Database corruption | 15 min | 5 min | Restore from backup | [Database Recovery](#database-recovery) |
| Data loss (user delete) | 10 min | 5 min | Restore user data | [Point-in-Time Recovery](#point-in-time-recovery) |
| S3 backup corruption | 30 min | 30 min | Verify backup integrity | [Backup Integrity](#backup-integrity-checks) |
| Call log loss | 5 min | - | Restore from backup | [Call Log Recovery](#call-log-recovery) |
| Encryption key loss | 1 hour | N/A | Key recovery procedure | [Key Recovery](#encryption-key-recovery) |

## Prerequisites

Before starting recovery procedures:

1. **Required credentials:**
   ```bash
   export DATABASE_URL="postgresql://user:pass@host/puchai"
   export AWS_ACCESS_KEY_ID="xxx"
   export AWS_SECRET_ACCESS_KEY="xxx"
   export S3_BUCKET="backups-bucket"
   export ENCRYPTION_MASTER_KEY="xxx"
   ```

2. **Required tools:**
   - Python 3.8+
   - psycopg3 (PostgreSQL client)
   - AWS CLI
   - Docker (for running recovery in container)

3. **Network access:**
   - PostgreSQL database (5432)
   - S3 bucket (https)
   - Optional: Bastion host if in restricted network

## Database Recovery

### Scenario: Database Corruption or Data Corruption

**RTO:** 15 minutes | **RPO:** 5 minutes

### Step 1: Assess Damage

```bash
# Check database status
psql $DATABASE_URL -c "SELECT version();"

# Check backup metadata
psql $DATABASE_URL -c "SELECT * FROM backup_metadata WHERE status='completed' ORDER BY created_at DESC LIMIT 5;"

# Check audit trail integrity
psql $DATABASE_URL -c "SELECT COUNT(*) FROM audit_trail;"
```

### Step 2: Identify Latest Good Backup

```python
from src.infrastructure.backup_manager import BackupManager

async def find_good_backup():
    manager = BackupManager(
        db_url=os.getenv("DATABASE_URL"),
        s3_bucket=os.getenv("S3_BUCKET"),
    )
    
    backups = await manager.list_backups(limit=10)
    for backup in backups:
        if backup['status'] == 'completed':
            print(f"Good backup: {backup['backup_id']}")
            return backup['backup_id']
```

### Step 3: Restore Database

```bash
# Stop application
docker stop exotel-voice-ai

# Restore backup
python3 -c "
import asyncio
from src.infrastructure.backup_manager import BackupManager

async def restore():
    manager = BackupManager(
        db_url=os.getenv('DATABASE_URL'),
        s3_bucket=os.getenv('S3_BUCKET'),
    )
    await manager.restore_backup('backup-20240410-143000')

asyncio.run(restore())
"

# Verify restore
psql $DATABASE_URL -c "SELECT COUNT(*) FROM call_logs;"

# Start application
docker start exotel-voice-ai

# Monitor logs
docker logs -f exotel-voice-ai
```

### Step 4: Verify Data Integrity

```bash
# Run integrity checks
psql $DATABASE_URL -c "ANALYZE;"
psql $DATABASE_URL -c "VACUUM FULL ANALYZE;"

# Check for orphaned records
psql $DATABASE_URL -c "
SELECT 
  schemaname, 
  tablename, 
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) 
FROM pg_tables 
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"
```

## Point-in-Time Recovery (PITR)

### Scenario: Need to Recover Data from Specific Point in Time

**RTO:** 20 minutes | **RPO:** Variable (depends on backup frequency)

### Step 1: Identify Recovery Target

```bash
# Find the transaction/time you want to recover to
psql $DATABASE_URL -c "
SELECT * FROM audit_trail 
WHERE timestamp > '2024-04-10 10:00:00'
  AND timestamp < '2024-04-10 11:00:00'
ORDER BY timestamp DESC LIMIT 20;
"
```

### Step 2: Restore to Target Time

```python
from datetime import datetime
from src.infrastructure.backup_manager import BackupManager

async def point_in_time_restore(target_time: datetime):
    manager = BackupManager(
        db_url=os.getenv("DATABASE_URL"),
        s3_bucket=os.getenv("S3_BUCKET"),
    )
    
    # Find backup before target time
    backups = await manager.list_backups(limit=100)
    suitable_backup = None
    
    for backup in backups:
        if backup['created_at'] < target_time:
            suitable_backup = backup['backup_id']
            break
    
    if suitable_backup:
        await manager.restore_backup(suitable_backup)
        print(f"Restored to {suitable_backup}")
```

## Call Log Recovery

### Scenario: Call Logs Deleted or Lost

**RTO:** 5 minutes | **RPO:** < 5 minutes

### Step 1: Check Audit Trail

```bash
# Verify audit logs are intact
psql $DATABASE_URL -c "
SELECT COUNT(*) FROM audit_trail 
WHERE action IN ('CALL_START', 'CALL_END');
"
```

### Step 2: Restore from Backup

```bash
# Restore specific table
python3 -c "
import asyncio
from src.infrastructure.backup_manager import BackupManager

async def restore_call_logs():
    manager = BackupManager(
        db_url=os.getenv('DATABASE_URL'),
        s3_bucket=os.getenv('S3_BUCKET'),
    )
    await manager.restore_backup(
        backup_id='latest',  # Use latest backup
        include_tables=['call_logs']
    )

asyncio.run(restore_call_logs())
"
```

### Step 3: Verify Recovery

```bash
# Count call logs
psql $DATABASE_URL -c "SELECT COUNT(*) FROM call_logs;"

# Check for data gaps
psql $DATABASE_URL -c "
SELECT DATE(created_at), COUNT(*) 
FROM call_logs 
GROUP BY DATE(created_at)
ORDER BY DATE(created_at) DESC
LIMIT 10;
"
```

## Backup Integrity Checks

### Verify Backup Validity

```python
import hashlib
from src.infrastructure.backup_manager import BackupManager

async def verify_backup(backup_id: str):
    manager = BackupManager(
        db_url=os.getenv("DATABASE_URL"),
        s3_bucket=os.getenv("S3_BUCKET"),
    )
    
    # Get backup metadata
    backup = await manager._get_backup_metadata(backup_id)
    
    # Download and verify checksum
    data = await manager._download_from_s3(backup['s3_key'])
    checksum = hashlib.sha256(data).hexdigest()
    
    if checksum == backup['checksum']:
        print(f"✓ Backup {backup_id} is valid")
        return True
    else:
        print(f"✗ Backup {backup_id} is corrupted")
        return False
```

## Encryption Key Recovery

### Scenario: Encryption Master Key Lost

**RTO:** 1 hour | **RPO:** N/A (key-based)

### Step 1: Identify Key Loss

```bash
# Check if encrypted data is accessible
python3 -c "
from src.infrastructure.encryption import get_encryption_manager
manager = get_encryption_manager()
# Try to decrypt a known field
status = manager.get_key_rotation_status()
print(status)
"
```

### Step 2: Key Recovery Options

**Option A: Use Backup Key** (if you have multiple key copies)
```bash
# Rotate to backup key
export ENCRYPTION_MASTER_KEY="backup-key-xxx"
# Restart application
docker restart exotel-voice-ai
```

**Option B: Re-encrypt with New Key**
```bash
# Create new master key
NEW_KEY=$(openssl rand -hex 32)
export ENCRYPTION_MASTER_KEY=$NEW_KEY

# Re-encrypt database fields
python3 -c "
import asyncio
from src.infrastructure.encryption import EncryptionManager

async def reencrypt():
    manager = EncryptionManager(master_key=os.getenv('ENCRYPTION_MASTER_KEY'))
    # TODO: Implement field re-encryption
    pass

asyncio.run(reencrypt())
"
```

### Step 3: Store New Key Safely

```bash
# Store in AWS Secrets Manager
aws secretsmanager create-secret \
  --name exotel-voice-ai/encryption-key \
  --secret-string $NEW_KEY

# Or in environment variable backup
echo "ENCRYPTION_MASTER_KEY=$NEW_KEY" > /secure/backup/.env
chmod 600 /secure/backup/.env
```

## Data Retention Recovery

### Scenario: Data Accidentally Deleted Due to Retention Policy

**RTO:** 30 minutes | **RPO:** Last backup

### Step 1: Identify Deletion

```bash
# Check deletion log
psql $DATABASE_URL -c "
SELECT * FROM deletion_log 
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
"
```

### Step 2: Restore Deleted Data

```python
from datetime import datetime, timedelta
from src.infrastructure.backup_manager import BackupManager

async def recover_deleted_data(deletion_time: datetime):
    manager = BackupManager(
        db_url=os.getenv("DATABASE_URL"),
        s3_bucket=os.getenv("S3_BUCKET"),
    )
    
    # Find backup before deletion
    backups = await manager.list_backups(limit=100)
    
    for backup in backups:
        if backup['created_at'] < deletion_time:
            print(f"Restoring from {backup['backup_id']}")
            await manager.restore_backup(backup['backup_id'])
            break
```

## Disaster Recovery Testing

### Monthly Backup Test

```bash
#!/bin/bash
# Run monthly to ensure backups are valid

# 1. List recent backups
psql $DATABASE_URL -c "
  SELECT backup_id, start_time, status, backup_size_bytes 
  FROM backup_metadata 
  WHERE status='completed' 
  ORDER BY created_at DESC LIMIT 5;
"

# 2. Test restore (on staging environment)
python3 -c "
import asyncio
from src.infrastructure.backup_manager import BackupManager

async def test_restore():
    manager = BackupManager(
        db_url='postgresql://localhost/puchai-staging',
        s3_bucket=os.getenv('S3_BUCKET'),
    )
    
    backups = await manager.list_backups(limit=1)
    if backups:
        await manager.restore_backup(backups[0]['backup_id'])
        print('✓ Backup restore test passed')

asyncio.run(test_restore())
"

# 3. Verify data integrity
psql postgresql://localhost/puchai-staging -c "
  SELECT COUNT(*) FROM call_logs;
  SELECT COUNT(*) FROM audit_trail;
  SELECT COUNT(*) FROM sessions;
"
```

### Failover Testing

```bash
# Test database failover (if using replication)
docker exec postgres-standby \
  pg_ctl promote -D /var/lib/postgresql/data

# Monitor switchover
docker logs -f postgres-primary

# Revert after test
docker exec postgres-standby \
  pg_ctl demote -D /var/lib/postgresql/data
```

## Monitoring and Alerts

### Health Checks

```bash
# Check backup status every hour
0 * * * * /usr/local/bin/check-backup-status.sh

# Check encryption key rotation status every week
0 0 * * 0 /usr/local/bin/check-key-rotation.sh

# Check data retention policy every day
0 1 * * * /usr/local/bin/check-retention-policy.sh
```

### CloudWatch Metrics

```python
import boto3

cloudwatch = boto3.client('cloudwatch')

# Report backup status
cloudwatch.put_metric_data(
    Namespace='ExotelVoiceAI',
    MetricData=[
        {
            'MetricName': 'LastBackupAge',
            'Value': hours_since_backup,
            'Unit': 'Hours',
        },
        {
            'MetricName': 'BackupSize',
            'Value': backup_size_bytes,
            'Unit': 'Bytes',
        },
    ]
)
```

## Emergency Contacts

- **Database Team:** db-oncall@company.com
- **Security Team:** security@company.com
- **DevOps:** devops@company.com

## Appendix: Recovery Checklist

- [ ] Identify failure type and RTO/RPO
- [ ] Notify stakeholders
- [ ] Prepare recovery environment
- [ ] Execute recovery procedure
- [ ] Verify data integrity
- [ ] Run health checks
- [ ] Monitor for 24 hours
- [ ] Document incident
- [ ] Update runbook with lessons learned
