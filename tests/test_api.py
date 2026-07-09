"""Tests for the OpenAI Admin API client."""

from __future__ import annotations

import pytest

from custom_components.openai_usage_monitor.api import (
    OpenAIAdminClient,
    OpenAIAuthError,
    OpenAIRateLimitError,
    OpenAIUsageError,
)


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, text: str = "") -> None:
        self.status = status
        self._payload = payload or {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return self._text


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls = []

    def get(self, url, headers, params, timeout):
        self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_fetch_costs_handles_pagination():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "data": [{"start_time": 1, "results": []}],
                    "has_more": True,
                    "next_page": "next",
                },
            ),
            FakeResponse(
                200,
                {
                    "data": [{"start_time": 2, "results": []}],
                    "has_more": False,
                    "next_page": None,
                },
            ),
        ]
    )
    client = OpenAIAdminClient(session, "admin-key")

    buckets = await client.fetch_costs(start_time=1, end_time=3)

    assert [bucket["start_time"] for bucket in buckets] == [1, 2]
    assert session.calls[1]["params"]["page"] == "next"
    assert session.calls[0]["headers"]["Authorization"] == "Bearer admin-key"


@pytest.mark.asyncio
async def test_invalid_key_maps_to_auth_error():
    client = OpenAIAdminClient(FakeSession([FakeResponse(401)]), "admin-key")

    with pytest.raises(OpenAIAuthError):
        await client.fetch_costs(start_time=1, end_time=2)


@pytest.mark.asyncio
async def test_rate_limit_maps_to_rate_limit_error():
    client = OpenAIAdminClient(
        FakeSession([FakeResponse(429), FakeResponse(429), FakeResponse(429)]), "admin-key"
    )

    with pytest.raises(OpenAIRateLimitError):
        await client.fetch_costs(start_time=1, end_time=2)


@pytest.mark.asyncio
async def test_api_error_does_not_include_secret():
    client = OpenAIAdminClient(FakeSession([FakeResponse(400, text="bad request")]), "secret")

    with pytest.raises(OpenAIUsageError) as err:
        await client.fetch_usage("completions", start_time=1, end_time=2)

    assert "secret" not in str(err.value)
