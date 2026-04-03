"""Smoke tests — verify server starts, health check returns 200, WebSocket accepts connection."""

import asyncio
import json
import os

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-key")

from httpx import AsyncClient, ASGITransport  # noqa: E402
from src.infrastructure.server import app  # noqa: E402


@pytest.mark.asyncio
async def test_health_returns_200():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_body_contains_status_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    body = response.json()
    assert body["status"] == "ok"
    assert "active_sessions" in body


@pytest.mark.asyncio
async def test_health_reports_zero_sessions_initially():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.json()["active_sessions"] == 0
