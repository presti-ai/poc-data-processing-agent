"""
CostTracker: accumulates token usage and Firecrawl credits during a run,
then produces a cost summary dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from p24_agent_node_poc.cost_constants import estimate_firecrawl_cost, estimate_llm_cost


@dataclass
class CostTracker:
    # LLM usage per model  {model_id: {input, output, cache_read, cache_write}}
    llm_usage: dict[str, dict[str, int]] = field(default_factory=dict)
    # Firecrawl
    firecrawl_credits: int = 0

    # ── recording ─────────────────────────────────────────────────────────────

    def record_llm(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        if model_id not in self.llm_usage:
            self.llm_usage[model_id] = {
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
            }
        u = self.llm_usage[model_id]
        u["input"] += input_tokens
        u["output"] += output_tokens
        u["cache_read"] += cache_read_tokens
        u["cache_write"] += cache_write_tokens

    def record_firecrawl(self, credits: int) -> None:
        self.firecrawl_credits += credits

    # ── summary ───────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return a serialisable cost breakdown dict."""
        llm_breakdown = {}
        total_llm_usd = 0.0

        for model_id, u in self.llm_usage.items():
            usd = estimate_llm_cost(
                model_id,
                input_tokens=u["input"],
                output_tokens=u["output"],
                cache_read_tokens=u["cache_read"],
                cache_write_tokens=u["cache_write"],
            )
            total_llm_usd += usd
            llm_breakdown[model_id] = {
                "input_tokens": u["input"],
                "output_tokens": u["output"],
                "cache_read_tokens": u["cache_read"],
                "cache_write_tokens": u["cache_write"],
                "estimated_usd": round(usd, 6),
            }

        firecrawl_usd = estimate_firecrawl_cost(self.firecrawl_credits)
        total_usd = total_llm_usd + firecrawl_usd

        return {
            "llm": llm_breakdown,
            "firecrawl": {
                "credits_used": self.firecrawl_credits,
                "estimated_usd": round(firecrawl_usd, 6),
            },
            "total_estimated_usd": round(total_usd, 6),
            "total_estimated_eur": round(total_usd * 0.92, 6),  # rough EUR conversion
        }
