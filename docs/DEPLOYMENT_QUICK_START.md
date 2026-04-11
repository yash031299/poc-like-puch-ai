# Deployment Quick Start Guide

Complete guide for deploying the Exotel AgentStream voice AI PoC locally or to production.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development Setup](#local-development-setup)
3. [Server Startup Modes](#server-startup-modes)
4. [Exposing with ngrok](#exposing-with-ngrok)
5. [Local Testing](#local-testing)
6. [Pre-Flight Checklist](#pre-flight-checklist)
7. [Comprehensive Troubleshooting](#comprehensive-troubleshooting)
8. [Production Deployment](#production-deployment)

---

## Prerequisites

### System Requirements

- **Python 3.11+** with pip
- **Node.js 18+** (optional, for frontend)
- **curl** or Postman (for API testing)
- **Minimum 2GB RAM** for server + dependencies
- **Minimum 500MB disk space** for dependencies

### Exotel Account (for production)

- Exotel account with SIP trunk access
- Exotel API credentials (API key, API token)
- Phone number assigned to your account
- VoiceBot applet capabilities enabled

### Environment Setup

```bash
# Clone repository (if not already done)
git clone <repository-url>
cd poc-like-puch-ai

# Create Python virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # macOS/Linux
# OR
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## Local Development Setup

### Step 1: Configure Environment Variables

Create `.env` file in the project root:

```bash
# Copy from example
cp .env.example .env

# Edit .env with your settings
nano .env
```

**For local DEV_MODE (no external credentials):**

```env
# Server config
LOG_LEVEL=DEBUG
PORT=8000
HOST=0.0.0.0

# Dev mode (uses stubs, no credentials needed)
DEV_MODE=true

# Optional: Logging
ENABLE_CONSOLE_LOGGING=true
```

**For local HYBRID_MODE (real Google providers):**

```env
LOG_LEVEL=DEBUG
PORT=8000
HOST=0.0.0.0
HYBRID_MODE=true

# Google Cloud credentials (create service account)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
```

**For production (all real providers):**

```env
LOG_LEVEL=INFO
PORT=8000
HOST=0.0.0.0
DEV_MODE=false
HYBRID_MODE=false

# Google Cloud credentials
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# Gemini API key
GEMINI_API_KEY=your-api-key-here

# Database (PostgreSQL)
DATABASE_URL=postgresql://user:pass@localhost:5432/exotel_voicebot

# Redis cache
REDIS_URL=redis://localhost:6379

# Exotel IPs for whitelist (get from Exotel docs)
ALLOWED_IPS=1.2.3.4,5.6.7.8

# Or use Basic Auth instead of IP whitelist
API_KEY=your-api-key
API_TOKEN=your-api-token
```

### Step 2: Verify Prerequisites

```bash
# Check Python version
python3 --version  # Should be 3.11 or higher

# Check curl is available
curl --version

# Check port 8000 is free
lsof -i :8000  # Should return nothing

# Verify dependencies installed
pip list | grep fastapi  # Should show fastapi
```

If port 8000 is in use:
```bash
# Find and kill process using port 8000
lsof -i :8000
kill -9 <PID>
```

---

## Server Startup Modes

### Mode 1: DEV_MODE (Local Development - Recommended)

**Use case:** Local testing, development, demo without any external credentials

```bash
DEV_MODE=true LOG_LEVEL=DEBUG python3 -m src.infrastructure.server
```

**Features:**
- Stub STT/TTS (instant responses)
- Stub LLM (returns fixed responses)
- No external API calls
- No credentials needed
- Perfect for testing locally

**Expected output:**
```
[2025-04-11T10:30:45] INFO Starting OpenTelemetry initialization
[2025-04-11T10:30:46] INFO DEV_MODE enabled - using stub adapters
[2025-04-11T10:30:47] INFO Uvicorn running on http://0.0.0.0:8000
[2025-04-11T10:30:48] INFO Application startup complete
```

### Mode 2: HYBRID_MODE (Real Google Providers)

**Use case:** Test with real STT/TTS without Gemini quota

```bash
# Set up Google Cloud credentials first
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

HYBRID_MODE=true python3 -m src.infrastructure.server
```

**Features:**
- Real Google Cloud STT (converts audio to text)
- Real Google Cloud TTS (converts text to audio)
- Stub LLM (returns fixed responses)
- Requires Google Cloud credentials
- Good for testing audio quality

### Mode 3: Production Mode (All Real)

**Use case:** Full production with real AI responses

```bash
# Set all credentials
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
export GEMINI_API_KEY=your-gemini-api-key

python3 -m src.infrastructure.server
```

**Features:**
- Real Google Cloud STT/TTS
- Real Google Gemini LLM
- All external integrations active
- Requires all credentials
- Best conversation quality

**Database and Redis (optional for scaling):**
```bash
# Start PostgreSQL (if using)
docker run -p 5432:5432 postgres:15

# Start Redis (if using)
docker run -p 6379:6379 redis:7
```

---

## Exposing with ngrok

### Step 1: Install ngrok

**macOS:**
```bash
brew install ngrok
```

**Windows:**
```bash
# Download from https://ngrok.com/download
# Or use Chocolatey
choco install ngrok
```

**Linux:**
```bash
# Download from https://ngrok.com/download
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.zip
unzip ngrok-v3-stable-linux-amd64.zip
sudo mv ngrok /usr/local/bin/
```

### Step 2: Start Server (if not already running)

Terminal 1:
```bash
cd poc-like-puch-ai
DEV_MODE=true LOG_LEVEL=DEBUG python3 -m src.infrastructure.server

# Expected: "Application startup complete"
```

### Step 3: Start ngrok Tunnel

Terminal 2:
```bash
ngrok http 8000
```

Expected output:
```
ngrok                                                          (Ctrl+C to quit)

Forwarding    https://abc123def456.ngrok-free.app -> http://localhost:8000
Forwarding    http://abc123def456.ngrok-free.app -> http://localhost:8000

Status                 online                                    
Session Expires        2 hours, 55 minutes
Connections            0/20
Data In                0 B
Data Out               0 B
```

### Step 4: Extract Your Public URLs

From ngrok output:

**WebSocket endpoint (for Exotel):**
```
wss://abc123def456.ngrok-free.app/stream?sample-rate=8000
```

**REST endpoints:**
```
Health:  https://abc123def456.ngrok-free.app/health
Passthru: https://abc123def456.ngrok-free.app/passthru
Metrics: https://abc123def456.ngrok-free.app/metrics (if exposed)
```

**Save these URLs!** You'll need the WSS URL for Exotel configuration.

---

## Local Testing

### Test 1: Health Check

Terminal 3:
```bash
# Replace abc123def456 with your ngrok URL
curl https://abc123def456.ngrok-free.app/health

# Expected response:
# {"status":"ok","active_sessions":0,"uptime_seconds":45}
```

### Test 2: Passthru Endpoint

```bash
curl -X POST https://abc123def456.ngrok-free.app/passthru \
  -H "Content-Type: application/json" \
  -d '{
    "input": "What is the weather today?",
    "context": {"user_id": "test123"}
  }'

# Expected response:
# {"output":"Hello, I am an AI assistant...","status":"success"}
```

### Test 3: WebSocket Simulator

Terminal 4:
```bash
cd poc-like-puch-ai
python3 scripts/sim_exotel.py
```

Expected output:
```
Running Exotel AgentStream Simulator...

Testing scenario: basic_call
  Status: PASSED
  - Connected to WebSocket
  - Processed 5 audio frames
  - Received AI response

Testing scenario: clear_call
  Status: PASSED

Testing scenario: dtmf
  Status: PASSED

Testing scenario: concurrent_calls
  Status: PASSED

Testing scenario: passthru_test
  Status: PASSED

Summary:
  Total scenarios: 5
  Passed: 5
  Failed: 0
  Success rate: 100%
```

### Test 4: Run Test Suite

Terminal 5:
```bash
cd poc-like-puch-ai

# Run all tests
python3 -m pytest

# Or run specific test suite
python3 -m pytest tests/unit/  # Unit tests only
python3 -m pytest tests/integration/  # Integration tests
python3 -m pytest tests/smoke/  # Smoke tests
```

Expected output:
```
collected 698 items
tests/unit/... PASSED
tests/integration/... PASSED
tests/smoke/... PASSED

================== 698 passed in 45.23s ==================
```

---

## Pre-Flight Checklist

### Before connecting to Exotel:

```
✅ Server starts without errors
   Command: DEV_MODE=true python3 -m src.infrastructure.server

✅ Health endpoint responds
   Command: curl http://localhost:8000/health

✅ ngrok tunnel is active
   Command: ngrok http 8000

✅ Public URL is accessible
   Command: curl https://abc123def456.ngrok-free.app/health

✅ WebSocket simulator passes all tests
   Command: python3 scripts/sim_exotel.py

✅ All unit tests pass
   Command: python3 -m pytest tests/unit/

✅ All integration tests pass
   Command: python3 -m pytest tests/integration/

✅ No errors in server logs
   Look at Terminal 1 for "ERROR" or "EXCEPTION"

✅ WSS URL is correctly formatted
   Format: wss://abc123def456.ngrok-free.app/stream?sample-rate=8000
   ✓ Starts with wss:// (not ws://)
   ✓ Has sample-rate parameter
   ✓ Sample rate is 8000, 16000, or 24000

✅ Ngrok is in free tier or paid
   If using free tier: URL changes on each restart (acceptable for testing)
   For production: upgrade to paid ngrok for persistent URL
```

---

## Comprehensive Troubleshooting

### Server Issues

#### Problem: "Address already in use"

```bash
# Find process on port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>

# Restart server
DEV_MODE=true python3 -m src.infrastructure.server
```

#### Problem: "ModuleNotFoundError: No module named 'src'"

```bash
# Make sure you're in the right directory
cd poc-like-puch-ai

# Reinstall dependencies
pip install -r requirements.txt

# Try again
python3 -m src.infrastructure.server
```

#### Problem: Server starts but immediately exits

```bash
# Check error messages (may have scrolled off)
DEV_MODE=true python3 -m src.infrastructure.server 2>&1 | tail -20

# Common causes:
# 1. Missing environment variable
# 2. Corrupted virtual environment → recreate it
python3 -m venv venv_new
source venv_new/bin/activate
pip install -r requirements.txt
```

#### Problem: "Permission denied" error

```bash
# Make scripts executable
chmod +x scripts/sim_exotel.py
chmod +x scripts/run_local_validation.sh

# Try again
python3 scripts/sim_exotel.py
```

---

### ngrok Issues

#### Problem: "Cannot connect to localhost:8000"

1. **Server is not running**
   ```bash
   # Check if server is still running in other terminal
   curl http://localhost:8000/health
   
   # If fails, restart server
   DEV_MODE=true python3 -m src.infrastructure.server
   ```

2. **Wrong port in ngrok**
   ```bash
   # Make sure you're using port 8000
   ngrok http 8000  # ✓ Correct
   ngrok http 3000  # ✗ Wrong
   ```

3. **Firewall is blocking**
   ```bash
   # Allow port 8000 through firewall
   # macOS: System Preferences → Security & Privacy → Firewall
   # Windows: Windows Defender Firewall → Allow app through firewall
   ```

#### Problem: "Invalid tunnel URL"

**If Exotel reports invalid URL:**

1. Check WSS format: `wss://` not `ws://`
   ```
   ✓ wss://abc123def456.ngrok-free.app/stream?sample-rate=8000
   ✗ ws://abc123def456.ngrok-free.app/stream?sample-rate=8000
   ```

2. Check sample-rate parameter:
   ```
   ✓ ?sample-rate=8000   (8000, 16000, or 24000)
   ✗ ?samplerate=8000    (wrong parameter name)
   ✗ ?sample-rate=44100  (unsupported rate)
   ```

3. Check URL is fully copied (no extra spaces)
   ```
   ✓ wss://abc123def456.ngrok-free.app/stream?sample-rate=8000
   ✗ wss://abc123def456.ngrok-free.app/stream?sample-rate=8000 (extra space)
   ```

#### Problem: "Connection refused" from Exotel

1. **Server is down**
   ```bash
   # Test locally first
   curl http://localhost:8000/health
   
   # If fails, restart server
   DEV_MODE=true python3 -m src.infrastructure.server
   ```

2. **ngrok tunnel is down**
   ```bash
   # Restart ngrok
   ngrok http 8000
   
   # Copy new URL and update Exotel configuration
   ```

3. **Firewall is blocking Exotel**
   - Exotel IPs might be blocked
   - Add exception for Exotel IP range
   - Or disable firewall temporarily for testing

#### Problem: "ngrok URL keeps changing"

**This is normal on free tier!**

- Free ngrok generates new URL on each restart
- URL expires after 2 hours of inactivity
- **Solution for testing:** Just update Exotel with new URL
- **Solution for production:** Upgrade to paid ngrok ($5/month)

---

### Testing Issues

#### Problem: "pytest: command not found"

```bash
# Install pytest
pip install pytest pytest-asyncio pytest-cov

# Try again
python3 -m pytest tests/
```

#### Problem: "Some tests are failing"

```bash
# Run just one failing test to see details
python3 -m pytest tests/unit/test_specific.py -v

# See full error trace
python3 -m pytest tests/ -vv --tb=long

# Common causes:
# 1. External API credentials missing → use DEV_MODE
# 2. Database not running → not needed for DEV_MODE
# 3. Port already in use → kill the process using it
```

#### Problem: "Simulator reports failed scenarios"

```bash
# Check server is running
curl http://localhost:8000/health

# Check server logs for errors
# (Look at Terminal 1 where server is running)

# Run simulator with verbose output
python3 scripts/sim_exotel.py -v

# Common causes:
# 1. Server crashed → restart with DEV_MODE=true
# 2. Port 8000 not accessible → check firewall
# 3. Audio processing issue → check logs for details
```

---

### Exotel Connection Issues

#### Problem: "WebSocket connection fails"

1. **Wrong WSS URL format**
   ```
   ✓ wss://abc123def456.ngrok-free.app/stream?sample-rate=8000
   ✗ http://... (should be wss://)
   ✗ https://... (should be wss://)
   ```

2. **Sample-rate parameter missing or wrong**
   ```
   ✓ ?sample-rate=8000
   ✗ (no parameter)
   ✗ ?sample-rate=44100 (unsupported)
   ```

3. **Authentication fails**
   - If using IP whitelist: Make sure Exotel's IP is allowed
   - If using Basic auth: Make sure credentials are correct
   - Test with curl first:
     ```bash
     curl -u api_key:api_token https://abc123def456.ngrok-free.app/health
     ```

#### Problem: "Audio is choppy or missing"

1. **Check sample rate matches**
   - Server: `?sample-rate=8000`
   - Exotel: Must match (8000, 16000, or 24000)

2. **Check network latency**
   ```bash
   # Ping ngrok URL
   ping abc123def456.ngrok-free.app
   # Should be < 100ms for acceptable quality
   ```

3. **Check audio buffer settings**
   - Look at server logs for audio chunk sizes
   - Should be > 320 bytes (1 audio frame)
   - Check for buffer overflow warnings

#### Problem: "Exotel shows no active streams"

1. **Check WebSocket is connecting**
   ```bash
   # Monitor server logs (Terminal 1)
   # Should see "WebSocket connected" message
   ```

2. **Check Exotel applet configuration**
   - Navigate to App Bazaar
   - Edit VoiceBot applet
   - Verify WSS URL is correct and active
   - Verify sample rate is set correctly

3. **Check custom parameters syntax**
   - Max 3 parameters
   - Total length ≤ 256 characters
   - Format: `key1=value1&key2=value2`

---

## Production Deployment

### Before Production

1. **Generate real credentials**
   ```bash
   # Get Google Cloud service account JSON
   # Get Gemini API key from Google AI Studio
   # Get Exotel API credentials from dashboard
   ```

2. **Set production environment variables**
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   export GEMINI_API_KEY=your-gemini-key
   export API_KEY=your-exotel-api-key
   export API_TOKEN=your-exotel-api-token
   ```

3. **Set up database and cache (optional but recommended)**
   ```bash
   # PostgreSQL for session storage
   docker run -p 5432:5432 postgres:15
   
   # Redis for distributed caching
   docker run -p 6379:6379 redis:7
   ```

4. **Deploy to cloud (AWS, GCP, Azure, Heroku)**
   - Use Docker (see Dockerfile in repo)
   - Set environment variables in cloud dashboard
   - Expose port 8000 (or your chosen port)
   - Configure domain name (instead of ngrok)
   - Enable HTTPS (most cloud platforms do this automatically)

5. **Update Exotel configuration**
   - Update WebSocket URL to production domain
   - Set authentication (IP whitelist or Basic auth)
   - Test with real phone numbers

See deployment guides in `ops/` directory for detailed platform-specific instructions.

---

## Quick Reference

### Common Commands

```bash
# Start server (DEV mode)
cd poc-like-puch-ai && DEV_MODE=true python3 -m src.infrastructure.server

# Start ngrok tunnel
ngrok http 8000

# Test health endpoint
curl https://YOUR_NGROK_URL/health

# Run simulator
python3 scripts/sim_exotel.py

# Run all tests
python3 -m pytest

# Check logs
# Terminal 1 (where server is running) shows live logs
```

### URLs to Remember

```
Local: http://localhost:8000
Public (via ngrok): https://abc123def456.ngrok-free.app

WebSocket endpoint: wss://abc123def456.ngrok-free.app/stream?sample-rate=8000
Health check: https://abc123def456.ngrok-free.app/health
Passthru: https://abc123def456.ngrok-free.app/passthru
```

### Ports

```
8000 - Server (FastAPI)
5432 - PostgreSQL (if using)
6379 - Redis (if using)
```

---

## Next Steps

1. ✅ Complete this guide
2. ✅ Server running locally with ngrok
3. ✅ All tests passing
4. ▶️ **Next:** Connect to Exotel Dashboard ([EXOTEL_DASHBOARD_WALKTHROUGH.md](./EXOTEL_DASHBOARD_WALKTHROUGH.md))
5. ▶️ **Then:** Make your first real call!

Good luck! 🚀
