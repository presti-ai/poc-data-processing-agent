"""
Custom tools for the data processing agent: web search, URL fetching, and image upload.

- Internet_search: Tavily-powered web search for finding information.
- Fetch_page_content: Clean text extraction via Jina Reader (bypasses some bot protection).
- Fetch_HTML_from_URL: Raw HTML fetch with Jina fallback on 403.
- Fetch_wayback_page: Fetch archived page from Wayback Machine when direct fetch fails.
- Upload_image_to_GCS: Download image from URL, upload to GCS, return new public URL.
"""

import os
import re
from datetime import datetime
from typing import Literal
from uuid import uuid4

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from loguru import logger
from tavily import TavilyClient

from p24_agent_node_poc.gcs_storage import upload_image_from_bytes

load_dotenv()

# API clients (keys from .env)
tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
jina_base = os.getenv("JINA_READER_BASE", "https://r.jina.ai")  # Jina Reader proxy
jina_api_key = os.getenv("JINA_API_KEY")


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


# Image magic bytes for validation
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
    (b"RIFF", "image/webp", "webp"),
)


def _is_image_content(data: bytes) -> tuple[bool, str, str]:
    """Check if bytes look like an image. Returns (is_valid, content_type, ext)."""
    for sig, ct, ext in _IMAGE_SIGNATURES:
        if data.startswith(sig):
            return True, ct, ext
    return False, "application/octet-stream", "bin"


def _extension_from_url(url: str) -> str:
    """Extract image extension from URL path."""
    match = re.search(r"\.(jpe?g|png|gif|webp|bmp)(?:\?|$)", url, re.I)
    if match:
        ext = match.group(1).lower()
        if ext == "jpeg":
            ext = "jpg"
        return ext
    return "jpg"


@tool("Upload_image_to_GCS")
def upload_image_to_gcs(image_url: str) -> str:
    """
    Download an image from a URL, upload it to GCS, and return the new public URL.
    Use this for EVERY image URL before adding it to output.csv. Do not put raw
    external image URLs in the output—always replace them with GCS URLs from this tool.
    """
    if not image_url or not isinstance(image_url, str):
        return "Error: image_url must be a non-empty string."
    url = image_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return f"Invalid URL (must start with http:// or https://): {url[:80]}"

    logger.info("Upload_image_to_GCS invoked: url={}", url[:80] + "..." if len(url) > 80 else url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except Exception as exc:
        logger.warning("Upload_image_to_GCS download failed: {}", exc)
        return f"Download failed: {exc}"

    if not resp.ok:
        return f"Download failed: HTTP {resp.status_code}"

    data = resp.content
    if len(data) < 12:
        return "Downloaded content too small to be a valid image."

    is_img, content_type, ext = _is_image_content(data)
    if not is_img:
        ext = _extension_from_url(url)
        content_type = f"image/{ext}" if ext != "bin" else "image/jpeg"

    if ext == "bin":
        ext = "jpg"
        content_type = "image/jpeg"

    date_prefix = datetime.now().strftime("%Y-%m-%d")
    blob_path = f"{date_prefix}_{uuid4().hex[:12]}.{ext}"

    try:
        public_url = upload_image_from_bytes(data, blob_path, content_type)
        logger.info("Upload_image_to_GCS success: {}", public_url[:80])
        return public_url
    except Exception as exc:
        logger.warning("Upload_image_to_GCS upload failed: {}", exc)
        return f"GCS upload failed: {exc}"


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
