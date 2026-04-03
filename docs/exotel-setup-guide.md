# Exotel Account Setup & Integration Guide

> **Goal:** Route a real phone call through Exotel → your Puch AI server → Gemini LLM → back to caller.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Exotel Account Setup](#2-exotel-account-setup)
3. [Get Your Exotel API Credentials](#3-get-your-exotel-api-credentials)
4. [Buy a Phone Number](#4-buy-a-phone-number)
5. [Expose Your Server Publicly](#5-expose-your-server-publicly)
6. [Build the Call Flow in App Bazaar](#6-build-the-call-flow-in-app-bazaar)
7. [Assign the App to Your Phone Number](#7-assign-the-app-to-your-phone-number)
8. [Make a Test Call](#8-make-a-test-call)
9. [Monitor Live Calls](#9-monitor-live-calls)
10. [Authentication Options](#10-authentication-options)
11. [Passthru Applet Reference](#11-passthru-applet-reference)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

Before you start, make sure you have:

- [ ] Your Puch AI server running (`python -m src.infrastructure.server`)
- [ ] A publicly accessible HTTPS/WSS URL (ngrok, Render, Railway, EC2, etc.)
- [ ] Your `.env` file populated with `GEMINI_API_KEY`
- [ ] (Optional) `GOOGLE_APPLICATION_CREDENTIALS` for real STT/TTS

---

## 2. Exotel Account Setup

### 2.1 Choose Your Region

| Region | Dashboard URL | API Base URL | Use When |
|--------|--------------|--------------|----------|
| **Singapore** (default) | https://app.exotel.com | `api.exotel.com` | Most use cases outside India |
| **Mumbai (Veeno)** | https://app.in.exotel.com | `api.in.exotel.com` | Indian customers, BFSI, SIP Trunking |

> **For India:** Use the Mumbai instance. It also supports IP–PSTN intermixing (SIP trunks).

### 2.2 Sign Up

1. Go to your region's dashboard URL above
2. Click **Sign Up** → fill in company details
3. Verify your email

### 2.3 Complete KYC (Required for AgentStream)

AgentStream (the WebSocket streaming feature) requires KYC verification:

1. Log in to the dashboard
2. Go to **Settings → KYC**
3. Submit company documents as instructed
4. Wait for confirmation from Exotel's compliance team

> **Note:** KYC and development/testing can happen in parallel — you can build and test locally while KYC is being approved. AgentStream will only work on live calls once KYC is approved.

---

## 3. Get Your Exotel API Credentials

You'll need these for the Active Streams monitoring API and for Basic Auth on your WebSocket.

1. Log in → go to **Settings → API Settings** (or **Developers → API Keys**)
2. Note down:
   - **API Key** — acts as username
   - **API Token** — acts as password
   - **Account SID** — your account identifier

Keep these safe. You'll use them to:
- Secure your WebSocket endpoint (Basic Auth)
- Call the Active Streams API to monitor live calls

```bash
# Example: check active streams
curl -X GET 'https://<API_KEY>:<API_TOKEN>@api.exotel.com/v1/Accounts/<ACCOUNT_SID>/ActiveStreams'
# For Mumbai: @api.in.exotel.com
```

---

## 4. Buy a Phone Number

1. Dashboard → **Phone Numbers → Buy a Number**
2. Select a number in your country
3. Complete purchase

This is the number callers will dial to reach your AI bot.

---

## 5. Expose Your Server Publicly

Exotel needs to reach your server over HTTPS/WSS. During development, use **ngrok**.

### Option A: ngrok (Development)

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000
```

You'll get a URL like:
```
https://abc123.ngrok-free.app
```

Your endpoints:
| Purpose | URL |
|---------|-----|
| WebSocket (Exotel streams audio here) | `wss://abc123.ngrok-free.app/stream` |
| Passthru (Exotel POSTs call metadata here) | `https://abc123.ngrok-free.app/passthru` |
| Health check | `https://abc123.ngrok-free.app/health` |

> **Important:** ngrok free tier generates a new URL each restart. Use a paid plan or deploy to a persistent host for demos.

### Option B: Persistent Deployment

| Platform | Cost | Notes |
|----------|------|-------|
| [Render](https://render.com) | Free tier available | Auto-deploys from GitHub |
| [Railway](https://railway.app) | ~$5/month | Very simple |
| AWS EC2 / GCP VM | ~$10-20/month | Full control, production-grade |

Ensure your deployment has a valid TLS certificate (all of the above provide this automatically). Self-signed certs will be rejected by Exotel.

---

## 6. Build the Call Flow in App Bazaar

This is where you wire Exotel to call your server when someone dials your number.

### Step-by-Step

1. Log in to Exotel Dashboard
2. Go to **App Bazaar** (left sidebar)
3. Click **Create New App**
4. Give it a name, e.g. `"Puch AI Voicebot"`

### 6.1 Add the VoiceBot Applet (Bidirectional Streaming)

This applet connects Exotel to your WebSocket server for full two-way audio.

In the app builder, drag in a **VoiceBot** applet and configure:

| Field | Value | Notes |
|-------|-------|-------|
| **URL** | `wss://abc123.ngrok-free.app/stream?sample-rate=8000` | Your public WSS URL |
| **Sample Rate** | `8000` (default) | Use `16000` for better quality if bandwidth allows |
| **Authentication** | IP Whitelist or Basic Auth | See [Section 10](#10-authentication-options) |
| **Record this?** | Optional ✓ | Enables recording URL in Passthru |
| **Custom Parameters** | Optional | Max 3 params, total ≤ 256 chars |

**URL formats by sample rate:**
```
8000 Hz  (default PSTN quality): wss://your-host/stream?sample-rate=8000
16000 Hz (recommended for AI):   wss://your-host/stream?sample-rate=16000
24000 Hz (HD quality):           wss://your-host/stream?sample-rate=24000
```

> **Recommended:** Use `16000` Hz for best STT accuracy. Exotel defaults to `8000` if omitted.

**What Exotel will send to your WebSocket (sequence of events):**
```
1. connected  → WebSocket handshake done
2. start      → Stream starting, includes call_sid, from, to, media_format
3. media      → Continuous base64-encoded PCM audio chunks (caller's voice)
4. dtmf       → If caller presses a key (optional)
5. mark       → Acknowledgment of your mark events
6. clear      → Caller said "start over" — reset bot context
7. stop       → Call ended
```

**What your server sends back to Exotel:**
```
media  → base64 PCM audio (bot's voice, from TTS)
mark   → logical milestone markers (for sync/debugging)
clear  → flush Exotel's audio buffer (barge-in/interruption)
```

### 6.2 Add the Passthru Applet (Immediately After VoiceBot)

The Passthru applet fires an HTTP GET to your server after the call ends, delivering call metadata.

Drag a **Passthru** applet immediately after the VoiceBot applet:

| Field | Value |
|-------|-------|
| **URL** | `https://abc123.ngrok-free.app/passthru` |
| **Mode** | **Async** (recommended — caller doesn't wait) |

> **Always place Passthru right after VoiceBot.** This is how you capture call duration, recording URL, disconnect reason, and errors.

### 6.3 (Optional) Add Escalation Logic

If you want to route callers to a human after the bot finishes:

```
VoiceBot → Passthru → SwitchCase (check escalate=true) → Connect (to human agent)
                                                         → Hangup
```

Your `/passthru` endpoint can return:
- `200 OK` with `{"escalate": "true"}` → route to human
- `200 OK` without escalate → proceed to next applet (hangup)

### 6.4 Complete Call Flow Diagram

```
Caller dials your Exotel number
           ↓
    [VoiceBot Applet]
    URL: wss://your-host/stream?sample-rate=8000
           ↓  (bidirectional WebSocket — live call)
    Your Puch AI server:
      caller audio (PCM base64) → STT → Gemini LLM → TTS → audio back
           ↓  (WebSocket closes when bot is done)
    [Passthru Applet]
    URL: https://your-host/passthru
    Receives: StreamSID, Duration, RecordingUrl, DisconnectedBy
           ↓
    [Hangup / Connect to Agent]
```

### 6.5 Save the App

Click **Save** or **Publish** in App Bazaar.

---

## 7. Assign the App to Your Phone Number

1. Dashboard → **Phone Numbers**
2. Click on your number
3. Under **Incoming Call**, select the app you just created (`"Puch AI Voicebot"`)
4. Save

Now when someone calls that number, the flow runs.

---

## 8. Make a Test Call

### 8.1 Verify your server is running

```bash
curl https://abc123.ngrok-free.app/health
# Expected: {"status": "ok", "active_sessions": 0}
```

### 8.2 Watch the logs

```bash
# With text logging (default)
python -m src.infrastructure.server

# With JSON logging (production-style)
LOG_FORMAT=json python -m src.infrastructure.server
```

### 8.3 Call the number

Dial your Exotel phone number from any phone. You should see in your server logs:

```
2026-04-03T12:00:00 INFO  Exotel connected event received
2026-04-03T12:00:00 INFO  Call accepted: stream=<sid> caller=+91XXXXXXXXXX called=+91YYYYYYYYYY
2026-04-03T12:00:01 INFO  Audio processing started: stream=<sid>
2026-04-03T12:00:05 INFO  STT result: "Hello, how can you help me?"
2026-04-03T12:00:06 INFO  LLM response streaming started
2026-04-03T12:00:07 INFO  TTS audio sent: 3200 bytes, position=0
...
2026-04-03T12:00:28 INFO  Call ended: stream=<sid>
2026-04-03T12:00:28 INFO  Stream completed: stream=<sid> status=completed duration=28s disconnected_by=bot
```

### 8.4 Local simulation (no real Exotel call needed)

Test your server locally without making a real call:

```bash
# Start server
python -m src.infrastructure.server

# In another terminal, run the simulator
python scripts/local_ws_test.py --chunks 10 --sample-rate 8000
```

This sends a synthetic `connected → start → media → stop` sequence directly to your WebSocket.

---

## 9. Monitor Live Calls

### 9.1 Active Streams API

Check how many calls are currently live:

```bash
# Singapore cluster
curl -X GET 'https://<API_KEY>:<API_TOKEN>@api.exotel.com/v1/Accounts/<ACCOUNT_SID>/ActiveStreams'

# Mumbai cluster
curl -X GET 'https://<API_KEY>:<API_TOKEN>@api.in.exotel.com/v1/Accounts/<ACCOUNT_SID>/ActiveStreams'
```

Response:
```json
{
  "status": "success",
  "active_streams": 3,
  "max_allowed_streams": 100,
  "account_sid": "your_account_sid"
}
```

### 9.2 Your `/health` endpoint

```bash
curl https://your-host/health
# {"status": "ok", "active_sessions": 2}
```

---

## 10. Authentication Options

Exotel supports two ways to secure your WebSocket endpoint.

### Option A: IP Whitelisting (Simplest for PoC)

Exotel will only connect from its own IP ranges. No credentials needed in the URL.

1. Email **hello@exotel.com** to get Exotel's outbound IP ranges
2. Add those IPs to your server's firewall / security group allowlist
3. In VoiceBot Applet → Authentication: select **IP Whitelist**

### Option B: Basic Authentication

Credentials are passed in the WSS URL by you, then transmitted by Exotel as an HTTP `Authorization` header (never exposed in transit).

**In VoiceBot Applet URL, you configure:**
```
wss://<YOUR_API_KEY>:<YOUR_API_TOKEN>@your-host/stream?sample-rate=8000
```

**What Exotel actually sends to your server (in HTTP headers):**
```
Authorization: Basic base64(<YOUR_API_KEY>:<YOUR_API_TOKEN>)
```

**To validate in your server** (add to `server.py`):
```python
from fastapi import WebSocket, HTTPException
import base64

EXPECTED_CREDENTIALS = base64.b64encode(
    f"{API_KEY}:{API_TOKEN}".encode()
).decode()

@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    auth = websocket.headers.get("Authorization", "")
    if not auth.startswith("Basic ") or auth[6:] != EXPECTED_CREDENTIALS:
        await websocket.close(code=4001)
        return
    # ... rest of handler
```

> **For PoC:** IP Whitelisting is simpler. For production: use Basic Auth.

---

## 11. Passthru Applet Reference

Your `/passthru` endpoint receives a `GET` request from Exotel after each call ends.

### What Exotel Sends

```
GET https://your-host/passthru?
  CallSid=56b1234567abcdef89abcdef12345678&
  Direction=inbound&
  From=+918888000000&
  To=+912233344455&
  Stream[StreamSID]=6f048d2e897a0d2d4029560f3f541947&
  Stream[Status]=completed&
  Stream[Duration]=28&
  Stream[RecordingUrl]=https://recordings.exotel.com/...mp3&
  Stream[StreamUrl]=wss://your-host/stream&
  Stream[DisconnectedBy]=bot
```

### Parameter Reference

| Parameter | Values | Description |
|-----------|--------|-------------|
| `Stream[StreamSID]` | string | Unique ID for this streaming session |
| `Stream[Status]` | `completed`, `failed`, `cancelled` | How the stream ended |
| `Stream[Duration]` | integer (seconds) | How long the stream lasted |
| `Stream[DisconnectedBy]` | `user`, `bot`, `NA` | Who closed the connection |
| `Stream[RecordingUrl]` | URL | Recording download link (if recording enabled) |
| `Stream[Error]` | string | Error message on failure |
| `Stream[DetailedStatus]` | `Streaming_call_throttled` | Present when concurrency limit hit |

### Common Scenarios

| Scenario | `Status` | `DisconnectedBy` | `Error` |
|----------|----------|------------------|---------|
| Normal call, bot ended it | `completed` | `bot` | — |
| Caller hung up | `cancelled` | `user` | — |
| Invalid WebSocket URL | `failed` | `NA` | `3009 failed to establish ws conn...` |
| Concurrency limit hit | `failed` | `NA` | — (check `DetailedStatus`) |

### Your server's `/passthru` already handles all of this

The server logs everything and returns `{"status": "ok"}`. To add routing logic (e.g., escalate to human):

```python
@app.get("/passthru")
async def passthru(request: Request) -> JSONResponse:
    params = dict(request.query_params)
    disconnected_by = params.get("Stream[DisconnectedBy]", "NA")
    
    # Example: route to human if user said "agent"
    # (you'd check this against your session state)
    if disconnected_by == "user":
        return JSONResponse({"escalate": "true"})  # → Exotel routes to Connect applet
    
    return JSONResponse({"status": "ok"})
```

---

## 12. Troubleshooting

### Server not receiving any events

- Check your public URL is reachable: `curl https://your-host/health`
- Check ngrok is running and the URL matches what's in VoiceBot Applet
- Check the VoiceBot Applet URL uses `wss://` not `ws://` for HTTPS hosts

### "failed to establish ws conn" in Passthru

- Your server wasn't running when the call came in
- TLS certificate is self-signed or expired (use Let's Encrypt / ngrok / cloud provider)
- Firewall blocking Exotel's IPs — request IP list from hello@exotel.com

### Audio coming in but no response sent back

- Check `GEMINI_API_KEY` is set correctly in `.env`
- If using Google STT/TTS: verify `GOOGLE_APPLICATION_CREDENTIALS` points to a valid JSON key
- Run `python scripts/local_ws_test.py` locally to isolate from Exotel

### Exotel disconnects after 10 seconds

- Your server took too long to respond to the WebSocket handshake
- Make sure `uvicorn` starts quickly (lifespan should be fast — all our adapters are lazy-init)
- Check server logs for any blocking startup operations

### "Streaming_call_throttled" in Passthru

- You've hit the concurrent stream limit on your Exotel plan
- Check current usage: `curl .../ActiveStreams`
- Contact Exotel to increase your limit

### Calls connect but bot sounds garbled

- Sample rate mismatch: ensure VoiceBot Applet URL has `?sample-rate=8000` and `SAMPLE_RATE=8000` in `.env`
- Chunk size issue: our TTS outputs 3200-byte chunks (100ms), which is within Exotel's 3.2k–100k range ✓

---

## Quick Reference Card

```
Your Exotel Dashboard:   https://app.exotel.com  (or app.in.exotel.com for India)
AgentStream Docs:        https://docs.exotel.com/exotel-agentstream/agentstream
Support:                 hello@exotel.com  |  WhatsApp: 08088919888

VoiceBot Applet URL:     wss://<YOUR_HOST>/stream?sample-rate=8000
Passthru Applet URL:     https://<YOUR_HOST>/passthru

Audio format:            PCM 16-bit little-endian, mono, base64-encoded
Chunk size:              3200 bytes (100ms) — multiples of 320 bytes
Timeout:                 10 seconds (server must respond to handshake)
Max concurrent calls:    depends on your Exotel plan
Max call duration:       60 minutes per session
Max custom params:       3 (total length ≤ 256 chars)
```
