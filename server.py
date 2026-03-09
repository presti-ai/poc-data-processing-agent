"""
FastAPI server for the P24 data processing agent.
Serves the frontend and provides /api/run for agent execution with SSE streaming.
Run history is stored in GCS; inputs are uploaded to GCS when Run is clicked.
"""

import asyncio
import csv
import io
import json
import mimetypes
import shutil
import tempfile
import time
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
    append_run,
    delete_run,
    download_from_gcs,
    download_output as gcs_download_output,
    get_run,
    list_outputs as gcs_list_outputs,
    read_runs_history,
    upload_image_from_bytes,
    upload_to_haithem,
)

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

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
    run_id: str,
    start_time: float,
    input_infos: list[dict],
    params: dict,
    example_output_path: Path | None = None,
):
    """Async generator that yields SSE events from the agent run."""
    queue: Queue = Queue()

    def on_chunk(stream_mode: str, payload: dict):
        if stream_mode == "retry":
            queue.put(("retry", payload))
        else:
            queue.put(("chunk", {"stream_mode": stream_mode, "data": payload}))

    def run_in_thread():
        output_gcs_uri = None
        try:
            result_df, _ = process_data(
                input_files=input_paths,
                output_columns=output_columns,
                additional_instructions=additional_instructions or None,
                model_name=model_name,
                subagent_model_name=subagent_model_name or None,
                on_stream_chunk=on_chunk,
                example_output_path=example_output_path,
            )
            csv_str = result_df.to_csv(index=False)
            try:
                output_filename = f"output_{run_id}.csv"
                blob_path = f"outputs/{output_filename}"
                output_gcs_uri = upload_to_haithem(csv_str.encode("utf-8"), blob_path, "text/csv")
            except Exception:
                pass
            queue.put(("done", {"csv": csv_str, "error": None, "output_gcs_uri": output_gcs_uri}))
        except Exception as e:
            queue.put(("done", {"csv": None, "error": str(e), "output_gcs_uri": None}))

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
                duration_seconds = time.time() - start_time
                outputs = []
                if payload.get("output_gcs_uri"):
                    outputs.append({"name": f"output_{run_id}.csv", "gcs_uri": payload["output_gcs_uri"]})
                status = "failed" if payload.get("error") else "completed"
                run_entry = {
                    "id": run_id,
                    "timestamp": datetime.fromtimestamp(start_time).isoformat(),
                    "inputs": input_infos,
                    "outputs": outputs,
                    "duration_seconds": round(duration_seconds, 2),
                    "status": status,
                    "params": params,
                }
                try:
                    append_run(run_entry)
                except Exception:
                    pass
                done_payload = {**payload, "run_id": run_id}
                yield _sse_event({"type": "done", **done_payload})
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


@app.get("/api/runs")
def api_runs():
    """Return run history from GCS (newest first)."""
    runs = read_runs_history()
    return {"runs": list(reversed(runs))}


@app.get("/api/runs/{run_id}")
def api_run_get(run_id: str):
    """Return a single run by id for preset/rerun."""
    run = get_run(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"error": "Run not found."})
    return run


@app.delete("/api/runs/{run_id}")
def api_run_delete(run_id: str):
    """Remove a run from history (files stay in GCS)."""
    if not delete_run(run_id):
        return JSONResponse(status_code=404, content={"error": "Run not found."})
    return {"ok": True}


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
    sample_size = int(form.get("sample_size", "0") or "0")
    skip_rows = int(form.get("skip_rows", "0") or "0")

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

    run_id = f"run_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{uuid4().hex[:8]}"
    start_time = time.time()
    params = {
        "model_name": model_name,
        "subagent_model_name": subagent_model_name,
        "output_columns": columns,
        "additional_instructions": additional_instructions,
    }
    input_infos: list[dict] = []

    tmpdir = tempfile.mkdtemp()
    try:
        input_paths: list[Path] = []
        upload_prefix = f"uploads/{run_id}"

        for i, f in enumerate(files):
            content = await f.read()
            filename = f.filename or f"input_{i}.csv"
            if filename.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
                    for name in zf.namelist():
                        if name.endswith("/"):
                            continue
                        safe = _safe_filename(name)
                        ext = Path(safe).suffix.lower()
                        if ext not in ALLOWED_EXTENSIONS and ext not in AGENT_EXTENSIONS:
                            continue
                        blob_path = f"{upload_prefix}/{safe}"
                        try:
                            gcs_uri = upload_to_haithem(zf.read(name), blob_path, _guess_content_type(safe))
                            input_infos.append({"name": safe, "gcs_uri": gcs_uri})
                            dest = Path(tmpdir) / safe
                            counter = 0
                            while dest.exists():
                                counter += 1
                                dest = Path(tmpdir) / f"{Path(safe).stem}_{counter}{ext}"
                            dest.write_bytes(zf.read(name))
                            input_paths.append(dest)
                        except Exception:
                            continue
            else:
                safe = _safe_filename(filename)
                blob_path = f"{upload_prefix}/{safe}"
                try:
                    gcs_uri = upload_to_haithem(content, blob_path, _guess_content_type(safe))
                    input_infos.append({"name": safe, "gcs_uri": gcs_uri})
                except Exception:
                    pass
                dest = Path(tmpdir) / (safe or f"input_{i}.csv")
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
                input_infos.append({"name": name, "gcs_uri": gcs_uri})
                dest = Path(tmpdir) / name
                counter = 0
                while dest.exists():
                    counter += 1
                    dest = Path(tmpdir) / f"{Path(name).stem}_{counter}{ext}"
                dest.write_bytes(content)
                input_paths.append(dest)
            except Exception:
                continue

        # Pre-process: when 2+ images, upload to GCS, create input_images.csv, replace image inputs
        if len(input_paths) == len(input_infos):
            entries = list(zip(input_paths, input_infos))
            image_entries = [(p, i) for p, i in entries if Path(i["name"]).suffix.lower() in IMAGE_EXTENSIONS]
            other_entries = [(p, i) for p, i in entries if Path(i["name"]).suffix.lower() not in IMAGE_EXTENSIONS]
            if len(image_entries) >= 2:
                rows = []
                for path, info in image_entries:
                    try:
                        data = path.read_bytes()
                        content_type = _guess_content_type(info["name"]) or "image/jpeg"
                        blob_path = f"run_inputs/{run_id}/{info['name']}"
                        public_url = upload_image_from_bytes(data, blob_path, content_type)
                        rows.append({"image_name": info["name"], "image_url": public_url})
                    except Exception:
                        continue
                if rows:
                    csv_path = Path(tmpdir) / "input_images.csv"
                    with open(csv_path, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=["image_name", "image_url"])
                        writer.writeheader()
                        writer.writerows(rows)
                    csv_bytes = csv_path.read_bytes()
                    csv_gcs_uri = upload_to_haithem(
                        csv_bytes, f"{upload_prefix}/input_images.csv", "text/csv"
                    )
                    input_paths = [csv_path] + [p for p, _ in other_entries]
                    input_infos = [{"name": "input_images.csv", "gcs_uri": csv_gcs_uri}] + [
                        i for _, i in other_entries
                    ]

        # Detect validated_sample.csv and separate it from agent inputs
        example_output_path: Path | None = None
        clean_paths = []
        clean_infos = []
        for path, info in zip(input_paths, input_infos):
            if path.name == "validated_sample.csv":
                example_output_path = path
            else:
                clean_paths.append(path)
                clean_infos.append(info)
        input_paths = clean_paths
        input_infos = clean_infos

        # Slice CSV for sample_size or skip_rows
        if (sample_size > 0 or skip_rows > 0) and input_paths:
            for path in input_paths:
                if path.suffix.lower() == ".csv":
                    try:
                        import pandas as _pd
                        df = _pd.read_csv(path)
                        if sample_size > 0:
                            df = df.head(sample_size)
                        elif skip_rows > 0:
                            df = df.iloc[skip_rows:]
                        df.to_csv(path, index=False)
                    except Exception:
                        pass
                    break

        async def stream_with_cleanup():
            try:
                async for chunk in _run_agent_sse(
                    input_paths=input_paths,
                    output_columns=columns,
                    additional_instructions=additional_instructions or None,
                    model_name=model_name,
                    subagent_model_name=subagent_model_name or None,
                    run_id=run_id,
                    start_time=start_time,
                    input_infos=input_infos,
                    params=params,
                    example_output_path=example_output_path,
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
