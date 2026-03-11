"""Tool implementations used by the data-processing agent.

This module exposes LangChain tools for:

- Web search via Tavily (`Internet_search`).
- Readable page extraction via Jina Reader (`Fetch_page_content`).
- Firecrawl-based page fetching to local files with compact JSON outputs (`Fetch_firecrawl`).
- Wayback Machine fallback retrieval (`Fetch_wayback_page`).
- Uploading local workspace images to Google Cloud Storage (`Upload_file_gcs`).

The HTML-related tools are intentionally designed to avoid returning full HTML inline.
Instead, they write HTML to files in the current workspace and return structured JSON
containing file paths and metadata, which helps keep agent context compact.
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4
from firecrawl import Firecrawl

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
firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
_HTML_FETCH_OUTPUT_DIR = "fetched_html"


def _make_html_filename(url: str, suffix: str = "html") -> str:
    parsed = urlparse(url)
    host_part = re.sub(r"[^a-zA-Z0-9]+", "-", parsed.netloc).strip("-") or "url"
    path_part = re.sub(r"[^a-zA-Z0-9]+", "-", parsed.path).strip("-") or "root"
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{host_part}_{path_part[:64]}_{uuid4().hex[:8]}.{suffix}"


def _save_html_to_workspace(url: str, html: str, suffix: str = "html") -> str:
    output_dir = Path.cwd() / _HTML_FETCH_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / _make_html_filename(url, suffix=suffix)
    out_path.write_text(html, encoding="utf-8")
    return str(out_path.relative_to(Path.cwd()))


def _json_result(
    status: str,
    url: str,
    *,
    files: list[dict[str, str]] | None = None,
    fetched_via: str | None = None,
    http_status: int | None = None,
    comments: list[str] | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "status": status,
        "url": url,
    }
    if files:
        payload["files"] = files
    if fetched_via:
        payload["fetched_via"] = fetched_via
    if http_status is not None:
        payload["http_status"] = http_status
    if comments:
        payload["comments"] = comments
    if error:
        payload["error"] = error
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _parse_fetch_result(raw_result: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        return {
            "status": "error",
            "error": "Fetch_firecrawl returned non-JSON output.",
            "raw_result_snippet": raw_result[:200],
        }
    if not isinstance(parsed, dict):
        return {
            "status": "error",
            "error": "Fetch_firecrawl returned unexpected JSON type.",
        }
    return parsed


@tool("Internet_search")
def internet_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """Run a Tavily web search and return structured search results.

    Args:
        query: Search query text.
        max_results: Maximum number of results to request from Tavily.
        topic: Tavily topic scope (`general`, `news`, or `finance`).
        include_raw_content: Whether to include raw page snippets/content when available.

    Returns:
        A Tavily response object (typically a dict) containing result entries and
        related metadata.
    """
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


@tool("Fetch_firecrawl")
def fetch_firecrawl(url: str) -> str:
    """Fetch page content through Firecrawl, save it locally, and return compact JSON.

    Behavior:
    - Validates that the URL starts with `http://` or `https://`.
    - Fetches markdown + links via Firecrawl.
    - Saves Firecrawl output content to `fetched_html/` under the current workspace.

    The tool does **not** return full HTML inline. Instead, it returns JSON that
    includes local file path(s), status, fetch metadata, and optional comments/errors.

    Args:
        url: Absolute HTTP(S) URL to fetch.

    Returns:
        A JSON string with fields such as:
        - `status`: `ok` or `error`
        - `url`: input URL
        - `files`: list of saved files (on success)
        - `fetched_via`: transport/fallback used
        - `http_status`: response status code when available
        - `comments`: optional informational notes
        - `char_count`: HTML length on success
        - `error`: error description on failure
    """
    logger.info(
        "Fetch_firecrawl invoked: url={}",
        url[:80] + "..." if len(url) > 80 else url,
    )
    if not url.startswith("http://") and not url.startswith("https://"):
        return _json_result(
            "error",
            url,
            error="Invalid URL (must start with http:// or https://).",
        )

    if not firecrawl_api_key:
        return _json_result(
            "error",
            url,
            fetched_via="firecrawl",
            error="Firecrawl not configured: FIRECRAWL_API_KEY not set in .env",
        )

    try:
        app = Firecrawl(api_key=firecrawl_api_key)
        result = app.scrape(url, formats=["markdown", "links"])
        if not isinstance(result, dict):
            result = vars(result) if hasattr(result, "__dict__") else {}

        if isinstance(result.get("data"), dict):
            result = result["data"]

        markdown = result.get("markdown") or ""
        links = result.get("links") or []

        if not markdown and not links:
            return _json_result(
                "error",
                url,
                fetched_via="firecrawl",
                error=f"Firecrawl returned no content for {url}",
            )

        output = markdown
        if links:
            output += "\n\n## Links\n" + "\n".join(links)

        html_file_path = _save_html_to_workspace(url, output, suffix="md")
    except Exception as exc:
        return _json_result(
            "error",
            url,
            fetched_via="firecrawl",
            error=f"Firecrawl request failed: {exc}",
        )

    logger.info(
        "Fetch_firecrawl success: {} chars, {} links -> {}",
        len(markdown),
        len(links),
        html_file_path,
    )
    return _json_result(
        "ok",
        url,
        files=[{"path": html_file_path, "type": "markdown"}],
        fetched_via="firecrawl",
        extra={"char_count": len(output), "links_count": len(links)},
    )


@tool("Fetch_wayback_page")
def fetch_wayback_page(url: str, timestamp: str = "20240101000000") -> str:
    """Fetch an archived Wayback snapshot and return file-path based JSON.

    The tool attempts the provided timestamp first, then retries with predefined
    fallback timestamps. Each attempt delegates actual fetching to
    `Fetch_firecrawl` using a Wayback URL.

    On success, the returned JSON extends the base fetch contract with Wayback
    metadata (`original_url`, `wayback_timestamp`, `wayback_url`).

    Args:
        url: Original HTTP(S) URL to retrieve from archive.
        timestamp: Preferred Wayback timestamp in `YYYYMMDDhhmmss` format.

    Returns:
        A JSON string matching the `Fetch_firecrawl` contract with additional
        Wayback metadata on success, or an error payload including attempt details.
    """
    logger.info("Fetch_wayback_page invoked: url={} timestamp={}", url[:80], timestamp)
    if not url.startswith("http://") and not url.startswith("https://"):
        return _json_result(
            "error",
            url,
            error="Invalid URL (must start with http:// or https://).",
        )

    tried_timestamps = [timestamp] + [
        ts for ts in ["20230101000000", "20220101000000"] if ts != timestamp
    ]
    attempts: list[dict[str, str]] = []

    for ts in tried_timestamps:
        wayback_url = f"https://web.archive.org/web/{ts}/{url}"
        result = _parse_fetch_result(fetch_firecrawl.invoke(wayback_url))
        if result.get("status") == "ok":
            comments = list(result.get("comments", []))
            comments.append(
                f"Fetched archived snapshot from Wayback timestamp {ts} for original URL."
            )
            result["comments"] = comments
            result["original_url"] = url
            result["wayback_timestamp"] = ts
            result["wayback_url"] = wayback_url
            return json.dumps(result, ensure_ascii=False)

        attempts.append({"timestamp": ts, "error": str(result.get("error", "unknown"))})

    return _json_result(
        "error",
        url,
        comments=["Wayback fetch attempts failed for all tested timestamps."],
        error="Could not fetch archived page content.",
        extra={"attempts": attempts},
    )


@tool("Upload_file_gcs")
def upload_file_gcs(file_path: str) -> str:
    """Upload a local workspace image to Google Cloud Storage and return a public URL.

    Security and usage constraints:
    - The provided path is sanitized to basename-only to prevent path traversal.
    - Only known image extensions are accepted (`.jpg`, `.jpeg`, `.png`, `.gif`,
      `.webp`, `.bmp`).
    - The file must exist in the current workspace.

    This tool is intended for converting local image artifacts into stable remote URLs
    for final CSV outputs.

    Args:
        file_path: Workspace-relative image filename (for example `photo.jpg`).

    Returns:
        Public GCS URL as a string on success, otherwise an explanatory error message.
    """
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

    logger.info(f"Testing {fetch_firecrawl.name}")
    logger.info("Google HTML snippet")
    logger.info(fetch_firecrawl.invoke("https://www.google.com"))
    logger.info("BUT HTML snippet")
    logger.info(
        fetch_firecrawl.invoke("https://www.but.fr/produits/2099901526182/fiche.html")[:100]
    )
