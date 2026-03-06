"""
FastAPI server for the P24 data processing agent.
Serves the frontend and provides /api/run for agent execution with SSE streaming.
Also provides /api/upload (zip/files to GCS) and /api/history.
"""

import asyncio
import io
import json
import mimetypes
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from p24_agent_node_poc.agent import process_data
from p24_agent_node_poc.gcs_storage import (
    append_to_history,
    download_from_gcs,
    download_output as gcs_download_output,
    list_outputs as gcs_list_outputs,
    read_history_json,
    upload_to_haithem,
)

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}

app = FastAPI(title="P24 Agent API", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, exc: RequestValidationError):
    """Return validation errors in a client-friendly format."""
    return JSONResponse(
        status_code=422,
        content={"error": "Validation error", "detail": exc.errors()},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE event."""
    return f"data: {json.dumps(data)}\n\n"


async def _run_agent_sse(
    input_paths: list[Path],
    output_columns: list[dict],
    additional_instructions: str | None,
    model_name: str,
    subagent_model_name: str | None,
):
    """Async generator that yields SSE events from the agent run."""
    queue: Queue = Queue()

    def on_chunk(stream_mode: str, payload: dict):
        if stream_mode == "retry":
            queue.put(("retry", payload))
        else:
            queue.put(("chunk", {"stream_mode": stream_mode, "data": payload}))

    def run_in_thread():
        try:
            result_df, _ = process_data(
                input_files=input_paths,
                output_columns=output_columns,
                additional_instructions=additional_instructions or None,
                model_name=model_name,
                subagent_model_name=subagent_model_name or None,
                on_stream_chunk=on_chunk,
            )
            csv_str = result_df.to_csv(index=False)
            # Upload to GCS (agent already saves to data/output/ locally)
            try:
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                blob_path = f"outputs/output_{ts}.csv"
                upload_to_haithem(csv_str.encode("utf-8"), blob_path, "text/csv")
            except Exception:
                pass  # Don't fail the run if GCS upload fails
            queue.put(("done", {"csv": csv_str, "error": None}))
        except Exception as e:
            queue.put(("done", {"csv": None, "error": str(e)}))

    loop = asyncio.get_event_loop()
    task = asyncio.to_thread(run_in_thread)
    run_task = asyncio.create_task(task)

    try:
        while True:
            try:
                item = await asyncio.to_thread(lambda: queue.get(timeout=0.25))
            except Empty:
                if run_task.done():
                    break
                continue

            event_type, payload = item
            if event_type == "chunk":
                yield _sse_event({"type": "chunk", **payload})
            elif event_type == "retry":
                yield _sse_event({"type": "retry", "message": payload.get("message", "")})
            elif event_type == "done":
                yield _sse_event({"type": "done", **payload})
                break
    finally:
        if not run_task.done():
            run_task.cancel()


def _guess_content_type(filename: str) -> str | None:
    """Guess MIME type from filename."""
    guessed, _ = mimetypes.guess_type(filename)
    return guessed


def _safe_filename(name: str) -> str:
    """Sanitize filename for GCS (avoid path traversal, keep extension)."""
    base = Path(name).name
    return base if base else "unnamed"


@app.post("/api/upload")
async def api_upload(request: Request):
    """Upload zip or single file to GCS. Extracts zip contents, uploads each file, appends to history."""
    form = await request.form()
    files = form.getlist("file")
    if not files:
        files = form.getlist("files")
    if not files:
        return JSONResponse(
            status_code=400,
            content={"error": "Please upload at least one file (field: file or files)."},
        )

    upload_id = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{uuid4().hex[:8]}"
    uploaded_files: list[dict] = []

    try:
        for f in files:
            filename = f.filename or "unnamed"
            content = await f.read()

            if filename.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        ext = Path(info.filename).suffix.lower()
                        if ext not in ALLOWED_EXTENSIONS:
                            continue
                        safe_name = _safe_filename(info.filename)
                        if not safe_name:
                            continue
                        file_content = zf.read(info)
                        blob_path = f"{upload_id}/{safe_name}"
                        content_type = _guess_content_type(safe_name)
                        gcs_uri = upload_to_haithem(file_content, blob_path, content_type)
                        uploaded_files.append({
                            "name": safe_name,
                            "gcs_path": f"haithem/{blob_path}",
                            "gcs_uri": gcs_uri,
                            "content_type": content_type or "application/octet-stream",
                        })
            else:
                ext = Path(filename).suffix.lower()
                if ext not in ALLOWED_EXTENSIONS:
                    continue
                safe_name = _safe_filename(filename)
                blob_path = f"{upload_id}/{safe_name}"
                content_type = _guess_content_type(safe_name)
                gcs_uri = upload_to_haithem(content, blob_path, content_type)
                uploaded_files.append({
                    "name": safe_name,
                    "gcs_path": f"haithem/{blob_path}",
                    "gcs_uri": gcs_uri,
                    "content_type": content_type or "application/octet-stream",
                })

        if not uploaded_files:
            return JSONResponse(
                status_code=400,
                content={"error": "No allowed files found. Allowed: " + ", ".join(ALLOWED_EXTENSIONS)},
            )

        source_name = files[0].filename or "upload"
        entry = {
            "id": upload_id,
            "timestamp": datetime.now().isoformat(),
            "source": source_name,
            "files": uploaded_files,
        }
        append_to_history(entry)

        return JSONResponse(content={
            "id": upload_id,
            "source": source_name,
            "files": uploaded_files,
            "gcs_paths": [uf["gcs_uri"] for uf in uploaded_files],
        })
    except zipfile.BadZipFile:
        return JSONResponse(status_code=400, content={"error": "Invalid or corrupt zip file."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/history")
def api_history():
    """Return upload history from GCS (newest first)."""
    history = read_history_json()
    return {"history": list(reversed(history))}


OUTPUT_DIR = Path(__file__).parent / "data" / "output"


@app.get("/api/outputs")
def api_outputs():
    """Return list of previous agent outputs from local + GCS (newest first, deduplicated)."""
    seen: dict[str, dict] = {}
    # Local files
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.iterdir():
            if f.is_file() and f.suffix.lower() == ".csv":
                stat = f.stat()
                seen[f.name] = {
                    "filename": f.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "source": "local",
                }
    # GCS files (prefer GCS if same filename exists locally)
    for entry in gcs_list_outputs():
        name = entry["filename"]
        if name not in seen or entry.get("modified", 0) >= seen[name]["modified"]:
            seen[name] = {
                "filename": name,
                "size": entry["size"],
                "modified": entry["modified"],
                "source": "gcs",
            }
    files = sorted(seen.values(), key=lambda x: x["modified"], reverse=True)
    return {"outputs": files}


@app.get("/api/outputs/{filename}")
def api_output_download(filename: str):
    """Download a previous output CSV by filename. Tries GCS first, then local."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".csv"):
        return JSONResponse(status_code=400, content={"error": "Invalid file."})
    # Try GCS first
    try:
        content = gcs_download_output(safe_name)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )
    except Exception:
        pass
    # Fallback to local
    path = OUTPUT_DIR / safe_name
    if not path.exists() or not path.is_file():
        return JSONResponse(status_code=404, content={"error": "File not found."})
    return FileResponse(path, filename=safe_name, media_type="text/csv")


AGENT_EXTENSIONS = {".csv", ".xlsx", ".xls", ".txt"}


@app.post("/api/run")
async def api_run(request: Request):
    """Run the agent with uploaded files and/or files from history. Returns SSE stream of progress and result."""
    form = await request.form()
    files = form.getlist("files")
    history_file_ids = form.get("history_file_ids", "[]")
    output_columns = form.get("output_columns", "[]")
    additional_instructions = form.get("additional_instructions", "") or ""
    model_name = form.get("model_name", "anthropic:claude-opus-4-6") or "anthropic:claude-opus-4-6"
    subagent_model_name = form.get("subagent_model_name", "openai:gpt-5.4") or "openai:gpt-5.4"

    try:
        history_gcs_uris = json.loads(history_file_ids) if history_file_ids else []
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"error": "history_file_ids must be valid JSON."},
        )
    if not isinstance(history_gcs_uris, list):
        history_gcs_uris = []

    if not files and not history_gcs_uris:
        return JSONResponse(
            status_code=400,
            content={"error": "Please upload at least one file or select files from history."},
        )

    try:
        columns = json.loads(output_columns) if output_columns else []
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"error": "output_columns must be valid JSON."},
        )
    if not isinstance(columns, list):
        return JSONResponse(
            status_code=400,
            content={"error": "output_columns must be a JSON array."},
        )

    tmpdir = tempfile.mkdtemp()
    try:
        input_paths: list[Path] = []
        for i, f in enumerate(files):
            dest = Path(tmpdir) / (f.filename or f"input_{i}.csv")
            content = await f.read()
            dest.write_bytes(content)
            input_paths.append(dest)

        for i, gcs_uri in enumerate(history_gcs_uris):
            if not isinstance(gcs_uri, str) or not gcs_uri.startswith("gs://"):
                continue
            try:
                content = download_from_gcs(gcs_uri)
                name = Path(gcs_uri).name or f"history_{i}.csv"
                ext = Path(name).suffix.lower()
                if ext not in AGENT_EXTENSIONS:
                    continue
                dest = Path(tmpdir) / name
                counter = 0
                while dest.exists():
                    counter += 1
                    dest = Path(tmpdir) / f"{Path(name).stem}_{counter}{ext}"
                dest.write_bytes(content)
                input_paths.append(dest)
            except Exception:
                continue

        async def stream_with_cleanup():
            try:
                async for chunk in _run_agent_sse(
                    input_paths=input_paths,
                    output_columns=columns,
                    additional_instructions=additional_instructions or None,
                    model_name=model_name,
                    subagent_model_name=subagent_model_name or None,
                ):
                    yield chunk
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        return StreamingResponse(
            stream_with_cleanup(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


# Serve frontend static files
frontend_dir = Path(__file__).parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
