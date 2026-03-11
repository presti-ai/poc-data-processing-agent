import json
from typing import Any, Optional, TextIO

from langchain_core.messages import BaseMessage, messages_to_dict

# Debug log: truncate very long content to avoid huge files
DEBUG_LOG_TRUNCATE = 8000  # chars for tool results, page content, etc.


def _debug_log(f: TextIO, section: str, content: Any, truncate: bool = True) -> None:
    """Write a section to the debug log file."""
    if isinstance(content, dict):
        content = json.dumps(content, indent=2, default=str)
    elif not isinstance(content, str):
        content = str(content)
    if truncate and len(content) > DEBUG_LOG_TRUNCATE:
        content = content[:DEBUG_LOG_TRUNCATE] + f"\n... [TRUNCATED, total {len(content)} chars]"
    f.write(f"\n{'='*60}\n{section}\n{'='*60}\n{content}\n")
    f.flush()


SSE_TRUNCATE = 2000  # chars for SSE payloads to avoid huge events


def _serialize_chunk_for_sse(chunk: dict) -> Optional[dict]:
    """Convert a stream chunk to JSON-serializable dict for SSE. Returns None if empty."""
    payload: dict = {}
    if model_chunk := chunk.get("model"):
        msgs = model_chunk.get("messages", [])
        valid = [m for m in msgs if isinstance(m, BaseMessage)]
        if valid:
            payload["model"] = messages_to_dict(valid)
            # Truncate long content in payload
            for m in payload.get("model", []):
                d = m.get("data", {})
                if "content" in d:
                    c = d["content"]
                    if isinstance(c, str) and len(c) > SSE_TRUNCATE:
                        d["content"] = c[:SSE_TRUNCATE] + f"... [TRUNCATED, total {len(c)} chars]"
    if tool_chunk := chunk.get("tools"):
        msgs = tool_chunk.get("messages", [])
        valid = [m for m in msgs if isinstance(m, BaseMessage)]
        if valid:
            payload["tools"] = messages_to_dict(valid)
            for m in payload.get("tools", []):
                d = m.get("data", {})
                if "content" in d:
                    c = d["content"]
                    if isinstance(c, str) and len(c) > SSE_TRUNCATE:
                        d["content"] = c[:SSE_TRUNCATE] + f"... [TRUNCATED, total {len(c)} chars]"
    return payload if payload else None
