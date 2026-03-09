"""
Post-processing: migrate image URLs in output CSV to GCS.
Detects image URLs by extension heuristic, downloads each, uploads to GCS, replaces in DataFrame.
"""

import re
from datetime import datetime
from uuid import uuid4

import pandas as pd
import requests
from loguru import logger

from p24_agent_node_poc.gcs_storage import upload_image_from_bytes

# Image magic bytes for validation
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
    (b"RIFF", "image/webp", "webp"),
)

# Regex: URL has image extension in path (before ? or end)
_IMAGE_URL_PATTERN = re.compile(
    r"^https?://.+(?:\.(?:jpe?g|png|gif|webp|bmp))(?:\?.*)?$",
    re.IGNORECASE,
)


def is_image_url(value: str) -> bool:
    """Return True if value looks like an external image URL (not already GCS)."""
    if not value or not isinstance(value, str):
        return False
    s = value.strip()
    if not s.startswith("http://") and not s.startswith("https://"):
        return False
    # Skip URLs already in GCS
    if s.startswith("https://storage.googleapis.com/") or s.startswith("gs://"):
        return False
    return bool(_IMAGE_URL_PATTERN.search(s))


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


def upload_image_url_to_gcs(url: str) -> str | None:
    """
    Download image from URL, upload to GCS, return public URL.
    Returns None on any failure.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except Exception as exc:
        logger.warning("image_migration: download failed for {}: {}", url[:60], exc)
        return None

    if not resp.ok:
        logger.warning("image_migration: HTTP {} for {}", resp.status_code, url[:60])
        return None

    data = resp.content
    if len(data) < 12:
        return None

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
        return public_url
    except Exception as exc:
        logger.warning("image_migration: GCS upload failed for {}: {}", url[:60], exc)
        return None


def migrate_image_urls_in_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Scan all cells, detect image URLs by heuristic, upload to GCS, replace in DataFrame.
    Deduplicates: same URL is uploaded once and reused.
    """
    cache: dict[str, str] = {}  # original_url -> gcs_url

    def process_cell(value) -> str:
        s = str(value).strip() if pd.notna(value) else ""
        if not is_image_url(s):
            return value
        if s in cache:
            return cache[s]
        gcs_url = upload_image_url_to_gcs(s)
        if gcs_url:
            cache[s] = gcs_url
            return gcs_url
        return value

    # Apply to all cells; use map to preserve types where possible
    result = df.copy()
    for col in result.columns:
        result[col] = result[col].apply(process_cell)

    if cache:
        logger.info("Migrated {} unique image URLs to GCS", len(cache))
    return result
