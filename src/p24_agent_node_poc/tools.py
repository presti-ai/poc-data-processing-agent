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
    """Fetch the raw HTML content of a URL. Use this when the cleaned content from 'Fetch page content' is not enough and you need the full HTML structure.
    If the direct request fails with a 403 (e.g. due to bot protection), this tool will automatically try to fetch it via Jina Reader.
    """
    logger.success(f"Fetching page content from {url}")
    if not url.startswith("http://") and not url.startswith("https://"):
        return f"Invalid URL (must start with http:// or https://): {url}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except Exception as exc:  # pragma: no cover - network / connectivity errors
        return f"Request failed: {exc}"

    if resp.status_code == 403:
        logger.info(f"Direct request to {url} returned 403. Trying via Jina Reader...")
        reader_url = f"{jina_base}/{url}"
        jina_headers = {"X-Return-Format": "html"}
        if jina_api_key:
            jina_headers["Authorization"] = f"Bearer {jina_api_key}"
        try:
            resp = requests.get(reader_url, headers=jina_headers, timeout=30)
        except Exception as exc:
            return f"Jina Reader fallback failed: {exc}"

    if not resp.ok:
        snippet = resp.text[:500]
        return f"Request returned {resp.status_code}: {snippet}"
    return resp.text


if __name__ == '__main__':
    logger.info(f"Testing {internet_search.name}")
    logger.info(internet_search.invoke("BUT tables"))

    # logger.info(f"Testing {fetch_page_content.name}")
    # logger.info("Google")
    # logger.info(fetch_page_content.invoke("https://www.google.com"))
    # logger.info("BUT")
    # logger.info(fetch_page_content.invoke("https://www.but.fr/produits/2099901526182/fiche.html"))

    logger.info(f"Testing {fetch_html.name}")
    logger.info("Google HTML snippet")
    logger.info(fetch_html.invoke("https://www.google.com")[:100])
    logger.info("BUT HTML snippet")
    logger.info(fetch_html.invoke("https://www.but.fr/produits/2099901526182/fiche.html")[:100])
