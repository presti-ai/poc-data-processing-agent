"""
Core agent module: orchestrates the LLM-based data processing pipeline.

Creates an isolated workspace, copies input files, invokes the deep agent with
tools (Python REPL, web search, page fetching), and returns the produced output.csv.
"""

import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, TextIO

import pandas as pd
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_experimental.tools import PythonREPLTool
from loguru import logger

from agent_constants import RATE_LIMIT_RETRIES, RATE_LIMIT_WAIT, subagents, SYSTEM_PROMPT, tools
from agent_logging import _debug_log, _serialize_chunk_for_sse
from p24_agent_node_poc.image_migration import migrate_image_urls_in_dataframe
from p24_agent_node_poc.tools import (
    fetch_html,
    fetch_page_content,
    fetch_wayback_page,
    internet_search,
    upload_file_gcs,
)

load_dotenv()  # Load API keys from .env (TAVILY_API_KEY, etc.)

# Log file and data dirs in project root (derived from this module's location) so they're consistent regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEBUG_LOG_PATH = _PROJECT_ROOT / "log.txt"
DATA_INPUT_DIR = _PROJECT_ROOT / "data" / "input"
DATA_OUTPUT_DIR = _PROJECT_ROOT / "data" / "output"


def process_data(
    input_files: Sequence[Path | str],
    output_columns: List[Dict[str, str]],
    additional_instructions: Optional[str] = None,
    example_output_path: Optional[Path | str] = None,
    model_name: str = "anthropic:claude-opus-4-6",
    save_output_dir: Optional[Path | str] = None,
    on_stream_chunk: Optional[Callable[[str, dict], None]] = None,
) -> tuple[pd.DataFrame, List[Dict[str, str]]]:
    """
    Main entry point: process input CSVs and produce output.csv with the requested columns.
    Optionally accepts a validated_sample.csv (example_output_path) to guide the agent.
    When save_output_dir is None, saves output to data/output/ with a timestamped filename.
    """
    logger.info("Starting data processing task")

    # Resolve all input paths to absolute paths (handle ~ and relative paths)
    resolved_input_files: List[Path] = []
    current_dir = Path.cwd()
    for raw_path in input_files:
        source_path = Path(raw_path).expanduser()
        if not source_path.is_absolute():
            source_path = (current_dir / source_path).resolve()
        else:
            source_path = source_path.resolve()
        resolved_input_files.append(source_path)

    # Generate run timestamp for pairing input/output saves
    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # Save input files to data/input/ before run
    DATA_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved_input_paths: List[Path] = []
    for i, source_path in enumerate(resolved_input_files):
        if source_path.exists() and source_path.is_file():
            ext = source_path.suffix or ".csv"
            dest_name = f"input_{run_timestamp}_{i}{ext}"
            dest_path = DATA_INPUT_DIR / dest_name
            shutil.copy2(source_path, dest_path)
            saved_input_paths.append(dest_path)
    if saved_input_paths:
        logger.info("Inputs saved to {}", [str(p) for p in saved_input_paths])

    # Create isolated temp workspace; agent works inside it and produces output.csv
    with tempfile.TemporaryDirectory() as workspace_root:
        original_cwd = os.getcwd()
        os.chdir(workspace_root)  # Agent runs in workspace so paths resolve correctly

        # Open debug log file (append mode so multi-run / two-phase runs accumulate)
        log_path = DEBUG_LOG_PATH
        debug_file: Optional[TextIO] = None
        loguru_sink_id: Optional[int] = None
        try:
            debug_file = open(log_path, "a", encoding="utf-8")
            loguru_sink_id = logger.add(
                log_path,
                mode="a",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
            )
            _debug_log(
                debug_file,
                f"RUN START @ {datetime.now().isoformat()}",
                f"model={model_name}\nsubagent_model=genai:gemini-3-flash-preview\n"
                f"input_files={[str(p) for p in resolved_input_files]}\n"
                f"example_output_path={example_output_path}\n"
                f"workspace={workspace_root}",
                truncate=False,
            )
        except OSError as e:
            logger.warning("Could not open debug log file: {}", e)

        try:
            copied_files: List[str] = []

            # Copy each input file into workspace (avoid name clashes with _1, _2, etc.)
            for i, source_path in enumerate(resolved_input_files):
                if not source_path.exists() or not source_path.is_file():
                    raise FileNotFoundError(
                        f"Input file not found or not a file: {source_path}"
                    )

                candidate_name = source_path.name or f"input_{i}"
                destination_path = Path(workspace_root) / candidate_name
                counter = 1
                while destination_path.exists():
                    destination_path = (
                        Path(workspace_root)
                        / f"{source_path.stem}_{counter}{source_path.suffix}"
                    )
                    counter += 1

                shutil.copy2(source_path, destination_path)
                copied_files.append(destination_path.name)

                try:
                    content = destination_path.read_text(
                        encoding="utf-8", errors="ignore"
                    )
                except Exception:
                    pass  # Non-text files: ignore read errors

            # Two-phase scaling: add validated sample as reference for the agent
            if example_output_path:
                ex_path = Path(example_output_path).expanduser().resolve()
                if not ex_path.is_absolute():
                    ex_path = (current_dir / ex_path).resolve()
                if ex_path.exists() and ex_path.is_file():
                    dest = Path(workspace_root) / "validated_sample.csv"
                    shutil.copy2(ex_path, dest)
                    copied_files.append("validated_sample.csv")

            # Build column spec string for the prompt (name + description per column)
            columns_info = "\n".join(
                [f"- {col['name']}: {col['description']}" for col in output_columns]
            )

            # Initial user message: lists workspace files; include column spec only when columns are defined
            if output_columns:
                initial_message = f"""Start processing the data now.

Input files available in your workspace:
{chr(10).join([f"- {name}" for name in copied_files])}

The 'output.csv' MUST have the following columns.
IMPORTANT: Each column description is a strict instruction for how to populate that column.
{columns_info}
"""
            else:
                initial_message = f"""Start processing the data now.

Input files available in your workspace:
{chr(10).join([f"- {name}" for name in copied_files])}

Create output.csv based on the input files. Infer the structure and content from the data and any additional instructions below.
"""

            # Append optional user instructions (e.g. extraction rules for a use case)
            if additional_instructions:
                initial_message += (
                    f"\nAdditional instructions:\n{additional_instructions}"
                )

            # Two-phase: tell agent to use validated_sample.csv as format reference
            if example_output_path:
                initial_message += """

REFERENCE OUTPUT: The file 'validated_sample.csv' contains validated output from a prior run on a subset of data.
Use it as a strict reference for column format, extraction logic, and URL structure. Process the remaining input files accordingly.
"""

            logger.info("Workspace ready with {} file(s)", len(copied_files))

            # Write full prompts and workspace info to debug log
            if debug_file:
                _debug_log(
                    debug_file,
                    "COPIED FILES IN WORKSPACE",
                    copied_files,
                    truncate=False,
                )
                _debug_log(
                    debug_file,
                    "SYSTEM PROMPT (sent to main agent)",
                    SYSTEM_PROMPT,
                    truncate=False,
                )
                _debug_log(
                    debug_file,
                    "INITIAL MESSAGE (sent to main agent)",
                    initial_message,
                    truncate=False,
                )

            # DeepAgents: main agent + subagent for URL batch fetching (reduces context size)
            backend = FilesystemBackend(root_dir=workspace_root, virtual_mode=True)
            agent = create_deep_agent(
                model=model_name,
                tools=tools,
                system_prompt=SYSTEM_PROMPT,
                backend=backend,
                subagents=subagents,
            )

            logger.info("Invoking agent stream")
            message_log = []

            for attempt in range(RATE_LIMIT_RETRIES):
                try:
                    # Stream agent responses; capture final state and log model/tool activity
                    messages = [HumanMessage(content=initial_message)]
                    for stream_mode, chunk in agent.stream(
                        {"messages": messages},
                        config={"configurable": {"thread_id": "data_proc_session"}},
                        stream_mode=["updates", "values"],
                    ):
                        # "values" = full state snapshot; "updates" = incremental model/tool output
                        # stream_mode can be a tuple for namespaced events (e.g. subagent streams)
                        if stream_mode == "values" or stream_mode == ("values",):
                            message_log = chunk  # Keep latest state for UI display
                            continue

                        if on_stream_chunk and stream_mode in ("updates", ("updates",)):
                            payload = _serialize_chunk_for_sse(chunk)
                            if payload:
                                on_stream_chunk(str(stream_mode), payload)

                        if debug_file and stream_mode not in ("updates", ("updates",)):
                            _debug_log(
                                debug_file,
                                f"STREAM MODE (may indicate subagent): {stream_mode}",
                                list(chunk.keys())
                                if isinstance(chunk, dict)
                                else str(chunk)[:500],
                                truncate=False,
                            )

                        # Log model reasoning and tool calls for debugging/transparency
                        if not chunk.get("model") and not chunk.get("tools"):
                            logger.debug("Received chunk: {}", chunk)
                            if debug_file and chunk:
                                _debug_log(
                                    debug_file,
                                    "STREAM CHUNK (other)",
                                    {k: str(v)[:500] for k, v in chunk.items()},
                                    truncate=False,
                                )

                        if model_chunk := chunk.get("model"):
                            for msg in model_chunk.get("messages", []):
                                msg: AIMessage
                                if msg.content:
                                    text = (
                                        msg.content
                                        if isinstance(msg.content, str)
                                        else (
                                            msg.content[0].get("text", str(msg.content))
                                            if msg.content
                                            else ""
                                        )
                                    )
                                    logger.info(
                                        "Model - {}",
                                        text[:100] + "..."
                                        if len(str(text)) > 100
                                        else text,
                                    )
                                    if debug_file:
                                        _debug_log(
                                            debug_file, "MAIN AGENT (AI message)", text
                                        )
                                if msg.tool_calls:
                                    for tc in msg.tool_calls:
                                        tc: dict
                                        logger.info(
                                            "Model - Tool call: {}", tc.get("name", "?")
                                        )
                                        if debug_file:
                                            _debug_log(
                                                debug_file,
                                                f"MAIN AGENT -> TOOL CALL: {tc.get('name', '?')}",
                                                {
                                                    "args": tc.get("args", {}),
                                                    "id": tc.get("id"),
                                                },
                                                truncate=False,
                                            )
                        if tool_chunk := chunk.get("tools"):
                            for msg in tool_chunk.get("messages", []):
                                msg: ToolMessage
                                logger.info(
                                    "Tool {} - {}...", msg.name, str(msg.content)[:50]
                                )
                                if debug_file:
                                    _debug_log(
                                        debug_file,
                                        f"TOOL RESULT: {msg.name}",
                                        msg.content,
                                    )
                        if on_stream_chunk and stream_mode in ("updates", ("updates",)):
                            payload = _serialize_chunk_for_sse(chunk)
                            if payload:
                                on_stream_chunk(str(stream_mode), payload)
                    break  # Success, exit retry loop
                except Exception as e:
                    err_str = str(e).lower()
                    if attempt < RATE_LIMIT_RETRIES - 1 and (
                        "429" in err_str or "rate_limit" in err_str
                    ):
                        wait = RATE_LIMIT_WAIT
                        if on_stream_chunk:
                            on_stream_chunk(
                                "retry",
                                {
                                    "message": f"Rate limit (429), waiting {wait}s before retry {attempt + 2}/{RATE_LIMIT_RETRIES}"
                                },
                            )
                        logger.warning(
                            "Rate limit (429), waiting {}s before retry {}/{}",
                            wait,
                            attempt + 2,
                            RATE_LIMIT_RETRIES,
                        )
                        if on_stream_chunk:
                            on_stream_chunk(
                                "retry",
                                {
                                    "message": f"Rate limit (429), waiting {wait}s before retry {attempt + 2}/{RATE_LIMIT_RETRIES}"
                                },
                            )
                        time.sleep(wait)
                    else:
                        raise

            # Agent must produce output.csv; fail if missing
            output_path = Path(workspace_root) / "output.csv"
            if not output_path.exists():
                logger.error(
                    "output.csv not found. Workspace files: {}",
                    sorted(os.listdir(workspace_root)),
                )
                raise RuntimeError(
                    "Agent failed to produce 'output.csv'. Please check the agent's logic and inputs."
                )

            result_df = pd.read_csv(
                output_path
            )  # Return parsed CSV + message log for UI
            result_df = migrate_image_urls_in_dataframe(result_df)
            logger.info("Migrated image URLs to GCS")
            logger.info(
                "Agent completed: {} row(s), {} column(s), {} logged message(s)",
                len(result_df),
                len(result_df.columns),
                len(message_log),
            )

            # Save output to data/output/ with same timestamp as inputs
            out_dir = (
                Path(save_output_dir).expanduser().resolve()
                if save_output_dir
                else DATA_OUTPUT_DIR
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            saved_path = out_dir / f"output_{run_timestamp}.csv"
            result_df.to_csv(saved_path, index=False)
            logger.info("Output saved to {}", saved_path)

            if debug_file:
                _debug_log(
                    debug_file,
                    "RUN COMPLETE",
                    f"rows={len(result_df)}, cols={len(result_df.columns)}, messages={len(message_log)}, saved_to={saved_path}",
                    truncate=False,
                )
            return result_df, message_log
        finally:
            if loguru_sink_id is not None:
                try:
                    logger.remove(loguru_sink_id)
                except ValueError:
                    pass
            if debug_file:
                try:
                    debug_file.close()
                except OSError:
                    pass
            os.chdir(original_cwd)  # Restore cwd even on error


def process_data_two_phase(
    input_path: Path,
    output_columns: List[Dict[str, str]],
    additional_instructions: Optional[str],
    model_name: str = "anthropic:claude-opus-4-6",
    sample_size: int = 5,
    validated_phase1_df: Optional[pd.DataFrame] = None,
) -> tuple[
    Optional[pd.DataFrame],
    Optional[pd.DataFrame],
    List,
    List,
]:
    """
    Two-phase processing for scaling: Phase 1 runs on first N rows; Phase 2 runs on
    remaining rows using validated Phase 1 output as reference context.

    When validated_phase1_df is None: run Phase 1 only. Returns (phase1_df, None, msgs, []).
    When validated_phase1_df is provided: run Phase 2 only. Returns (None, phase2_df, [], msgs).
    """
    # Ensure input exists
    input_path = Path(input_path).expanduser().resolve()
    if not input_path.exists() or not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    full_df = pd.read_csv(input_path)

    # Phase 1: process first N rows, return sample output
    if validated_phase1_df is None:
        sample_df = full_df.head(sample_size)  # First 5 rows
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            sample_df.to_csv(f, index=False)
            sample_path = Path(f.name)
        try:
            phase1_df, phase1_messages = process_data(
                input_files=[sample_path],
                output_columns=output_columns,
                additional_instructions=additional_instructions,
                model_name=model_name,
            )
            return phase1_df, None, phase1_messages, []
        finally:
            sample_path.unlink(missing_ok=True)  # Cleanup temp file

    # Phase 2: process remaining rows with validated sample as reference
    remaining_df = full_df.iloc[sample_size:]
    if remaining_df.empty:  # Input had <= sample_size rows
        return None, pd.DataFrame(), [], []

    # Write remaining rows and validated sample to temp files for process_data
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f_rem:
        remaining_df.to_csv(f_rem, index=False)
        remaining_path = Path(f_rem.name)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f_val:
        validated_phase1_df.to_csv(f_val, index=False)
        validated_path = Path(f_val.name)

    try:
        phase2_df, phase2_messages = process_data(
            input_files=[remaining_path],
            output_columns=output_columns,
            additional_instructions=additional_instructions,
            example_output_path=validated_path,
            model_name=model_name,
        )
        return None, phase2_df, [], phase2_messages
    finally:
        remaining_path.unlink(missing_ok=True)  # Cleanup temp files
        validated_path.unlink(missing_ok=True)
