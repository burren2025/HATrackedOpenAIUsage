"""Async client for the official OpenAI Admin Usage and Costs APIs."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession

from .const import API_BASE_URL, COSTS_ENDPOINT, USAGE_ENDPOINTS

_LOGGER = logging.getLogger(__name__)


class OpenAIUsageError(Exception):
    """Base API error."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class OpenAIAuthError(OpenAIUsageError):
    """Raised when the API key is invalid or lacks access."""


class OpenAIRateLimitError(OpenAIUsageError):
    """Raised when OpenAI rate limits the request."""


class OpenAIUnavailableError(OpenAIUsageError):
    """Raised for temporary transport/server failures."""


@dataclass(slots=True)
class OpenAIAdminClient:
    """Small aiohttp wrapper around OpenAI Admin usage endpoints."""

    session: ClientSession
    admin_api_key: str
    base_url: str = API_BASE_URL

    async def validate_key(self) -> None:
        """Validate credentials with the least expensive required endpoint."""
        end_time = int(time.time())
        start_time = end_time - 24 * 60 * 60
        await self.fetch_costs(start_time=start_time, end_time=end_time, limit=1)

    async def fetch_usage(
        self,
        category: str,
        *,
        start_time: int,
        end_time: int,
        group_by: list[str] | None = None,
        limit: int = 31,
    ) -> list[dict[str, Any]]:
        """Fetch all pages for one usage category."""
        endpoint = USAGE_ENDPOINTS[category]
        params: dict[str, Any] = {
            "start_time": start_time,
            "end_time": end_time,
            "bucket_width": "1d",
            "limit": limit,
        }
        if group_by:
            params["group_by"] = group_by
        return await self._fetch_paginated(endpoint, params)

    async def fetch_costs(
        self,
        *,
        start_time: int,
        end_time: int,
        group_by: list[str] | None = None,
        limit: int = 31,
    ) -> list[dict[str, Any]]:
        """Fetch all pages from the costs endpoint."""
        params: dict[str, Any] = {
            "start_time": start_time,
            "end_time": end_time,
            "bucket_width": "1d",
            "limit": limit,
        }
        if group_by:
            params["group_by"] = group_by
        return await self._fetch_paginated(COSTS_ENDPOINT, params)

    async def fetch_admin_api_keys(self) -> list[dict[str, Any]]:
        """Fetch organization and project API key records visible to the Admin key."""
        return await self._fetch_list_paginated(
            "/organization/admin_api_keys", {"limit": 100, "order": "desc"}
        )

    async def fetch_projects(self) -> list[dict[str, Any]]:
        """Fetch organization project records, including archived projects."""
        return await self._fetch_list_paginated(
            "/organization/projects", {"limit": 100, "include_archived": True}
        )

    async def fetch_project_api_keys(self, project_id: str) -> list[dict[str, Any]]:
        """Fetch API key records for one project."""
        return await self._fetch_list_paginated(
            f"/organization/projects/{project_id}/api_keys", {"limit": 100}
        )

    async def _fetch_paginated(
        self, endpoint: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        buckets: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            request_params = dict(params)
            if page:
                request_params["page"] = page
            payload = await self._request_json(endpoint, request_params)
            buckets.extend(payload.get("data") or [])
            page = payload.get("next_page") if payload.get("has_more") else None
            if not page:
                return buckets

    async def _fetch_list_paginated(
        self, endpoint: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            request_params = dict(params)
            if after:
                request_params["after"] = after
            payload = await self._request_json(endpoint, request_params)
            records.extend(payload.get("data") or [])
            after = payload.get("last_id") if payload.get("has_more") else None
            if not after:
                return records

    async def _request_json(
        self, endpoint: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.admin_api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(3):
            try:
                async with self.session.get(
                    url, headers=headers, params=params, timeout=30
                ) as response:
                    return await self._handle_response(response)
            except OpenAIRateLimitError:
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)
            except (TimeoutError, ClientError) as err:
                if attempt == 2:
                    raise OpenAIUnavailableError("OpenAI API request failed") from err
                await asyncio.sleep(2**attempt)
        raise OpenAIUnavailableError("OpenAI API request failed")

    async def _handle_response(self, response: ClientResponse) -> dict[str, Any]:
        if response.status in (401, 403):
            detail = _redact_message(await response.text())
            _LOGGER.warning(
                "OpenAI Admin API authentication failed with HTTP %s: %s",
                response.status,
                detail,
            )
            raise OpenAIAuthError(
                f"OpenAI Admin API key is invalid or unauthorized: {detail}",
                response.status,
            )
        if response.status == 429:
            raise OpenAIRateLimitError("OpenAI API rate limit exceeded", response.status)
        if response.status >= 500:
            raise OpenAIUnavailableError(
                "OpenAI API is temporarily unavailable", response.status
            )
        if response.status >= 400:
            detail = _redact_message(await response.text())
            if _is_invalid_group_by(detail):
                _LOGGER.debug(
                    "OpenAI Admin API does not support requested grouping: %s", detail
                )
            else:
                _LOGGER.warning(
                    "OpenAI Admin API returned HTTP %s: %s", response.status, detail
                )
            raise OpenAIUsageError(
                f"OpenAI Admin API returned HTTP {response.status}: {detail}",
                response.status,
            )
        return await response.json()


def redact_secret(value: str | None) -> str | None:
    """Return a stable redacted representation of a secret."""
    if not value:
        return value
    return f"{value[:4]}...redacted...{value[-4:]}" if len(value) >= 12 else "redacted"


def _redact_message(value: str) -> str:
    """Redact obvious bearer/API key material from an API error message."""
    if not value:
        return "No response body"
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        message = value
    else:
        error = parsed.get("error") if isinstance(parsed, dict) else None
        message = error.get("message", value) if isinstance(error, dict) else value
    return message.replace("Bearer ", "Bearer redacted-")


def _is_invalid_group_by(message: str) -> bool:
    return "invalid group_by value" in message.lower()
