import os
from typing import Literal

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from loguru import logger
from tavily import TavilyClient

load_dotenv()

tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
jina_base = os.getenv("JINA_READER_BASE", "https://r.jina.ai")
jina_api_key = os.getenv("JINA_API_KEY")


@tool("Internet_search")
def internet_search(
        query: str,
        max_results: int = 5,
        topic: Literal["general", "news", "finance"] = "general",
        include_raw_content: bool = False,
):
    """Run a web search"""
    return tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )


@tool("Fetch_page_content")
def fetch_page_content(url: str) -> str:
    """Fetch cleaned page content for a URL using Jina Reader (r.jina.ai). Use this for any HTTP/HTTPS link found in the CSVs."""
    logger.success(f"Fetching page content from {url}")
    if not url.startswith("http://") and not url.startswith("https://"):
        return f"Invalid URL (must start with http:// or https://): {url}"
    reader_url = f"{jina_base}/{url}"
    headers = {}
    if jina_api_key:
        headers["Authorization"] = f"Bearer {jina_api_key}"
    try:
        resp = requests.get(reader_url, headers=headers, timeout=30)
    except Exception as exc:  # pragma: no cover - network / connectivity errors
        return f"Jina Reader request failed: {exc}"
    if not resp.ok:
        snippet = resp.text[:500]
        return f"Jina Reader returned {resp.status_code}: {snippet}"
    return resp.text


@tool("Fetch_HTML_from_URL")
def fetch_html(url: str) -> str:
    """Fetch the raw HTML content of a URL. Use this when the cleaned content from 'Fetch page content' is not enough and you need the full HTML structure."""
    if not url.startswith("http://") and not url.startswith("https://"):
        return f"Invalid URL (must start with http:// or https://): {url}"
    try:
        resp = requests.get(url, timeout=30)
    except Exception as exc:  # pragma: no cover - network / connectivity errors
        return f"Request failed: {exc}"
    if not resp.ok:
        snippet = resp.text[:500]
        return f"Request returned {resp.status_code}: {snippet}"
    return resp.text


if __name__ == '__main__':
    logger.info(f"Testing {internet_search.name}")
    logger.info(internet_search.invoke("BUT tables"))

    logger.info(f"Testing {fetch_page_content.name}")
    logger.info("Google")
    logger.info(fetch_page_content.invoke("https://www.google.com"))
    logger.info("BUT")
    logger.info(fetch_page_content.invoke("https://www.but.fr/produits/2099901526182/fiche.html"))

    logger.info(f"Testing {fetch_html.name}")
    logger.info("Google HTML snippet")
    html = fetch_html.invoke("https://www.google.com")
    logger.info(html[:500])
