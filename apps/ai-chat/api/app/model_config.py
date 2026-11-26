import json
import os
import re
from dataclasses import dataclass
from math import ceil

from fastapi import HTTPException

from app.db import query


def limit(name, default, minimum, maximum):
    value = int(os.getenv(name) or default)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


from chatflow_shared.auth import PUBLIC_DEMO

API_KEY = "" if PUBLIC_DEMO else os.getenv("OPENAI_API_KEY", "").strip()
INPUT_LIMIT = limit("AI_MAX_INPUT_TOKENS", 8192, 512, 32768)
OUTPUT_LIMIT = limit("AI_MAX_OUTPUT_TOKENS", 1024, 64, 8192)
USER_BUDGET = limit("AI_USER_DAILY_MICROUSD", 250_000, 1, 10**12)
GLOBAL_BUDGET = limit("AI_GLOBAL_DAILY_MICROUSD", 2_000_000, 1, 10**12)


@dataclass(frozen=True)
class Model:
    id: str
    input_price: int
    output_price: int


def configured_models():
    if not API_KEY:
        return {"mock": Model("mock", 0, 0)}
    entries = json.loads(os.getenv("AI_OPENAI_MODELS") or "{}")
    if not isinstance(entries, dict) or not entries or len(entries) > 20:
        raise ValueError("AI_OPENAI_MODELS must configure 1 to 20 text models and prices")
    result = {}
    for name, prices in entries.items():
        if name == "mock" or not re.fullmatch(r"[a-zA-Z0-9._:-]{1,100}", name):
            raise ValueError("AI_OPENAI_MODELS contains an invalid model ID")
        if not isinstance(prices, list) or len(prices) != 2 or any(
            type(value) is not int or not 1 <= value <= 10**9 for value in prices
        ):
            raise ValueError("Each model requires two positive integer prices")
        result[name] = Model(name, *prices)
    return result


MODELS = configured_models()


def context_window(messages):
    """Bound input using UTF-8 bytes plus per-message and request overhead."""
    selected_count = 0
    tokens = 32
    for message in reversed(messages):
        size = len(message["content"].encode("utf-8")) + 20
        if tokens + size > INPUT_LIMIT:
            break
        selected_count += 1
        tokens += size
    if not selected_count:
        raise HTTPException(422, "input_token_limit")
    first = len(messages) - selected_count
    # Omit an orphaned assistant turn when truncating from the left.
    if messages[first]["role"] == "assistant":
        tokens -= len(messages[first]["content"].encode("utf-8")) + 20
        first += 1
    return messages[first]["seq"], tokens


def reserve(conn, account, model, input_tokens):
    cost = ceil((input_tokens * model.input_price + OUTPUT_LIMIT * model.output_price) / 1_000_000)
    if not cost:
        return 0
    # Serialize admission across web processes before checking both daily budgets.
    query(conn, "SELECT pg_advisory_xact_lock(750321118)")
    totals = query(conn, """
        SELECT coalesce(sum(g.reserved_cost_microusd), 0) AS total,
               coalesce(sum(g.reserved_cost_microusd) FILTER (WHERE c.owner_id=:account), 0) AS own
        FROM generations g JOIN conversations c ON c.id=g.conversation_id
        WHERE g.reserved_cost_microusd>0 AND
              g.created_at >= date_trunc('day', current_timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
        """, account=account).mappings().one()
    if totals["total"] + cost > GLOBAL_BUDGET or totals["own"] + cost > USER_BUDGET:
        raise HTTPException(429, "daily_cost_limit")
    return cost
