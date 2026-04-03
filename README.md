# PoC Like Puch AI

AI-powered phone conversation system using Exotel AgentStream.

## Architecture

**Hexagonal Architecture (Ports & Adapters)**
- **Domain Layer:** Pure Python business logic (zero external dependencies)
- **Application Layer:** Use cases and orchestration
- **Infrastructure Layer:** Adapters for external services (Exotel, STT, LLM, TTS)

## Design Principles

- **SOLID Principles:** Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion
- **DRY:** Don't Repeat Yourself
- **YAGNI:** You Aren't Gonna Need It
- **KISS:** Keep It Simple, Stupid

## Development Approach

**Test-Driven Development (TDD)**
1. Write failing test (RED)
2. Write minimal code to pass (GREEN)
3. Refactor for quality (REFACTOR)
4. Repeat

## Project Structure

```
poc-like-puch-ai/
├── src/
│   ├── domain/              # Pure Python, zero dependencies
│   │   ├── entities/
│   │   ├── value_objects/
│   │   └── aggregates/
│   ├── use_cases/           # Application business rules
│   ├── ports/               # Interface definitions
│   │   ├── inbound/
│   │   └── outbound/
│   ├── adapters/            # Infrastructure implementations
│   │   ├── primary/
│   │   └── secondary/
│   └── infrastructure/      # Framework-specific code
├── tests/
│   ├── unit/                # Domain & use case tests
│   ├── integration/         # Adapter integration tests
│   └── e2e/                 # End-to-end tests
├── features/                # Gherkin feature files (BDD specs)
└── docs/                    # Documentation
```

## Setup

### Prerequisites
- Python 3.8+
- Virtual environment

### Installation

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate  # On Windows

# Install development dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov

# Run specific test file
pytest tests/unit/domain/test_stream_identifier.py

# Run with verbose output
pytest -v
```

### Code Quality

```bash
# Format code
black src/ tests/

# Type check
mypy src/

# Lint
ruff check src/ tests/

# All quality checks
black src/ tests/ && mypy src/ && ruff check src/ tests/
```

## Features

- ✅ Accept incoming calls via Exotel AgentStream (WebSocket)
- ✅ Convert caller's voice to text (STT)
- ✅ Generate intelligent responses using LLM (Google Gemini)
- ✅ Convert responses back to speech (TTS)
- ✅ Stream audio back to caller with low latency

## Current Status

**Phase 1: Domain & Use Cases** (In Progress)
- [ ] UC-001: Accept Incoming Call
- [ ] UC-002: Process Caller Audio
- [ ] UC-003: Generate AI Response
- [ ] UC-004: Stream Response to Caller
- [ ] UC-005: Handle Call Termination
- [ ] UC-006: Manage Call Session

## References

- [Exotel AgentStream Documentation](https://docs.exotel.com/exotel-agentstream/agentstream)
- [Clean Architecture by Uncle Bob](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Test Driven Development by Kent Beck](https://www.amazon.com/Test-Driven-Development-Kent-Beck/dp/0321146530)

## License

MIT
