"""
GCS storage utilities for the haithem folder in presti-tmp-test bucket.
Handles uploads, downloads, and upload history persisted in a JSON blob.
"""

import json
import re
from typing import Any

from google.cloud import storage
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError
from retry import retry

BUCKET_NAME = "presti-tmp-test"
HAITHEM_PREFIX = "haithem"
HISTORY_BLOB = f"{HAITHEM_PREFIX}/uploads_history.json"
OUTPUTS_PREFIX = f"{HAITHEM_PREFIX}/outputs"

_storage_client: storage.Client | None = None


def get_storage_client() -> storage.Client:
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client


def _upload_blob_from_memory(
    contents: bytes,
    destination_blob_name: str,
    content_type: str | None = None,
) -> None:
    """Upload bytes to a blob. Does not return URL."""
    client = get_storage_client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)
    if content_type is None:
        blob.upload_from_string(contents)
    else:
        blob.upload_from_string(contents, content_type=content_type)


@retry(exceptions=(SSLError, RequestsConnectionError), tries=3, delay=1, backoff=2)
def upload_to_haithem(
    contents: bytes,
    blob_path: str,
    content_type: str | None = None,
) -> str:
    """Upload to haithem/{blob_path}. Returns GCS URI (gs://bucket/path)."""
    full_path = f"{HAITHEM_PREFIX}/{blob_path}"
    _upload_blob_from_memory(contents, full_path, content_type)
    return f"gs://{BUCKET_NAME}/{full_path}"


def download_from_gcs(gcs_uri: str) -> bytes:
    """Download blob by GCS URI. Returns file contents as bytes."""
    match = re.match(r"gs://([^/]+)/(.+)", gcs_uri)
    if not match:
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    bucket_name, blob_path = match.groups()
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    return blob.download_as_bytes()


def list_outputs() -> list[dict[str, Any]]:
    """List output CSV files in haithem/outputs/. Returns list of {filename, size, modified, source}."""
    try:
        client = get_storage_client()
        bucket = client.bucket(BUCKET_NAME)
        blobs = bucket.list_blobs(prefix=f"{OUTPUTS_PREFIX}/")
        result = []
        for blob in blobs:
            if blob.name.endswith(".csv"):
                name = blob.name.split("/")[-1]
                result.append({
                    "filename": name,
                    "size": blob.size or 0,
                    "modified": blob.updated.timestamp() if blob.updated else 0,
                    "source": "gcs",
                })
        return result
    except Exception:
        return []


def download_output(filename: str) -> bytes:
    """Download an output file from GCS by filename. Raises if not found."""
    safe_name = filename.split("/")[-1] if "/" in filename else filename
    if not safe_name.endswith(".csv"):
        raise ValueError("Invalid file.")
    blob_path = f"{OUTPUTS_PREFIX}/{safe_name}"
    gcs_uri = f"gs://{BUCKET_NAME}/{blob_path}"
    return download_from_gcs(gcs_uri)


def read_history_json() -> list[dict[str, Any]]:
    """Read upload history from GCS. Returns empty list if missing or invalid."""
    try:
        client = get_storage_client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(HISTORY_BLOB)
        data = blob.download_as_bytes()
        history = json.loads(data.decode("utf-8"))
        return history if isinstance(history, list) else []
    except Exception:
        return []


def append_to_history(entry: dict[str, Any]) -> None:
    """Append an entry to upload history and write back to GCS."""
    history = read_history_json()
    history.append(entry)
    client = get_storage_client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(HISTORY_BLOB)
    blob.upload_from_string(
        json.dumps(history, indent=2),
        content_type="application/json",
    )
