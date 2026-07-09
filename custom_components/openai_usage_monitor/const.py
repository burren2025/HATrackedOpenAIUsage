"""Constants for OpenAI Usage Monitor."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "openai_usage_monitor"

CONF_ADMIN_API_KEY = "admin_api_key"
CONF_ORG_NAME = "organization_name"
CONF_MONTHLY_BUDGET = "monthly_budget"
CONF_DAILY_SPEND_WARNING = "daily_spend_warning"
CONF_REMAINING_CREDIT_WARNING = "remaining_credit_warning"
CONF_POLL_INTERVAL_MINUTES = "poll_interval_minutes"
CONF_API_KEY_ALIASES = "api_key_aliases"
CONF_PROJECT_ALIASES = "project_aliases"
CONF_TOP_N_MODELS = "top_n_models"

DEFAULT_ORG_NAME = "OpenAI"
DEFAULT_POLL_INTERVAL_MINUTES = 60
MIN_POLL_INTERVAL_MINUTES = 30
DEFAULT_TOP_N_MODELS = 5

DEFAULT_SCAN_INTERVAL = timedelta(minutes=DEFAULT_POLL_INTERVAL_MINUTES)

API_BASE_URL = "https://api.openai.com/v1"

USAGE_ENDPOINTS: dict[str, str] = {
    "audio_speeches": "/organization/usage/audio_speeches",
    "audio_transcriptions": "/organization/usage/audio_transcriptions",
    "code_interpreter_sessions": "/organization/usage/code_interpreter_sessions",
    "completions": "/organization/usage/completions",
    "embeddings": "/organization/usage/embeddings",
    "images": "/organization/usage/images",
    "moderations": "/organization/usage/moderations",
    "vector_stores": "/organization/usage/vector_stores",
    "file_search_calls": "/organization/usage/file_search_calls",
    "web_search_calls": "/organization/usage/web_search_calls",
}

COSTS_ENDPOINT = "/organization/costs"

ATTR_CONFIGURED_BUDGET = "configured_budget"
ATTR_MONTH_TO_DATE_COST = "month_to_date_cost"
ATTR_ESTIMATED_REMAINING = "estimated_remaining"
ATTR_PERCENT_USED = "percent_used"
ATTR_DAYS_ELAPSED = "days_elapsed"
ATTR_PROJECTED_MONTH_END_COST = "projected_month_end_cost"
ATTR_AVERAGE_DAILY_COST = "average_daily_cost"
