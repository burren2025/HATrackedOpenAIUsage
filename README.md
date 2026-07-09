# OpenAI Usage Monitor for Home Assistant

Home Assistant custom integration for monitoring OpenAI API organization usage with the official OpenAI Admin Usage and Costs APIs.

## What it uses

This integration calls the documented OpenAI Admin endpoints:

- `/v1/organization/costs`
- `/v1/organization/usage/completions`
- `/v1/organization/usage/embeddings`
- `/v1/organization/usage/images`
- `/v1/organization/usage/audio_transcriptions`
- `/v1/organization/usage/audio_speeches`
- `/v1/organization/usage/moderations`
- `/v1/organization/usage/vector_stores`
- `/v1/organization/usage/code_interpreter_sessions`
- `/v1/organization/usage/file_search_calls`
- `/v1/organization/usage/web_search_calls`

It handles pagination and gracefully records categories that are unavailable for your account.

## Security

An OpenAI Admin API key is powerful. Use this only on a trusted Home Assistant instance, restrict access to Home Assistant backups, and rotate the key if you suspect exposure. The integration stores the key in Home Assistant config entry storage and redacts it from diagnostics and logs.

## Installation

### HACS custom repository

HACS cannot install from private GitHub repositories. To use HACS for installation and updates, this repository must be public or moved to another public repository.

Once public, add it in HACS:

1. Open HACS.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/burren2025/HATrackedOpenAIUsage`.
4. Select repository type **Integration**.
5. Download **OpenAI Usage Monitor**.
6. Restart Home Assistant.
7. Add **OpenAI Usage Monitor** from **Settings > Devices & services > Add integration**.

For updates, install new GitHub releases through HACS and restart Home Assistant when prompted.

### Manual installation

Copy `custom_components/openai_usage_monitor` into:

```text
config/custom_components/openai_usage_monitor
```

Restart Home Assistant, then add **OpenAI Usage Monitor** from **Settings > Devices & services > Add integration**.

## Configuration

The UI setup asks for:

- OpenAI Admin API key
- Friendly organization/account name
- Optional manual monthly credit or budget
- Optional warning thresholds
- Polling interval, default 60 minutes, minimum 30 minutes

Options allow updating the API key, polling interval, budget, thresholds, top-N model sensor count, and local alias maps for API key IDs and project IDs.

Alias maps are JSON objects:

```json
{"key_abc123": "Production app", "proj_abc123": "Backend project"}
```

## Entities

Organization totals:

- `sensor.openai_cost_today`
- `sensor.openai_cost_month_to_date`
- `sensor.openai_requests_today`
- `sensor.openai_requests_month_to_date`
- `sensor.openai_input_tokens_today`
- `sensor.openai_output_tokens_today`
- `sensor.openai_total_tokens_today`
- `sensor.openai_input_tokens_month_to_date`
- `sensor.openai_output_tokens_month_to_date`
- `sensor.openai_total_tokens_month_to_date`
- `sensor.openai_estimated_credit_remaining`

Dynamic sensors are created when OpenAI returns inventory or grouped usage data:

- One monthly-spend record sensor per API key ID
- One monthly-spend record sensor per project ID
- Top-N model token sensors

API key record attributes include name, status, tracking ID, redacted key value, created time, last-used time, expiration time, project access, owner/created-by metadata when returned by OpenAI, monthly spend, requests, token totals, category breakdowns, and model breakdowns.

Project record attributes include name, status, tracking ID, created time, archived time, external key ID, associated API key summaries where available, monthly spend, requests, token totals, category breakdowns, and model breakdowns.

Attributes also include line items where returned by the Costs API and last update time.

## Credit and budget

OpenAI's documented Admin Usage and Costs APIs expose costs and usage, but no official remaining credit or balance endpoint was found in the public API reference. The remaining credit sensor is therefore locally estimated:

```text
manual_monthly_credit_or_budget - month_to_date_cost
```

The sensor attributes include configured budget, month-to-date cost, estimated remaining, percent used, days elapsed, projected month-end cost, and average daily cost.

## Automations

See [examples/automations.yaml](examples/automations.yaml) for alerts covering:

- Today's spend exceeds a threshold
- Estimated remaining credit drops below a threshold
- Projected month-end cost exceeds configured budget
- Any single API key exceeds a threshold
- A new unknown API key ID appears

## Development

Install test dependencies in a virtual environment, then run:

```bash
pytest
python scripts/dev_fetch.py --start 1730419200 --end 1730505600
```

The helper reads `OPENAI_ADMIN_KEY` from the environment and never prints the key or authorization headers.

## Limitations

- Friendly API key names are not returned by the usage endpoints; use local aliases.
- Remaining credit is estimated locally unless OpenAI adds an official balance endpoint.
- Some usage categories may be unavailable depending on account permissions, product access, or API rollout.
