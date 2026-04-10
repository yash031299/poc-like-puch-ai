# Distributed Tracing with OpenTelemetry & Jaeger

This guide explains how to use OpenTelemetry and Jaeger for distributed tracing in the Exotel AgentStream voice AI PoC.

## Overview

Distributed tracing provides end-to-end visibility into call processing, from WebSocket connection to response delivery. Each call creates a trace containing multiple spans (operations), allowing you to:

- **Debug performance issues** — identify bottlenecks in STT, LLM, TTS pipelines
- **Correlate logs and traces** — link all logs for a single call via trace ID
- **Monitor latency** — measure time spent in each operation
- **Detect errors** — see exactly where in the pipeline failures occur
- **Understand concurrency** — see interleaved operations across distributed systems

## Architecture

```
┌─────────────────┐
│ Exotel WebSocket│
│   (incoming)    │
└────────┬────────┘
         │
         v
┌─────────────────────────────────┐
│ ExotelWebSocketHandler          │
│ (extract trace context)         │
└────────┬────────────────────────┘
         │
    ┌────┴────────────────────────────────────┐
    v                                          v
┌──────────────────┐          ┌──────────────────────┐
│ AcceptCallUseCase│          │ ProcessAudioUseCase  │
│ (create session) │          │ (transcribe + LLM)   │
└──────────┬───────┘          └──────────┬───────────┘
           │                             │
       ┌───┴────────────────────────────┴──────┐
       v                                       v
   ┌─────────────────┐           ┌──────────────────────┐
   │ GenerateResponse│           │ GoogleSTTAdapter     │
   │ (call LLM)      │           │ (real-time audio)    │
   └────────┬────────┘           └──────────┬───────────┘
            │                                │
            v                                v
        ┌─────────────────┐      ┌───────────────────┐
        │ StreamResponse  │      │ GoogleTTSAdapter  │
        │ (send to caller)│      │ (synthesize voice)│
        └─────────────────┘      └───────────────────┘
```

Each box above is a span. All spans for one call share the same **trace ID** (e.g., the stream_sid).

## Setup

### 1. Environment Variables

Configure tracing in your `.env` or deploy settings:

```bash
# Jaeger agent connection (default: localhost:6831)
JAEGER_AGENT_HOST=localhost
JAEGER_AGENT_PORT=6831

# Service name (appears in Jaeger UI)
JAEGER_SERVICE_NAME=puch-ai-voice-server

# Sampling rate: 0.0 = no traces, 1.0 = all traces, 0.01 = 1% (default)
OTEL_SAMPLE_RATE=0.01

# Logging format (json recommended for production)
LOG_FORMAT=json
```

### 2. Start Jaeger

Using Docker Compose:

```bash
cd ops
docker-compose up jaeger
```

Jaeger UI will be available at: **http://localhost:16686**

Using standalone Docker:

```bash
docker run --rm \
  -p 16686:16686 \
  -p 6831:6831/udp \
  jaegertracing/all-in-one
```

### 3. Run the Application

```bash
# Development mode with tracing
DEV_MODE=true python3 -m src.infrastructure.server

# Or with real providers
python3 -m src.infrastructure.server
```

Traces will be automatically exported to Jaeger every few seconds.

## Viewing Traces in Jaeger UI

### 1. Open Jaeger Dashboard

Go to: **http://localhost:16686**

### 2. Select Service

- **Service dropdown**: Select "puch-ai-voice-server" (or your JAEGER_SERVICE_NAME)

### 3. View Traces

The UI shows:
- **Timeline** of all spans in the trace
- **Operation** name (use case or adapter)
- **Span duration** (in milliseconds)
- **Attributes** (caller_id, stream_sid, error details, etc.)
- **Logs** (associated log lines)

### 4. Trace Example

A typical voice call trace:

```
Trace ID: stream-12345-xyz
├── ExotelWebSocketHandler.handle (500ms total)
│   ├── AcceptCallUseCase.execute (10ms)
│   │   └── SessionRepository.save (2ms)
│   ├── ProcessAudioUseCase.execute (150ms)
│   │   ├── GoogleSTTAdapter.transcribe (80ms)
│   │   ├── GenerateResponseUseCase.execute (50ms)
│   │   │   └── GeminiLLMAdapter.generate (45ms)
│   │   └── StreamResponseUseCase.execute (20ms)
│   │       └── GoogleTTSAdapter.synthesize (15ms)
│   └── EndCallUseCase.execute (5ms)
```

## Key Concepts

### Trace ID

The **trace ID** uniquely identifies a single call from start to finish. In our implementation, the trace ID is typically the `stream_sid` from Exotel.

- **Exotel provides**: `stream_sid = "stream-abc123xyz"`
- **We use it as**: `trace_id = "stream-abc123xyz"`
- **Appears in**: Logs, trace headers, Jaeger UI

### Span

A **span** represents a single operation (e.g., transcribe audio, generate response).

Spans have:
- **Name**: "GoogleSTTAdapter.transcribe"
- **Start time**: When operation began
- **Duration**: How long it took
- **Attributes**: Key-value pairs (provider="google", language="en-US")
- **Status**: success, error, or unknown

### W3C Trace Context

We follow the **W3C Trace Context** standard for inter-service propagation.

Header format:
```
traceparent: 00-<trace_id>-<span_id>-<flags>
```

Example:
```
traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
```

## Code Examples

### Instrumenting a Use Case

Use cases are automatically traced via the `@traced_use_case` decorator:

```python
from src.infrastructure.tracing import traced_use_case

class MyUseCase:
    @traced_use_case
    async def execute(self, stream_id: str, data: str) -> Result:
        # Operation automatically wrapped in span
        # stream_id is automatically added as span attribute
        result = await self.do_work(data)
        return result
```

The decorator automatically:
- Creates a span named `MyUseCase.execute`
- Extracts `stream_id` from arguments and sets as span attribute
- Captures exceptions and records them in the span
- Updates trace ID context for logging

### Instrumenting an Adapter Call

Adapter calls (external services) are traced with `@traced_adapter_call`:

```python
from src.infrastructure.tracing import traced_adapter_call

class GoogleSTTAdapter:
    @traced_adapter_call("google.stt", provider="google", service="speech-to-text")
    async def transcribe(self, audio_bytes: bytes) -> str:
        # Automatically wrapped in span
        response = await self.client.recognize(audio_bytes)
        return response.transcript
```

Attributes are automatically added to the span.

### Setting Trace Context Manually

If you need to propagate trace IDs manually:

```python
from src.infrastructure.tracing import set_trace_id, get_trace_id

async def handle_call(stream_sid: str):
    # Set the trace ID for this call
    set_trace_id(stream_sid)
    
    # All subsequent operations share this trace ID
    result = await process_audio(stream_sid)
    
    # Retrieve trace ID if needed
    current_trace = get_trace_id()
```

### Extracting Trace Context from Headers

When receiving HTTP/WebSocket messages with trace headers:

```python
from src.infrastructure.tracing import extract_trace_context_from_headers, set_trace_id

async def handle_websocket(websocket, headers):
    # Extract W3C Trace Context
    trace_id = extract_trace_context_from_headers(headers)
    
    if trace_id:
        set_trace_id(trace_id)
        # All operations are part of the same distributed trace
```

### Injecting Trace Context into Outgoing Requests

When making outbound requests:

```python
from src.infrastructure.tracing import inject_trace_context_to_headers

async def call_external_api(data):
    headers = {
        "Content-Type": "application/json"
    }
    
    # Add trace context headers
    headers = inject_trace_context_to_headers(headers)
    
    # Now external service can correlate logs with our trace
    response = await client.post(url, headers=headers, json=data)
```

## Correlation with Logs

All log records automatically include trace ID and span ID:

```json
{
  "timestamp": "2024-04-10T12:34:56.789Z",
  "level": "INFO",
  "logger": "src.infrastructure.exotel_websocket_handler",
  "message": "Exotel connection established",
  "trace_id": "stream-abc123xyz",
  "span_id": "0000000000000001",
  "stream_id": "stream-abc123xyz"
}
```

**To view all logs for a trace in Jaeger UI:**

1. Open a trace in Jaeger
2. Scroll to any span
3. Click "Logs" tab
4. All logs with matching trace_id appear

**To search logs by trace ID:**

If using a centralized log aggregation system (ELK, CloudWatch, etc.):

```
trace_id:stream-abc123xyz
```

## Performance Impact

### Sampling

By default, traces are sampled at **1%** (`OTEL_SAMPLE_RATE=0.01`). This means:

- **1 out of 100 calls** are fully traced (rest are not sampled)
- **Overhead < 5%** (negligible)
- **Jaeger storage**: ~1MB per 10,000 calls

### Adjustment

For **higher visibility** (e.g., staging or debugging):

```bash
OTEL_SAMPLE_RATE=0.10  # 10% of calls
```

For **production** with high throughput:

```bash
OTEL_SAMPLE_RATE=0.001  # 0.1% of calls
```

For **development**:

```bash
OTEL_SAMPLE_RATE=1.0  # 100% of calls
```

## Troubleshooting

### Traces Not Appearing in Jaeger

1. **Check Jaeger is running**:
   ```bash
   curl http://localhost:16686/api/services
   # Should return list of services
   ```

2. **Check environment variables**:
   ```bash
   echo $JAEGER_AGENT_HOST
   echo $JAEGER_AGENT_PORT
   ```

3. **Check sampling rate** isn't too low:
   ```bash
   OTEL_SAMPLE_RATE=1.0  # Set to 100% for testing
   ```

4. **Check logs for errors**:
   ```bash
   LOG_LEVEL=DEBUG python3 -m src.infrastructure.server
   # Look for "OpenTelemetry initialized" message
   ```

### Traces Incomplete (Missing Spans)

1. Ensure all use cases use `@traced_use_case` decorator
2. Ensure adapters use `@traced_adapter_call` decorator
3. Check `set_trace_id()` is called early in the request pipeline

### Trace ID Not in Logs

1. Ensure logging is configured with `configure_logging()` at startup
2. Check `LOG_FORMAT=json` for structured output
3. Verify `TraceContextInjectingFilter` is active

## Advanced: Custom Spans

Create custom spans for complex operations:

```python
from src.infrastructure.tracing import get_tracer

tracer = get_tracer(__name__)

async def complex_operation():
    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("user_id", user_id)
        span.set_attribute("batch_size", 100)
        
        try:
            result = await do_work()
            span.set_attribute("status", "success")
            return result
        except Exception as e:
            span.set_attribute("status", "error")
            span.set_attribute("error.type", type(e).__name__)
            raise
```

## Deployment Guide

### Docker Compose (Production)

The `ops/docker-compose.yml` already includes Jaeger configuration:

```yaml
services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # UI
      - "6831:6831/udp"  # Agent
  
  api-1:
    environment:
      JAEGER_AGENT_HOST: jaeger
      JAEGER_AGENT_PORT: 6831
```

### Kubernetes

Use the included Prometheus + Jaeger setup in `ops/kubernetes-deployment.yaml`.

### Standalone Jaeger Instance

For production deployments, use a dedicated Jaeger deployment (not all-in-one):

```yaml
# jaeger-collector.yaml
services:
  jaeger-collector:
    image: jaegertracing/jaeger-collector:latest
    environment:
      COLLECTOR_ZIPKIN_HTTP_PORT: 9411
    ports:
      - "14268:14268"  # Thrift
  
  jaeger-query:
    image: jaegertracing/jaeger-query:latest
    ports:
      - "16686:16686"  # UI
    depends_on:
      - jaeger-storage
```

## Testing

### Unit Tests

```bash
pytest tests/unit/infrastructure/test_tracing.py -v
```

### Integration Tests (with Jaeger)

```bash
# Start Jaeger first
docker-compose up jaeger &

# Run integration tests
pytest tests/integration/test_jaeger_integration.py -v

# Stop Jaeger
docker-compose down
```

### Manual Testing

1. Start application with `OTEL_SAMPLE_RATE=1.0`
2. Make a test call via `scripts/sim_exotel.py`
3. Go to http://localhost:16686
4. Find "puch-ai-voice-server" service
5. See the complete trace with all spans

## References

- **OpenTelemetry Python**: https://opentelemetry.io/docs/instrumentation/python/
- **Jaeger Documentation**: https://www.jaegertracing.io/docs/
- **W3C Trace Context**: https://w3c.github.io/trace-context/
- **OpenTelemetry Best Practices**: https://opentelemetry.io/docs/concepts/observability-primer/

## Support

For issues with tracing:

1. Check logs: `LOG_LEVEL=DEBUG`
2. Enable 100% sampling: `OTEL_SAMPLE_RATE=1.0`
3. Verify Jaeger connectivity: `curl http://localhost:16686/api/services`
4. Run tests: `pytest tests/unit/infrastructure/test_tracing.py`
