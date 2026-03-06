"""
FastAPI server for the P24 data processing agent.
Serves the frontend and provides /api/run for agent execution with SSE streaming.
"""

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from queue import Empty, Queue
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from p24_agent_node_poc.agent import process_data

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


@app.post("/api/run")
async def api_run(request: Request):
    """Run the agent with uploaded files. Returns SSE stream of progress and result."""
    form = await request.form()
    files = form.getlist("files")
    output_columns = form.get("output_columns", "[]")
    additional_instructions = form.get("additional_instructions", "") or ""
    model_name = form.get("model_name", "anthropic:claude-opus-4-6") or "anthropic:claude-opus-4-6"
    subagent_model_name = form.get("subagent_model_name", "openai:gpt-5.4") or "openai:gpt-5.4"

    if not files:
        return JSONResponse(
            status_code=400,
            content={"error": "Please upload at least one file."},
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
        input_paths = []
        for i, f in enumerate(files):
            dest = Path(tmpdir) / (f.filename or f"input_{i}.csv")
            content = await f.read()
            dest.write_bytes(content)
            input_paths.append(dest)

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
