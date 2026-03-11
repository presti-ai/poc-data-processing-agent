"""
Pricing constants for run cost estimation.

All prices are in USD. Update these when provider pricing changes.

Sources (verify at):
  Anthropic : https://www.anthropic.com/pricing
  Google    : https://ai.google.dev/pricing
  Firecrawl : https://www.firecrawl.dev/pricing
  GCS       : https://cloud.google.com/storage/pricing
"""

# ─── Anthropic Claude ──────────────────────────────────────────────────────────
# Price per 1 000 000 tokens (USD)

ANTHROPIC_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {
        "input":       15.00,   # $/1M input tokens
        "output":      75.00,   # $/1M output tokens
        "cache_read":   1.50,   # $/1M cache-read input tokens
        "cache_write": 18.75,   # $/1M cache-write input tokens
    },
    "claude-sonnet-4-6": {
        "input":       3.00,
        "output":      15.00,
        "cache_read":  0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-4-5": {
        "input":       0.25,
        "output":      1.25,
        "cache_read":  0.03,
        "cache_write": 0.30,
    },
}

# ─── Google Gemini ─────────────────────────────────────────────────────────────
# Approximate prices based on published Gemini 2.x tiers — update if different

GOOGLE_PRICES: dict[str, dict[str, float]] = {
    "gemini-3-flash-preview": {
        "input":  0.075,   # $/1M input tokens  (≈ Gemini 2.0 Flash tier)
        "output": 0.30,    # $/1M output tokens
    },
    "gemini-3.1-pro-preview": {
        "input":  1.25,    # $/1M input tokens  (≈ Gemini Pro tier, ≤128k ctx)
        "output": 5.00,    # $/1M output tokens
    },
    "gemini-3.5-pro-preview": {
        "input":  1.25,
        "output": 5.00,
    },
}

# ─── Firecrawl ─────────────────────────────────────────────────────────────────
# 1 scrape = 1 credit.  Hobby plan: $16 / 1 000 credits = $0.016 / credit.
# Update FIRECRAWL_USD_PER_CREDIT to match your plan.

FIRECRAWL_USD_PER_CREDIT: float = 0.016   # default: Hobby plan

# ─── GCS (optional, usually negligible) ───────────────────────────────────────

GCS_STORAGE_USD_PER_GB_MONTH: float = 0.020   # Standard storage, us-central1
GCS_EGRESS_USD_PER_GB: float = 0.12           # Egress outside Google network


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_llm_prices(model_id: str) -> dict[str, float] | None:
    """Return the price dict for a model string like 'anthropic:claude-opus-4-6'."""
    # Strip provider prefix (e.g. 'anthropic:', 'google_genai:')
    bare = model_id.split(":")[-1] if ":" in model_id else model_id

    # Exact match first
    if bare in ANTHROPIC_PRICES:
        return ANTHROPIC_PRICES[bare]
    if bare in GOOGLE_PRICES:
        return GOOGLE_PRICES[bare]

    # Prefix match (handles dated variants like claude-opus-4-6-20250514)
    for key, prices in ANTHROPIC_PRICES.items():
        if bare.startswith(key):
            return prices
    for key, prices in GOOGLE_PRICES.items():
        if bare.startswith(key):
            return prices

    return None


def estimate_llm_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Return estimated USD cost for one LLM call."""
    prices = _get_llm_prices(model_id)
    if prices is None:
        return 0.0
    M = 1_000_000
    cost = (
        input_tokens       * prices["input"]       / M
        + output_tokens    * prices["output"]      / M
        + cache_read_tokens  * prices.get("cache_read", 0)  / M
        + cache_write_tokens * prices.get("cache_write", 0) / M
    )
    return cost


def estimate_firecrawl_cost(credits_used: int) -> float:
    """Return estimated USD cost for Firecrawl credits."""
    return credits_used * FIRECRAWL_USD_PER_CREDIT
