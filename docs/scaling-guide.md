# Puch AI Voice Server - Enterprise Scaling Guide

## Overview

This guide explains how to scale the Puch AI Voice Server from single-instance (100 concurrent) to multi-instance (1000+ concurrent) deployment with enterprise-grade infrastructure.

## Architecture

### Single Instance (100 concurrent)
- 1 FastAPI server
- In-memory session storage
- Single-instance deployment
- Max: ~100 concurrent calls, 16GB memory

### Multi-Instance (300+ concurrent via ALB)
- 3 FastAPI instances
- Shared Redis for distributed state
- PostgreSQL for persistence
- Load balancer (ALB, Nginx, or K8s Service)
- Max: ~300 concurrent calls per instance group

### Global Multi-Region (1000+ concurrent)
- Multiple regional deployments
- PostgreSQL read replicas
- Redis Sentinel or ElastiCache multi-region
- Route53 geolocation routing
- Auto-failover on regional outage

## Components

### 1. Load Balancer

**Options:**

1. **Docker Compose (Development/Testing)**
   - Nginx load balancer
   - 3 FastAPI instances
   - Redis + PostgreSQL
   - Single-node Jaeger
   - See: `ops/docker-compose.yml`

2. **Kubernetes (Production)**
   - StatefulSet with 3 replicas
   - Horizontal Pod Autoscaler (HPA)
   - LoadBalancer Service
   - Pod Disruption Budget (PDB)
   - Auto-scaling: 3-10 replicas
   - See: `ops/kubernetes-deployment.yaml`

3. **AWS ALB (Production)**
   - Application Load Balancer
   - EC2 Auto Scaling Group
   - Target Group with health checks
   - See: `ops/terraform-multi-region.tf` (Phase 2C)

### 2. Graceful Shutdown

**Implementation:**

```bash
# Signal: SIGTERM → graceful shutdown initiated
# Timeout: 30 seconds (configurable via GRACEFUL_SHUTDOWN_TIMEOUT_S)
# Behavior:
#   1. Stop accepting new WebSocket connections
#   2. Drain active connections (wait for natural close)
#   3. Force-close after timeout
#   4. Save session metrics
#   5. Exit cleanly
```

**Configuration:**

```bash
# .env
GRACEFUL_SHUTDOWN_TIMEOUT_S=30          # Drain timeout in seconds
MAX_CONNECTIONS=200                      # Connections per instance
```

**Monitoring:**

```bash
# Monitor active WebSocket connections
curl http://localhost:8000/health

# Response:
{
  "status": "ok",
  "active_sessions": 42  # Number of active calls
}
```

### 3. Configuration

#### Environment Variables

```bash
# Server
PORT=8000
LOG_LEVEL=INFO
LOG_FORMAT=json

# Scaling
MAX_CONNECTIONS=200
GRACEFUL_SHUTDOWN_TIMEOUT_S=30
INSTANCE_ID=1              # Unique ID per instance
INSTANCE_NUM=1             # Total number of instances
INSTANCE_TOTAL=3

# Distributed state
REDIS_URL=redis://redis:6379/0
DATABASE_URL=postgresql://user:pass@host:5432/db

# Observability
JAEGER_AGENT_HOST=localhost
JAEGER_AGENT_PORT=6831

# AI providers (same as Phase 1)
GEMINI_API_KEY=...
GOOGLE_APPLICATION_CREDENTIALS=/path/to/creds.json
```

## Deployment

### Option 1: Docker Compose (3 instances + dependencies)

```bash
cd ops
docker-compose up -d

# Verify
curl http://localhost:8000/health
# or for each instance:
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health

# Scale test
python3 ../scripts/benchmark.py --concurrent 300 --duration 60

# Shutdown gracefully
docker-compose down
```

**Services:**
- `lb`: Nginx load balancer (port 8000)
- `api-1`, `api-2`, `api-3`: FastAPI instances
- `postgres`: PostgreSQL database
- `redis`: Redis for distributed state
- `jaeger`: Jaeger UI for tracing (port 16686)

### Option 2: Kubernetes (Production)

```bash
# Deploy to K8s cluster
kubectl apply -f ops/kubernetes-deployment.yaml

# Wait for deployment
kubectl rollout status -n puch-ai statefulset/puch-api

# Port-forward for testing
kubectl port-forward -n puch-ai svc/puch-api-lb 8000:80

# Verify
curl http://localhost:8000/health

# Scale up
kubectl scale -n puch-ai statefulset puch-api --replicas=5

# Check metrics
kubectl top -n puch-ai pod
kubectl top -n puch-ai node

# Graceful shutdown (rolling update)
kubectl set image -n puch-ai statefulset/puch-api \
  api=puch-ai:new-version --record

# Cleanup
kubectl delete -f ops/kubernetes-deployment.yaml
```

**Key Features:**
- **Auto-scaling**: HPA scales 3-10 replicas based on CPU/memory
- **Graceful shutdown**: Drain 30s timeout before forceful close
- **Health checks**: Liveness + readiness probes
- **Pod disruption budget**: Always keep 2 replicas
- **Anti-affinity**: Spread across different nodes

### Option 3: AWS (Production)

```bash
# Via Terraform (Phase 2C)
cd ops
terraform init
terraform plan -var region=us-east-1
terraform apply -var region=us-east-1

# Outputs
# - ALB DNS name
# - RDS endpoint
# - ElastiCache endpoint
# - Auto Scaling Group

# Scale capacity
aws autoscaling set-desired-capacity \
  --auto-scaling-group-name puch-api-asg \
  --desired-capacity 5
```

## Performance Tuning

### Per-Instance Capacity

```
CPU:    1 core handles ~200 concurrent calls
Memory: 1GB base + 5MB per active call
        - 100 concurrent = 1.5GB
        - 200 concurrent = 2.0GB
Network: 100 Mbps → ~200 concurrent calls
```

**Bottleneck:** CPU is typically the limiting factor (STT/LLM/TTS processing)

### Recommendation

```
For 1000 concurrent:
- 5 instances × 200 concurrent = 1000 concurrent
- Each instance: 2 CPU cores, 2GB memory
- Total: 10 CPU cores, 10GB memory
- Load balancer overhead: + 1 core
- Database: 4 CPU, 8GB memory
- Redis: 2 CPU, 4GB memory
```

## Monitoring & Observability

### Health Check Endpoint

```bash
GET /health
{
  "status": "ok",
  "active_sessions": 42
}
```

### Metrics (Phase 2C: Distributed Tracing)

```bash
# Jaeger tracing UI
http://localhost:16686

# Metrics to track
- Request latency (p50, p95, p99)
- Active sessions
- Error rate
- Provider API quota usage
- Cost per call
```

### Logs

```bash
# Structured JSON logging (configurable)
{
  "timestamp": "2024-04-10T12:34:56Z",
  "level": "INFO",
  "logger": "src.infrastructure.server",
  "message": "WebSocket disconnected cleanly",
  "stream_id": "abc123",
  "client_ip": "203.0.113.45",
  "trace_id": "xyz789"
}
```

## Troubleshooting

### Issue: Connection refused

```bash
# Check load balancer is running
curl -v http://localhost:8000/health

# Check backend instances
docker ps | grep api
kubectl get -n puch-ai pods
```

### Issue: Connections hang on shutdown

```bash
# Increase graceful shutdown timeout
GRACEFUL_SHUTDOWN_TIMEOUT_S=60

# Monitor active connections
docker logs puch-lb  # Nginx logs
kubectl logs -n puch-ai deployment/puch-lb
```

### Issue: High latency during scale-up

```bash
# Check HPA scaling
kubectl get -n puch-ai hpa puch-api-hpa

# Monitor CPU/memory
kubectl top -n puch-ai pod

# Check instance load
curl http://localhost:8000/health  # All instances
```

### Issue: Redis/PostgreSQL connection errors

```bash
# Verify connectivity
redis-cli -h redis ping
psql -h postgres -U puch_user -d puch_ai_db -c "SELECT 1"

# Check environment variables
echo $REDIS_URL
echo $DATABASE_URL

# Increase connection pool size
CONNECTION_POOL_SIZE=50
```

## Load Testing

### Benchmark Script (Phase 2C)

```bash
cd scripts
python3 benchmark.py \
  --concurrent 300 \
  --duration 60 \
  --target ws://localhost:8000/stream?sample-rate=8000
```

**Output:**
```
Concurrent connections: 300
Requests per second: 245
Latency (ms):
  p50: 45
  p95: 120
  p99: 280
Error rate: 0.2%
Total requests: 14700
```

## Scaling Checklist

- [ ] Deploy load balancer (Nginx, ALB, or K8s)
- [ ] Configure Redis for distributed state
- [ ] Configure PostgreSQL for persistence
- [ ] Set graceful shutdown timeout
- [ ] Enable health checks
- [ ] Enable auto-scaling (HPA, ASG)
- [ ] Configure monitoring (Jaeger, CloudWatch, Prometheus)
- [ ] Test load at 300 concurrent (3 instances)
- [ ] Test failover (kill 1 instance, verify traffic reroutes)
- [ ] Test graceful shutdown (verify 0 data loss)
- [ ] Capacity planning for 1000 concurrent (5+ instances)
- [ ] Cost estimation (compute, database, network)

## Cost Optimization

### Recommendations

1. **Use spot/preemptible instances** (40% savings)
   - Keep 1 on-demand, 4 on preemptible
   - Failure probability: <1% per instance

2. **Use cheaper regions** (25% savings)
   - Primary: us-east (cheaper)
   - Secondary: eu-west (for failover)

3. **Cache provider responses** (20% savings)
   - LLM responses: 5min TTL
   - TTS output: Common phrases
   - STT results: Identical utterances

4. **Use fallback providers** (30% savings for STT)
   - Primary: Google STT
   - Fallback: Deepgram (cheaper)

## Next Steps

1. Deploy Docker Compose setup for local testing
2. Implement Phase 2B: State synchronization (Redis + distributed locks)
3. Implement Phase 2C: Multi-region support (Terraform)
4. Add distributed tracing (OpenTelemetry + Jaeger)
5. Run 500 concurrent load test
6. Implement disaster recovery (backups + failover)
7. Finalize capacity model and cost projections

## References

- Kubernetes StatefulSet: https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/
- Nginx Load Balancing: https://nginx.org/en/docs/http/load_balancing.html
- AWS ALB: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/
- PostgreSQL Replication: https://www.postgresql.org/docs/current/warm-standby.html
- Redis Sentinel: https://redis.io/docs/management/sentinel/
