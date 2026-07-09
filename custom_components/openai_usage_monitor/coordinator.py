"""Coordinator and normalization for OpenAI usage data."""

from __future__ import annotations

import calendar
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import OpenAIAdminClient, OpenAIAuthError, OpenAIUsageError
from .const import (
    CONF_ADMIN_API_KEY,
    CONF_MONTHLY_BUDGET,
    CONF_POLL_INTERVAL_MINUTES,
    CONF_TOP_N_MODELS,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DEFAULT_TOP_N_MODELS,
    DOMAIN,
    USAGE_ENDPOINTS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class UsageAggregate:
    """Aggregated counters."""

    cost: float = 0.0
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    currency: str = "USD"
    model_breakdown: dict[str, dict[str, Any]] = field(default_factory=dict)
    line_items: dict[str, dict[str, Any]] = field(default_factory=dict)
    categories: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_updated: str | None = None

    def add_tokens(self, result: dict[str, Any], category: str) -> None:
        input_tokens = int(result.get("input_tokens") or 0)
        output_tokens = int(result.get("output_tokens") or 0)
        total_tokens = int(result.get("total_tokens") or input_tokens + output_tokens)
        requests = int(
            result.get("num_model_requests")
            or result.get("num_requests")
            or result.get("num_sessions")
            or 0
        )
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += total_tokens
        self.requests += requests
        bucket = self.categories.setdefault(
            category,
            {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        bucket["requests"] += requests
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
        model = result.get("model")
        if model:
            model_bucket = self.model_breakdown.setdefault(
                model,
                {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost": 0.0},
            )
            model_bucket["requests"] += requests
            model_bucket["input_tokens"] += input_tokens
            model_bucket["output_tokens"] += output_tokens
            model_bucket["total_tokens"] += total_tokens

    def add_cost(self, result: dict[str, Any]) -> None:
        amount = result.get("amount") or {}
        value = float(amount.get("value") or 0)
        self.cost += value
        if amount.get("currency"):
            self.currency = str(amount["currency"]).upper()
        line_item = result.get("line_item")
        if line_item:
            item = self.line_items.setdefault(
                line_item, {"cost": 0.0, "quantity": 0, "currency": self.currency}
            )
            item["cost"] += value
            item["quantity"] += result.get("quantity") or 0


@dataclass(slots=True)
class OpenAIUsageData:
    """Normalized data exposed to entities."""

    today: UsageAggregate
    month: UsageAggregate
    api_keys: dict[str, UsageAggregate]
    projects: dict[str, UsageAggregate]
    models: dict[str, UsageAggregate]
    unavailable_categories: dict[str, str]
    unknown_api_keys: list[str]
    budget: dict[str, Any]
    last_updated: str


class OpenAIUsageCoordinator(DataUpdateCoordinator[OpenAIUsageData]):
    """Fetch OpenAI organization usage periodically."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        minutes = int(
            entry.options.get(
                CONF_POLL_INTERVAL_MINUTES,
                entry.data.get(CONF_POLL_INTERVAL_MINUTES, DEFAULT_POLL_INTERVAL_MINUTES),
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
            config_entry=entry,
        )
        self.client = OpenAIAdminClient(
            async_get_clientsession(hass), entry.data[CONF_ADMIN_API_KEY]
        )

    async def _async_update_data(self) -> OpenAIUsageData:
        now = dt_util.now()
        today_start = _as_utc_ts(datetime.combine(now.date(), time.min, now.tzinfo))
        month_start = _as_utc_ts(datetime(now.year, now.month, 1, tzinfo=now.tzinfo))
        tomorrow_start = _as_utc_ts(
            datetime.combine(now.date() + timedelta(days=1), time.min, now.tzinfo)
        )
        try:
            return await self._collect(month_start, today_start, tomorrow_start, now.date())
        except OpenAIAuthError as err:
            raise UpdateFailed("OpenAI Admin API key is invalid or unauthorized") from err
        except OpenAIUsageError as err:
            raise UpdateFailed(str(err)) from err

    async def _collect(
        self, month_start: int, today_start: int, tomorrow_start: int, today: date
    ) -> OpenAIUsageData:
        month = UsageAggregate()
        today_agg = UsageAggregate()
        by_key: dict[str, UsageAggregate] = defaultdict(UsageAggregate)
        by_project: dict[str, UsageAggregate] = defaultdict(UsageAggregate)
        by_model: dict[str, UsageAggregate] = defaultdict(UsageAggregate)
        unavailable: dict[str, str] = {}

        for category in USAGE_ENDPOINTS:
            try:
                buckets = await self.client.fetch_usage(
                    category,
                    start_time=month_start,
                    end_time=tomorrow_start,
                    group_by=["api_key_id", "project_id", "model"],
                    limit=31,
                )
            except OpenAIUsageError as err:
                unavailable[category] = str(err)
                continue
            _add_usage_buckets(buckets, category, month, today_agg, by_key, by_project, by_model, today_start)

        try:
            cost_buckets = await self.client.fetch_costs(
                start_time=month_start,
                end_time=tomorrow_start,
                group_by=None,
                limit=31,
            )
            _add_cost_buckets(cost_buckets, month, today_agg, None, None, today_start)
        except OpenAIUsageError as err:
            unavailable["costs"] = str(err)

        for group_by in (["api_key_id"], ["project_id"]):
            try:
                cost_buckets = await self.client.fetch_costs(
                    start_time=month_start,
                    end_time=tomorrow_start,
                    group_by=group_by,
                    limit=31,
                )
            except OpenAIUsageError as err:
                unavailable["costs"] = str(err)
                continue
            _add_cost_buckets(cost_buckets, None, None, by_key, by_project, today_start)

        try:
            line_item_buckets = await self.client.fetch_costs(
                start_time=month_start,
                end_time=tomorrow_start,
                group_by=["line_item"],
                limit=31,
            )
            _add_line_item_buckets(line_item_buckets, month, today_agg, today_start)
        except OpenAIUsageError as err:
            unavailable["costs"] = str(err)

        last_updated = dt_util.utcnow().isoformat()
        for agg in [month, today_agg, *by_key.values(), *by_project.values(), *by_model.values()]:
            agg.last_updated = last_updated

        top_n = int(self.config_entry.options.get(CONF_TOP_N_MODELS, DEFAULT_TOP_N_MODELS))
        model_map = dict(
            sorted(by_model.items(), key=lambda item: item[1].total_tokens, reverse=True)[:top_n]
        )
        budget = _budget_attrs(
            self.config_entry.options.get(
                CONF_MONTHLY_BUDGET, self.config_entry.data.get(CONF_MONTHLY_BUDGET)
            ),
            month.cost,
            today,
        )
        return OpenAIUsageData(
            today=today_agg,
            month=month,
            api_keys=dict(by_key),
            projects=dict(by_project),
            models=model_map,
            unavailable_categories=unavailable,
            unknown_api_keys=sorted(k for k in by_key if k),
            budget=budget,
            last_updated=last_updated,
        )


def _add_usage_buckets(
    buckets: list[dict[str, Any]],
    category: str,
    month: UsageAggregate,
    today: UsageAggregate,
    by_key: dict[str, UsageAggregate],
    by_project: dict[str, UsageAggregate],
    by_model: dict[str, UsageAggregate],
    today_start: int,
) -> None:
    for bucket in buckets:
        is_today = int(bucket.get("start_time") or 0) >= today_start
        for result in bucket.get("results") or []:
            month.add_tokens(result, category)
            if is_today:
                today.add_tokens(result, category)
            if result.get("api_key_id"):
                by_key[str(result["api_key_id"])].add_tokens(result, category)
            if result.get("project_id"):
                by_project[str(result["project_id"])].add_tokens(result, category)
            if result.get("model"):
                by_model[str(result["model"])].add_tokens(result, category)


def _add_cost_buckets(
    buckets: list[dict[str, Any]],
    month: UsageAggregate | None,
    today: UsageAggregate | None,
    by_key: dict[str, UsageAggregate] | None,
    by_project: dict[str, UsageAggregate] | None,
    today_start: int,
) -> None:
    for bucket in buckets:
        is_today = int(bucket.get("start_time") or 0) >= today_start
        for result in bucket.get("results") or []:
            if month:
                month.add_cost(result)
            if today and is_today:
                today.add_cost(result)
            if by_key is not None and result.get("api_key_id"):
                by_key[str(result["api_key_id"])].add_cost(result)
            if by_project is not None and result.get("project_id"):
                by_project[str(result["project_id"])].add_cost(result)


def _add_line_item_buckets(
    buckets: list[dict[str, Any]],
    month: UsageAggregate,
    today: UsageAggregate,
    today_start: int,
) -> None:
    for bucket in buckets:
        is_today = int(bucket.get("start_time") or 0) >= today_start
        for result in bucket.get("results") or []:
            _add_line_item(month, result)
            if is_today:
                _add_line_item(today, result)


def _add_line_item(aggregate: UsageAggregate, result: dict[str, Any]) -> None:
    line_item = result.get("line_item")
    if not line_item:
        return
    amount = result.get("amount") or {}
    item = aggregate.line_items.setdefault(
        line_item,
        {"cost": 0.0, "quantity": 0, "currency": aggregate.currency},
    )
    item["cost"] += float(amount.get("value") or 0)
    item["quantity"] += result.get("quantity") or 0
    if amount.get("currency"):
        item["currency"] = str(amount["currency"]).upper()


def _budget_attrs(configured_budget: Any, month_cost: float, today: date) -> dict[str, Any]:
    budget = float(configured_budget or 0)
    days_elapsed = today.day
    _, days_in_month = calendar.monthrange(today.year, today.month)
    average_daily = month_cost / max(days_elapsed, 1)
    projected = average_daily * days_in_month
    remaining = budget - month_cost if budget else None
    percent = (month_cost / budget * 100) if budget else None
    return {
        "configured_budget": budget or None,
        "month_to_date_cost": round(month_cost, 6),
        "estimated_remaining": round(remaining, 6) if remaining is not None else None,
        "percent_used": round(percent, 2) if percent is not None else None,
        "days_elapsed": days_elapsed,
        "projected_month_end_cost": round(projected, 6),
        "average_daily_cost": round(average_daily, 6),
    }


def _as_utc_ts(value: datetime) -> int:
    return int(value.astimezone(dt_util.UTC).timestamp())
