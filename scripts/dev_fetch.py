#!/usr/bin/env python3
"""Fetch OpenAI Admin usage data outside Home Assistant for development."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from aiohttp import ClientSession

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from custom_components.openai_usage_monitor.api import OpenAIAdminClient  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, required=True, help="Unix start time")
    parser.add_argument("--end", type=int, required=True, help="Unix end time")
    parser.add_argument("--category", default="completions")
    args = parser.parse_args()

    key = os.environ.get("OPENAI_ADMIN_KEY")
    if not key:
        print("Set OPENAI_ADMIN_KEY in the environment.", file=sys.stderr)
        return 2

    async with ClientSession() as session:
        client = OpenAIAdminClient(session, key)
        costs = await client.fetch_costs(start_time=args.start, end_time=args.end, limit=31)
        usage = await client.fetch_usage(
            args.category,
            start_time=args.start,
            end_time=args.end,
            group_by=["project_id", "api_key_id", "model"],
            limit=31,
        )
    print(json.dumps({"costs": costs, "usage": usage}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
