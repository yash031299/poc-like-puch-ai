# Exotel Dashboard Walkthrough: Connect Your VoiceBot

Step-by-step guide to configure your Exotel AgentStream VoiceBot applet and make your first call.

## Prerequisites

- ✅ Server running locally or deployed
- ✅ ngrok tunnel active (or public domain)
- ✅ WSS endpoint ready: `wss://YOUR_URL/stream?sample-rate=8000`
- ✅ Exotel account created and activated
- ✅ Phone number assigned to your account

---

## Step 1: Sign In to Exotel Dashboard

1. Open https://exotel.com/app
2. Sign in with your email and password
3. You should see the main dashboard

---

## Step 2: Navigate to App Bazaar

In the left sidebar:

1. Click **"App Bazaar"** or **"Applications"**
2. Look for **"VoiceBot"** application
3. Click **"Install"** or **"Create"** (text may vary)

Expected screen:
```
[Dashboard] → [App Bazaar] → [VoiceBot] → [Install/Create]
```

---

## Step 3: Create VoiceBot Applet

You'll see a form with these fields:

### Field: Applet Name
```
Label: "Applet Name" or "Bot Name"
Example: "MyAIVoiceBot"
What to enter: Any descriptive name for your bot
```

### Field: WebSocket URL (CRITICAL)
```
Label: "WebSocket URL" or "Stream URL"
Format: wss://YOUR_DOMAIN/stream
Example: wss://abc123def456.ngrok-free.app/stream?sample-rate=8000

What to enter:
- Replace abc123def456 with your actual ngrok URL
- Must start with wss:// (not http:// or ws://)
- Must include sample-rate parameter
- Supported sample rates: 8000, 16000, 24000 Hz
```

### Field: Sample Rate (if separate field)
```
Label: "Sample Rate" or "Audio Sample Rate"
Options: 8000, 16000, 24000 Hz
Recommendation: 8000 Hz (standard for voice calls)
What to enter: 8000
```

### Field: Authentication Type (Important)
```
Label: "Authentication" or "Auth Method"
Options:
  A) IP Whitelist (if you know Exotel's IP range)
  B) Basic Auth (username:password)
  C) None (for local testing only)

RECOMMENDED FOR LOCAL TESTING:
  Choose: "Basic Auth" (more reliable than IP whitelist)
```

If you choose **Basic Auth**:

#### Sub-field: API Key
```
Label: "API Key" or "Username"
What to enter: Your Exotel API Key
Where to find: Exotel Dashboard → Account Settings → API Credentials
```

#### Sub-field: API Token
```
Label: "API Token" or "Token"
What to enter: Your Exotel API Token
Where to find: Exotel Dashboard → Account Settings → API Credentials
```

If you choose **IP Whitelist**:
```
Label: "Allowed IPs"
What to enter: Exotel's IP range (ask support or check docs)
Example: 1.2.3.4/32 or 1.2.3.0/24
```

### Field: Custom Parameters (Optional)
```
Label: "Custom Parameters" or "Extra Params"
Format: key1=value1&key2=value2

Example (for testing):
  stream_id=voicebot_001
  region=us-east-1
  environment=dev

Limits:
  - Max 3 parameters
  - Total length ≤ 256 characters
  - Use URL-encoded values

Leave blank if unsure.
```

### Field: Recording (Optional)
```
Label: "Enable Recording" or "Recording"
Options: Enable / Disable
Recommendation: Enable (for debugging)
```

### Field: Webhook URL (Optional)
```
Label: "Webhook URL" or "Callback URL"
What to enter: Leave blank for now
Note: Use this to receive call end events to your backend
```

---

## Step 4: Save VoiceBot Applet

1. Click **"Create"** or **"Save"** button
2. You should see: "VoiceBot applet created successfully"
3. Note your applet ID (you'll need it for the next step)

Expected confirmation:
```
✓ VoiceBot Applet 'MyAIVoiceBot' created
  ID: applet_abc123xyz789
  Status: Active
```

---

## Step 5: Assign Phone Number to VoiceBot

Now you need to connect a phone number to your VoiceBot applet.

### Step 5a: Navigate to Phone Numbers

In the left sidebar:
1. Click **"Phone Numbers"** or **"Incoming Numbers"**
2. Find your assigned phone number

### Step 5b: Configure Call Flow

1. Click on your phone number to edit it
2. Look for **"Call Flow"** or **"Incoming Call Routing"**
3. You should see options like:
   ```
   [ ] IVR
   [ ] Web URL
   [ ] SIP Trunk
   [X] VoiceBot
   ```

4. Select **"VoiceBot"**

### Step 5c: Select Your VoiceBot Applet

A dropdown will appear:
```
Select VoiceBot: [Dropdown showing your applets]
  ├─ MyAIVoiceBot  ← Select this
  ├─ OtherBot
  └─ ...
```

Choose the VoiceBot applet you just created: **"MyAIVoiceBot"**

### Step 5d: Configure Additional Options

You might see these optional fields:

**Fallback Handling:**
```
Label: "If bot fails, try"
Options: Disconnect / Forward to number / Voicemail
Recommendation: Disconnect (for testing)
```

**Call Recording:**
```
Label: "Record call"
Options: Yes / No
Recommendation: Yes (for debugging)
```

**Timeout:**
```
Label: "Call timeout (minutes)"
Default: 30
Recommendation: Keep default
```

### Step 5e: Save Phone Number Configuration

1. Click **"Save"** button
2. Confirmation: "Phone number configured successfully"

---

## Step 6: Test Connection

### Before Making a Real Call

1. **Verify server is running**
   ```bash
   curl http://localhost:8000/health
   # Expected: {"status":"ok"}
   ```

2. **Verify ngrok is active**
   ```bash
   # Should see "Status: online" in ngrok terminal
   ```

3. **Check Exotel dashboard**
   - VoiceBot status: "Active"
   - Phone number routing: Points to VoiceBot
   - Network connectivity: Green indicator

### Make Your First Test Call

1. **From any phone**, dial your assigned Exotel number
2. **Listen for**:
   - Ring tone for 1-2 seconds (normal)
   - VoiceBot answering: "Hello, this is an AI assistant"
   - Silence (waiting for you to speak)

3. **Say something** like "Hello" or "How are you?"
4. **Listen for** AI response (3-5 seconds later)

### Expected Call Flow

```
Timeline:
  0s    → You dial Exotel number
  1s    → Call connects to VoiceBot
  2s    → "Hello, I'm an AI assistant" (TTS response)
  3s    → Waiting for your input...
  5s+   → You speak
  6s    → Speech captured and sent to AI
  8s    → AI generates response
  10s   → Response spoken to you (TTS)
```

### Verify in Server Logs

In Terminal 1 (where server is running), you should see:

```
[2025-04-11T10:45:30] INFO: WebSocket connected - stream_id: stream_xyz123
[2025-04-11T10:45:31] INFO: Received audio frame 1 (3200 bytes)
[2025-04-11T10:45:32] INFO: Utterance complete - detected silence
[2025-04-11T10:45:32] INFO: STT result: "hello"
[2025-04-11T10:45:33] INFO: LLM response: "Hello, how can I help?"
[2025-04-11T10:45:34] INFO: Streaming TTS response (5 chunks)
[2025-04-11T10:45:37] INFO: WebSocket disconnected - stream_id: stream_xyz123
```

---

## Step 7: Troubleshooting First Call

### Problem: Call doesn't connect

**Check:**
1. Phone number is properly assigned to VoiceBot
2. VoiceBot applet status is "Active"
3. Server is running: `curl http://localhost:8000/health`
4. ngrok tunnel is active: Check ngrok terminal for "Status: online"

**Fix:**
1. Restart server: `DEV_MODE=true python3 -m src.infrastructure.server`
2. Restart ngrok: `ngrok http 8000`
3. Update WSS URL in VoiceBot applet with new ngrok URL

### Problem: Call connects but no voice response

**Check:**
1. Server logs (Terminal 1) for errors
2. Ngrok logs for connection issues
3. WSS URL format: Must be `wss://` (not `http://`)
4. Sample-rate parameter: Correct value (8000, 16000, or 24000)

**Fix:**
1. Check server logs: Look for "ERROR" messages
2. Check audio format: Should be PCM 16-bit little-endian
3. Check authentication: If using Basic Auth, verify credentials

### Problem: Audio quality is poor or choppy

**Check:**
1. Network latency: `ping abc123def456.ngrok-free.app`
2. Sample rate matches: Server and Exotel should agree
3. Audio chunk size: Should be multiples of 320 bytes

**Fix:**
1. Reduce network latency (use paid ngrok, cloud deployment)
2. Verify sample rate consistency
3. Check buffer settings in server logs

### Problem: No server logs appearing

**Check:**
1. Server is actually running: `curl http://localhost:8000/health`
2. LOG_LEVEL is set correctly: `export LOG_LEVEL=DEBUG`

**Fix:**
1. Restart server with explicit log level:
   ```bash
   DEV_MODE=true LOG_LEVEL=DEBUG python3 -m src.infrastructure.server
   ```

### Problem: "Connection refused" from Exotel

**Check:**
1. WSS URL is exactly correct (no typos, no extra spaces)
2. ngrok tunnel is active
3. Sample-rate parameter is present and valid
4. Authentication credentials are correct (if using Basic Auth)

**Fix:**
1. Re-copy WSS URL from ngrok output
2. Update VoiceBot applet with new URL
3. Wait 30 seconds for change to propagate
4. Try again

---

## Step 8: Make Real Calls (Production Testing)

Once your first test call succeeds:

1. **Make multiple calls** (5-10) to test consistency
2. **Test from different phones** (landline, mobile, etc.)
3. **Test different inputs**:
   - Long utterances: "Tell me a joke"
   - Short utterances: "Hi"
   - Silence: Just wait (should timeout after 30s)
   - Background noise: See if it's filtered

4. **Check audio quality**:
   - Can you understand the AI response?
   - Is there echo or feedback?
   - Are there gaps in audio?

5. **Monitor performance**:
   - How long until first response? (target: < 5 seconds)
   - How long for subsequent responses? (target: < 3 seconds)
   - Do calls drop unexpectedly?

---

## Step 9: Advanced Configuration (Optional)

### Add Passthru Endpoint (for HTTP calls)

If you want to handle voice calls via HTTP instead of WebSocket:

1. In App Bazaar, look for **"HTTP Voice"** or **"Passthru"** applet
2. Configure endpoint: `https://abc123def456.ngrok-free.app/passthru`
3. Add to phone number routing as fallback

### Add Call Recording with Webhook

To receive call events (start, end, etc.):

1. Create a webhook endpoint in your backend
2. Update VoiceBot applet: Set "Webhook URL" to your endpoint
3. You'll receive POST requests with call data

### Custom Parameters

Pass data through WebSocket URL:

```
wss://abc123def456.ngrok-free.app/stream?
  sample-rate=8000&
  tenant_id=org_123&
  session_id=call_456
```

The server can access these in custom parameters.

---

## Step 10: Monitor and Debug

### View Active Calls

In Exotel Dashboard:
1. Click **"Active Calls"** or **"Streams"**
2. You should see:
   ```
   Call ID: c_xyz123
   Duration: 00:05:23
   Status: Active
   From: +91-9876543210
   Stream: stream_abc123
   ```

### View Call Logs

1. Click **"Call Logs"** or **"History"**
2. Select date range
3. View details for each call:
   - Duration
   - Status (connected, failed, etc.)
   - Recording link
   - Any error messages

### Download Call Recording

1. Find call in logs
2. Click **"Download Recording"** or **"Play"**
3. Listen to verify audio quality

---

## Checklist: Before Going to Production

- ✅ VoiceBot applet created and active
- ✅ Phone number assigned to VoiceBot
- ✅ WSS URL is correct format: `wss://domain/stream?sample-rate=8000`
- ✅ Authentication configured (IP whitelist or Basic Auth)
- ✅ Server running and accessible via public URL
- ✅ ngrok tunnel (or cloud domain) is active
- ✅ First test call successful
- ✅ Audio quality acceptable
- ✅ Server logs show expected messages
- ✅ All tests pass: `python3 -m pytest`
- ✅ Performance is acceptable (first response < 5s)

---

## Quick Reference: URLs and Info

### Your URLs
```
Public domain:     abc123def456.ngrok-free.app
WebSocket:         wss://abc123def456.ngrok-free.app/stream?sample-rate=8000
Health check:      https://abc123def456.ngrok-free.app/health
```

### Your Exotel Info
```
Account email:     your@email.com
Account ID:        acc_xyz123
Phone number:      +91-XXXXXXXXXX
VoiceBot ID:       applet_abc123xyz789
```

### Server Credentials (if using Basic Auth)
```
API Key:           your-api-key-here
API Token:         your-api-token-here
```

---

## Need Help?

- **Server issues?** → See [DEPLOYMENT_QUICK_START.md](./DEPLOYMENT_QUICK_START.md) troubleshooting section
- **Exotel documentation?** → https://docs.exotel.com/exotel-agentstream/agentstream
- **General setup?** → See [exotel-setup-guide.md](./exotel-setup-guide.md)
- **Quick start with ngrok?** → See [QUICK_START_NGROK.md](./QUICK_START_NGROK.md)

---

## Summary

You're now ready to:
1. ✅ Start server locally with DEV_MODE
2. ✅ Expose via ngrok
3. ✅ Connect VoiceBot applet
4. ✅ Assign phone number
5. ✅ Make your first call!

**Congratulations! You now have a working AI voice assistant.** 🎉

Good luck with your VoiceBot! 🚀
