"""
Custom tools for the data processing agent: web search and URL fetching.

- Internet_search: Tavily-powered web search for finding information.
- Fetch_page_content: Clean text extraction via Jina Reader (bypasses some bot protection).
- Fetch_HTML_from_URL: Raw HTML fetch with Jina fallback on 403.
- Fetch_wayback_page: Fetch archived page from Wayback Machine when direct fetch fails.
- Fetch_firecrawl: Clean markdown extraction via Firecrawl (handles JS rendering, strong bot bypass).
- Upload_file_gcs: Upload a local image file from the workspace to GCS and return its public URL.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from loguru import logger
from tavily import TavilyClient

from p24_agent_node_poc.gcs_storage import upload_image_from_bytes

load_dotenv()

# Image extension -> content type for Upload_file_gcs
_IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

# API clients (keys from .env)
tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
jina_base = os.getenv("JINA_READER_BASE", "https://r.jina.ai")  # Jina Reader proxy
jina_api_key = os.getenv("JINA_API_KEY")
firecrawl_api_key = os.getenv("FireCrawl_API_KEY")


@tool("Internet_search")
def internet_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """Run a web search using Tavily."""
    logger.info("Internet_search invoked: query={} max_results={}", query[:100], max_results)
    result = tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )
    n_results = len(result.get("results", [])) if isinstance(result, dict) else 0
    logger.info("Internet_search success: {} results", n_results)
    return result


@tool("Fetch_page_content")
def fetch_page_content(url: str) -> str:
    """Fetch cleaned page content via Jina Reader (returns readable text, not raw HTML)."""
    logger.info("Fetch_page_content invoked: url={}", url[:80] + "..." if len(url) > 80 else url)
    if not url.startswith("http://") and not url.startswith("https://"):
        return f"Invalid URL (must start with http:// or https://): {url}"
    # Jina Reader: GET https://r.jina.ai/{url} returns cleaned text
    reader_url = f"{jina_base}/{url}"
    headers = {}
    if jina_api_key:
        headers["Authorization"] = f"Bearer {jina_api_key}"
    try:
        # Jina bypasses many bot blocks; returns markdown-like text
        resp = requests.get(reader_url, headers=headers, timeout=30)
    except Exception as exc:  # pragma: no cover - network / connectivity errors
        return f"Jina Reader request failed: {exc}"
    if not resp.ok:
        snippet = resp.text[:500]
        if resp.status_code == 402:
            return (
                f"Jina Reader returned 402 (Payment Required). "
                f"Try Fetch_wayback_page for archived content, or Fetch_HTML_from_URL for raw HTML."
            )
        return f"Jina Reader returned {resp.status_code}: {snippet}"
    logger.info("Fetch_page_content success: {} chars", len(resp.text))
    return resp.text


@tool("Fetch_HTML_from_URL")
def fetch_html(url: str) -> str:
    """Fetch raw HTML. Falls back to Jina Reader on 403 (bot protection)."""
    logger.success(f"Fetching page content from {url}")
    if not url.startswith("http://") and not url.startswith("https://"):
        return f"Invalid URL (must start with http:// or https://): {url}"

    # Browser-like headers to reduce 403 rates
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except Exception as exc:  # pragma: no cover - network / connectivity errors
        return f"Request failed: {exc}"

    # On 403 (bot block), retry via Jina Reader which often succeeds
    if resp.status_code == 403:
        logger.info(f"Direct request to {url} returned 403. Trying via Jina Reader...")
        reader_url = f"{jina_base}/{url}"
        jina_headers = {"X-Return-Format": "html"}
        if jina_api_key:
            jina_headers["Authorization"] = f"Bearer {jina_api_key}"
        try:
            resp = requests.get(reader_url, headers=jina_headers, timeout=15)
        except Exception as exc:
            return f"Jina Reader fallback failed: {exc}"

    if not resp.ok:
        snippet = resp.text[:500]
        return f"Request returned {resp.status_code}: {snippet}"
    logger.info("Fetch_HTML_from_URL success: {} chars", len(resp.text))
    return resp.text


@tool("Fetch_wayback_page")
def fetch_wayback_page(url: str, timestamp: str = "20240101000000") -> str:
    """Fetch an archived snapshot of a URL from the Wayback Machine. Use when direct fetch fails (403, 404, 402)."""
    logger.info("Fetch_wayback_page invoked: url={} timestamp={}", url[:80], timestamp)
    if not url.startswith("http://") and not url.startswith("https://"):
        return f"Invalid URL (must start with http:// or https://): {url}"
    wayback_url = f"https://web.archive.org/web/{timestamp}/{url}"
    result = fetch_html.invoke(wayback_url)
    if "returned 403" in result or "returned 404" in result or "returned 402" in result:
        # Try a few alternative timestamps
        for ts in ["20230101000000", "20220101000000"]:
            if ts == timestamp:
                continue
            wayback_url = f"https://web.archive.org/web/{ts}/{url}"
            result = fetch_html.invoke(wayback_url)
            if "returned" not in result or "success" in result.lower():
                break
    return result


@tool("Fetch_firecrawl")
def fetch_firecrawl(url: str) -> str:
    """Fetch a page via Firecrawl and return clean markdown content plus all page links.
    Handles JavaScript rendering and strong bot protection better than raw requests or Jina.
    Returns markdown text followed by a '## Links' section listing all URLs found on the page
    (including lazy-loaded images and assets). Use this as the primary scraping tool.
    """
    logger.info("Fetch_firecrawl invoked: url={}", url[:80] + "..." if len(url) > 80 else url)
    if not url.startswith("http://") and not url.startswith("https://"):
        return f"Invalid URL (must start with http:// or https://): {url}"
    if not firecrawl_api_key:
        return "Firecrawl not configured: FireCrawl_API_KEY not set in .env"
    try:
        from firecrawl import FirecrawlApp
    except ImportError:
        return "firecrawl-py not installed. Run: poetry add firecrawl-py"
    try:
        app = FirecrawlApp(api_key=firecrawl_api_key)
        result = app.scrape_url(url, params={"formats": ["markdown", "links"]})
        if not isinstance(result, dict):
            result = vars(result) if hasattr(result, "__dict__") else {}
        markdown = result.get("markdown") or ""
        links: list = result.get("links") or []
        if not markdown and not links:
            return f"Firecrawl returned no content for {url}"
        output = markdown
        if links:
            output += "\n\n## Links\n" + "\n".join(links)
        logger.info("Fetch_firecrawl success: {} chars, {} links", len(markdown), len(links))
        return output
    except Exception as exc:
        return f"Firecrawl request failed: {exc}"


@tool("Upload_file_gcs")
def upload_file_gcs(file_path: str) -> str:
    """Upload an image file from the workspace to GCS and return its public URL.
    Use this when the output requires a URL for a local image.
    Pass the filename relative to the workspace (e.g. TABLE_GPW037.jpg).
    Do not use Python_REPL to upload to tmpfiles, uguu, catbox, or other services."""
    # Sanitize: strip leading slash, use only basename to prevent path traversal
    path = file_path.strip().lstrip("/")
    path = Path(path).name
    if not path:
        return "Invalid file_path: empty or invalid."
    ext = Path(path).suffix.lower()
    if ext not in _IMAGE_CONTENT_TYPES:
        return f"Unsupported image type: {ext}. Supported: {list(_IMAGE_CONTENT_TYPES.keys())}"
    content_type = _IMAGE_CONTENT_TYPES[ext]
    full_path = Path.cwd() / path
    if not full_path.exists() or not full_path.is_file():
        return f"File not found: {path}"
    try:
        data = full_path.read_bytes()
    except OSError as e:
        return f"Cannot read file {path}: {e}"
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    blob_path = f"{date_prefix}_{uuid4().hex[:12]}{ext}"
    try:
        public_url = upload_image_from_bytes(data, blob_path, content_type)
        logger.info("Upload_file_gcs success: {} -> {}", path, public_url[:80] + "...")
        return public_url
    except Exception as e:
        logger.warning("Upload_file_gcs failed for {}: {}", path, e)
        return f"GCS upload failed: {e}"


# CLI test: run with `python -m p24_agent_node_poc.tools`
if __name__ == "__main__":
    logger.info(f"Testing {internet_search.name}")
    logger.info(internet_search.invoke("BUT tables"))

    logger.info(f"Testing {fetch_html.name}")
    logger.info("Google HTML snippet")
    logger.info(fetch_html.invoke("https://www.google.com")[:100])
    logger.info("BUT HTML snippet")
    logger.info(
        fetch_html.invoke("https://www.but.fr/produits/2099901526182/fiche.html")[:100]
    )
