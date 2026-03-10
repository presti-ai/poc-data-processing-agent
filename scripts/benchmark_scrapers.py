"""
Scraper benchmark: compare raw requests, Jina Reader, Firecrawl, and Browserbase
on a set of real product URLs.

Usage:
    # Test default scrapers (raw, jina, firecrawl) on UC2 small dataset (5 URLs):
    poetry run python scripts/benchmark_scrapers.py

    # Choose scrapers and URL limit:
    poetry run python scripts/benchmark_scrapers.py --scrapers jina firecrawl --limit 10

    # Use a custom CSV (must have a product_page_url column):
    poetry run python scripts/benchmark_scrapers.py --urls data/test_cases/uc3_product_multi_images/small_input.csv

    # Add Browserbase (requires BROWSERBASE_API_KEY + BROWSERBASE_PROJECT_ID in .env):
    poetry run python scripts/benchmark_scrapers.py --scrapers raw jina firecrawl browserbase

NOTE — Stagehand (https://www.stagehand.dev):
    Stagehand is a TypeScript/JavaScript-only framework with no stable Python SDK.
    It cannot be benchmarked directly from this script. To evaluate it you would
    need to build a small Node.js HTTP wrapper and call it as a subprocess.
    Consider it if the team is open to a mixed-language stack.

Results are printed as a summary table and saved to data/benchmark_results.csv.
"""

import argparse
import csv
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd
import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ScrapeResult:
    scraper: str
    url: str
    success: bool
    status_code: int | None
    latency_ms: float
    content_length: int        # number of characters returned
    error: str | None = None
    content_snippet: str = ""  # first 300 chars for manual inspection
    # quality: fraction of hint words found in content (0.0–1.0), None if no hint
    quality_score: float | None = field(default=None)


# ── Individual scraper functions ──────────────────────────────────────────────

def _make_result(scraper: str, url: str, *, success: bool, status_code: int | None,
                 latency_ms: float, content: str = "", error: str | None = None) -> ScrapeResult:
    return ScrapeResult(
        scraper=scraper,
        url=url,
        success=success,
        status_code=status_code,
        latency_ms=latency_ms,
        content_length=len(content),
        error=error,
        content_snippet=content[:300],
    )


def scrape_raw(url: str) -> ScrapeResult:
    """Direct HTTP GET with browser-like headers. Baseline — fastest but weakest bot bypass."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }
    t0 = time.perf_counter()
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        ms = (time.perf_counter() - t0) * 1000
        return _make_result("raw_requests", url, success=resp.ok,
                            status_code=resp.status_code, latency_ms=ms,
                            content=resp.text if resp.ok else "",
                            error=None if resp.ok else f"HTTP {resp.status_code}")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return _make_result("raw_requests", url, success=False, status_code=None,
                            latency_ms=ms, error=str(exc))


def scrape_jina(url: str) -> ScrapeResult:
    """Jina Reader — returns clean markdown text. Good bot bypass, no JS rendering."""
    jina_base = os.getenv("JINA_READER_BASE", "https://r.jina.ai")
    api_key = os.getenv("JINA_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    reader_url = f"{jina_base}/{url}"
    t0 = time.perf_counter()
    try:
        resp = requests.get(reader_url, headers=headers, timeout=30)
        ms = (time.perf_counter() - t0) * 1000
        return _make_result("jina_reader", url, success=resp.ok,
                            status_code=resp.status_code, latency_ms=ms,
                            content=resp.text if resp.ok else "",
                            error=None if resp.ok else f"HTTP {resp.status_code}")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return _make_result("jina_reader", url, success=False, status_code=None,
                            latency_ms=ms, error=str(exc))


def scrape_firecrawl(url: str) -> ScrapeResult:
    """Firecrawl — clean markdown with JS rendering. Strongest bot bypass of the three."""
    api_key = os.getenv("FireCrawl_API_KEY")
    if not api_key:
        return _make_result("firecrawl", url, success=False, status_code=None,
                            latency_ms=0, error="FireCrawl_API_KEY not set in .env")
    try:
        from firecrawl import FirecrawlApp
    except ImportError:
        return _make_result("firecrawl", url, success=False, status_code=None,
                            latency_ms=0, error="firecrawl-py not installed — run: poetry add firecrawl-py")
    t0 = time.perf_counter()
    try:
        app = FirecrawlApp(api_key=api_key)
        result = app.scrape_url(url, formats=["markdown"])
        ms = (time.perf_counter() - t0) * 1000
        # firecrawl-py >= 1.0 returns ScrapeResponse; older versions return a dict
        markdown = getattr(result, "markdown", None) or (
            result.get("markdown") if isinstance(result, dict) else None
        )
        if not markdown:
            return _make_result("firecrawl", url, success=False, status_code=None,
                                latency_ms=ms, error="No markdown content returned")
        return _make_result("firecrawl", url, success=True, status_code=200,
                            latency_ms=ms, content=markdown)
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return _make_result("firecrawl", url, success=False, status_code=None,
                            latency_ms=ms, error=str(exc))


def scrape_browserbase(url: str) -> ScrapeResult:
    """Browserbase — cloud Playwright session. Full JS rendering, strongest protection bypass.

    Requires in .env:
        BROWSERBASE_API_KEY=...
        BROWSERBASE_PROJECT_ID=...

    Install:  poetry add browserbase playwright && poetry run playwright install chromium
    """
    api_key = os.getenv("BROWSERBASE_API_KEY")
    project_id = os.getenv("BROWSERBASE_PROJECT_ID")
    if not api_key or not project_id:
        return _make_result(
            "browserbase", url, success=False, status_code=None, latency_ms=0,
            error="BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID not set in .env — skipping",
        )
    try:
        from browserbase import Browserbase
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return _make_result("browserbase", url, success=False, status_code=None,
                            latency_ms=0, error=f"Missing package: {exc}")
    t0 = time.perf_counter()
    try:
        bb = Browserbase(api_key=api_key)
        session = bb.sessions.create(project_id=project_id)
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                f"wss://connect.browserbase.com?apiKey={api_key}&sessionId={session.id}"
            )
            page = browser.new_page()
            page.goto(url, timeout=30_000)
            content = page.content()
            browser.close()
        ms = (time.perf_counter() - t0) * 1000
        return _make_result("browserbase", url, success=bool(content),
                            status_code=200 if content else None,
                            latency_ms=ms, content=content or "")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return _make_result("browserbase", url, success=False, status_code=None,
                            latency_ms=ms, error=str(exc))


# ── Scraper registry ──────────────────────────────────────────────────────────

SCRAPERS: dict[str, Callable[[str], ScrapeResult]] = {
    "raw":         scrape_raw,
    "jina":        scrape_jina,
    "firecrawl":   scrape_firecrawl,
    "browserbase": scrape_browserbase,
}


# ── Quality check ─────────────────────────────────────────────────────────────

def _quality_score(content: str, hint: str) -> float:
    """Fraction of the first 4 significant hint words found in content (case-insensitive)."""
    words = [w for w in hint.lower().split() if len(w) > 3][:4]
    if not words:
        return 0.0
    content_lower = content.lower()
    return sum(1 for w in words if w in content_lower) / len(words)


# ── Runner ────────────────────────────────────────────────────────────────────

def run_benchmark(
    urls: list[str],
    scraper_keys: list[str],
    hint_map: dict[str, str] | None = None,
) -> list[ScrapeResult]:
    results: list[ScrapeResult] = []
    for key in scraper_keys:
        fn = SCRAPERS[key]
        logger.info("── Scraper: {} ──────────────────────────────────", key)
        for url in urls:
            r = fn(url)
            if hint_map and url in hint_map and r.success and r.content_snippet:
                r.quality_score = _quality_score(r.content_snippet + r.content_snippet, hint_map[url])
            status = (
                f"✅  {r.status_code} | {r.latency_ms:6.0f}ms | {r.content_length:>8,} chars"
                + (f" | quality {r.quality_score:.0%}" if r.quality_score is not None else "")
                if r.success
                else f"❌  {r.error or r.status_code}"
            )
            logger.info("  {:<14} {}", url.split("/")[-2] or url[-30:], status)
            results.append(r)
    return results


# ── Summary table ─────────────────────────────────────────────────────────────

def print_summary(results: list[ScrapeResult]) -> None:
    from collections import defaultdict
    by_scraper: dict[str, list[ScrapeResult]] = defaultdict(list)
    for r in results:
        by_scraper[r.scraper].append(r)

    print("\n" + "═" * 80)
    print(f"  {'SCRAPER':<16} {'SUCCESS':>10}  {'AVG LATENCY':>13}  {'AVG CONTENT':>13}  {'AVG QUALITY':>12}")
    print("─" * 80)
    for scraper, rs in by_scraper.items():
        n = len(rs)
        ok = [r for r in rs if r.success]
        success_n = len(ok)
        avg_lat = sum(r.latency_ms for r in ok) / max(len(ok), 1)
        avg_len = sum(r.content_length for r in ok) / max(len(ok), 1)
        quality_rs = [r for r in ok if r.quality_score is not None]
        avg_q = sum(r.quality_score for r in quality_rs) / len(quality_rs) if quality_rs else None
        q_str = f"{avg_q:.0%}" if avg_q is not None else "   n/a"
        print(
            f"  {scraper:<16} {success_n:>4}/{n:<4} ({100*success_n/n:4.0f}%)"
            f"  {avg_lat:>10.0f} ms"
            f"  {avg_len:>10,.0f} ch"
            f"  {q_str:>12}"
        )
    print("═" * 80 + "\n")


# ── Save results ──────────────────────────────────────────────────────────────

def save_results(results: list[ScrapeResult], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "scraper", "url", "success", "status_code",
            "latency_ms", "content_length", "quality_score", "error",
        ])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "scraper": r.scraper,
                "url": r.url,
                "success": r.success,
                "status_code": r.status_code or "",
                "latency_ms": round(r.latency_ms, 1),
                "content_length": r.content_length,
                "quality_score": f"{r.quality_score:.2f}" if r.quality_score is not None else "",
                "error": r.error or "",
            })
    logger.info("Results saved → {}", output_path)


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark web scrapers on product page URLs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--urls",
        default="data/test_cases/uc2_packshot_dimensions/small_input.csv",
        help="CSV file with a product_page_url column (default: UC2 small)",
    )
    parser.add_argument(
        "--scrapers",
        nargs="+",
        choices=list(SCRAPERS.keys()),
        default=["raw", "jina", "firecrawl"],
        help="Scrapers to test (default: raw jina firecrawl)",
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Max URLs to test per scraper (default: 5)",
    )
    parser.add_argument(
        "--output",
        default="data/benchmark_results.csv",
        help="Output CSV path (default: data/benchmark_results.csv)",
    )
    args = parser.parse_args()

    input_path = PROJECT_ROOT / args.url if not Path(args.urls).is_absolute() else Path(args.urls)
    input_path = PROJECT_ROOT / args.urls  # always resolve relative to project root
    if not input_path.exists():
        logger.error("Input file not found: {}", input_path)
        return

    df = pd.read_csv(input_path)
    url_col = "product_page_url" if "product_page_url" in df.columns else df.columns[0]
    hint_col = "product_label_hint" if "product_label_hint" in df.columns else None

    urls = df[url_col].dropna().tolist()[: args.limit]
    hint_map = dict(zip(df[url_col], df[hint_col])) if hint_col else {}

    logger.info(
        "Benchmarking {} scraper(s) on {} URL(s) from {}",
        len(args.scrapers), len(urls), input_path.name,
    )

    results = run_benchmark(urls, args.scrapers, hint_map)
    print_summary(results)
    save_results(results, PROJECT_ROOT / args.output)


if __name__ == "__main__":
    main()
