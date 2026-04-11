# Quick Start: Local Development with ngrok (5 Minutes)

This guide gets you up and running with the Exotel AgentStream voice AI PoC in 5 minutes using ngrok for local WebSocket exposure.

## Prerequisites

- **Python 3.11+** — [Download here](https://www.python.org/downloads/)
- **curl** — Pre-installed on macOS/Linux; [Download for Windows](https://curl.se/download.html)
- **Internet connection** — For ngrok tunneling
- **Exotel credentials** (optional for local testing with stubs)

## Step 1: Install Dependencies (1 minute)

```bash
# Navigate to project directory
cd poc-like-puch-ai

# Install Python dependencies
pip install -r requirements.txt
```

Expected output:
```
Successfully installed [list of packages]...
```

## Step 2: Start the Server Locally (1 minute)

```bash
# Start server in DEV_MODE (uses stubs, no credentials needed)
DEV_MODE=true LOG_LEVEL=DEBUG python3 -m src.infrastructure.server
```

Expected output:
```
[2025-04-11T10:30:45.123Z] INFO: Starting OpenTelemetry initialization
[2025-04-11T10:30:46.456Z] INFO: Initializing adapters (DEV_MODE: stubs)
[2025-04-11T10:30:47.789Z] INFO: Uvicorn running on http://0.0.0.0:8000
[2025-04-11T10:30:48.012Z] INFO: Application startup complete
```

**Keep this terminal running!** It will show incoming WebSocket messages.

## Step 3: Install and Start ngrok (2 minutes)

Open a **new terminal** (keep the server running in the first one).

### Install ngrok

**macOS:**
```bash
brew install ngrok
```

**Windows:**
```bash
# Download from https://ngrok.com/download
# Or use Windows package manager:
choco install ngrok  # if using Chocolatey
```

**Linux:**
```bash
# Download from https://ngrok.com/download
# Or use apt:
sudo apt-get install ngrok  # if available in your package manager
```

### Start the Tunnel

```bash
# Expose local port 8000 to public internet
ngrok http 8000
```

Expected output:
```
ngrok                                                          (Ctrl+C to quit)

Forwarding    https://abc123-def456.ngrok-free.app -> http://localhost:8000
Forwarding    http://abc123-def456.ngrok-free.app -> http://localhost:8000

Status                 online                                    
Session Expires        2 hours, 55 minutes
Connections            0/20
Data In                0 B
Data Out               0 B
```

**Save the URL** (e.g., `abc123-def456.ngrok-free.app`) — you'll need it for Exotel!

## Step 4: Test the Server (1 minute)

Open a **third terminal**. Test that the server is running:

```bash
# Test health endpoint
curl https://abc123-def456.ngrok-free.app/health
```

Expected output:
```json
{
  "status": "ok",
  "active_sessions": 0,
  "uptime_seconds": 45
}
```

## Step 5: Get Your WSS Endpoint

Your WebSocket endpoint is ready:

```
wss://abc123-def456.ngrok-free.app/stream?sample-rate=8000
```

Replace `abc123-def456` with the actual ngrok URL from Step 3.

### Other Useful Endpoints

```
Health Check:    https://abc123-def456.ngrok-free.app/health
Passthru:        https://abc123-def456.ngrok-free.app/passthru
Metrics:         https://abc123-def456.ngrok-free.app/metrics
```

## Step 6 (Optional): Test WebSocket Locally

Test the WebSocket endpoint with the built-in simulator:

```bash
# In a new terminal, run the simulator
python3 scripts/sim_exotel.py
```

Expected output:
```
Running Exotel AgentStream Simulator...
Scenario: basic_call
  - Simulating incoming call...
  - Connected to WebSocket
  - Sending audio frames...
  - Received AI response: "Hello, how can I help you?"
  - ✓ PASSED
```

## Next Steps: Connect to Exotel

1. **Copy your WSS endpoint** from Step 5
2. **Go to Exotel Dashboard** → App Bazaar → Create VoiceBot Applet
3. **Paste WSS URL** in the VoiceBot applet configuration
4. **Add authentication** (IP whitelist or Basic auth)
5. **Test with a real call!**

See [EXOTEL_DASHBOARD_WALKTHROUGH.md](./EXOTEL_DASHBOARD_WALKTHROUGH.md) for detailed Exotel setup.

---

## Troubleshooting

### Issue: Server won't start

**Error:** `Address already in use`
```bash
# Find process using port 8000
lsof -i :8000

# Kill the process (replace PID)
kill -9 <PID>

# Then restart server
DEV_MODE=true python3 -m src.infrastructure.server
```

### Issue: ngrok tunnel not working

**Error:** `Cannot connect to localhost:8000`
- Make sure the server is running in the first terminal
- Verify with: `curl http://localhost:8000/health`

### Issue: "Invalid tunnel URL"

**Error:** Exotel reports invalid WSS URL
- Make sure URL starts with `wss://` (not `ws://`)
- Verify sample-rate parameter: `?sample-rate=8000` (8000, 16000, or 24000)
- Full URL format: `wss://abc123.ngrok-free.app/stream?sample-rate=8000`

### Issue: "Connection refused" from Exotel

**Possible causes:**
1. Server is not running → restart with `DEV_MODE=true python3 -m src.infrastructure.server`
2. ngrok tunnel is down → restart with `ngrok http 8000`
3. firewall is blocking → check firewall settings
4. Wrong port in ngrok → verify `ngrok http 8000` (not another port)

### Issue: ngrok URL keeps changing

**Note:** Free tier generates new URL on each restart. To keep the same URL:
- **Upgrade to paid ngrok** (recommended for production)
- **Or use ngrok agent** with saved config

### Issue: Certificate warnings

**Error:** `certificate_verify_failed`
- This is normal with ngrok free tier self-signed certs in some contexts
- Exotel handles this automatically
- For local curl testing, use `curl -k` (skip certificate check)

### Issue: Rate limiting

**Error:** `429 Too Many Requests`
- Free tier has rate limits (~20 requests/second)
- Reduce concurrent connections or upgrade to paid plan

---

## Additional Resources

- **Full Deployment Guide:** [DEPLOYMENT_QUICK_START.md](./DEPLOYMENT_QUICK_START.md)
- **Exotel Dashboard Setup:** [EXOTEL_DASHBOARD_WALKTHROUGH.md](./EXOTEL_DASHBOARD_WALKTHROUGH.md)
- **Exotel Official Docs:** https://docs.exotel.com/exotel-agentstream/agentstream
- **Complete Setup Guide:** [exotel-setup-guide.md](./exotel-setup-guide.md)
- **Simulator Documentation:** [scripts/sim_exotel.py](../scripts/sim_exotel.py)

---

## Time Tracking

| Step | Time | Notes |
|------|------|-------|
| Prerequisites | 1 min | Install dependencies |
| Start Server | 1 min | DEV_MODE setup |
| Install & Start ngrok | 2 min | Expose to public |
| Test Server | 1 min | Health check |
| Get WSS Endpoint | - | Copy from ngrok output |
| **Total** | **~5 min** | Ready for Exotel! |

---

## Next: Exotel Dashboard

Once your server and ngrok are running:

1. Open [Exotel Dashboard](https://exotel.com)
2. Navigate to **App Bazaar** → **VoiceBot**
3. Create new VoiceBot applet with WSS URL from Step 5
4. Assign a phone number
5. Make your first test call!

See [EXOTEL_DASHBOARD_WALKTHROUGH.md](./EXOTEL_DASHBOARD_WALKTHROUGH.md) for detailed step-by-step instructions.

Good luck! 🚀
