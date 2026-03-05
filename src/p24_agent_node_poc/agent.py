"""
Core agent module: orchestrates the LLM-based data processing pipeline.

Creates an isolated workspace, copies input files, invokes the deep agent with
tools (Python REPL, web search, page fetching), and returns the produced output.csv.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd
from deepagents import SubAgent, create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    messages_to_dict,
    ToolMessage,
)
from langchain_experimental.tools import PythonREPLTool
from loguru import logger

from p24_agent_node_poc.tools import fetch_html, fetch_page_content, internet_search

load_dotenv()  # Load API keys from .env (TAVILY_API_KEY, etc.)

URL_DELEGATION_THRESHOLD = 10  # Threshold for delegating URL fetching to subagents


def process_data(
    input_files: Sequence[Path | str],
    output_columns: List[Dict[str, str]],
    additional_instructions: Optional[str] = None,
    example_output_path: Optional[Path | str] = None,
    model_name: str = "google_genai:gemini-3-pro-preview",
) -> tuple[pd.DataFrame, List[Dict[str, str]]]:
    """
    Main entry point: process input CSVs and produce output.csv with the requested columns.
    Optionally accepts a validated_sample.csv (example_output_path) to guide the agent.
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

    # Create isolated temp workspace; agent works inside it and produces output.csv
    with tempfile.TemporaryDirectory() as workspace_root:
        original_cwd = os.getcwd()
        os.chdir(workspace_root)  # Agent runs in workspace so paths resolve correctly

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

            # System prompt: tells the agent its role, tools usage, and delegation policy
            system_prompt = """You are a data processing agent. Your goal is to process input files and create a final CSV file named 'output.csv'.

General instructions:
- Read input files with pandas.
- Use PythonREPLTool for data manipulation and to save the final 'output.csv' in the current directory.
- Use Internet_search when web search is needed.
- Use Fetch_page_content first for most pages; use Fetch_HTML_from_URL when cleaned content is not enough.
- Keep tool-use explanations brief and practical.
- Use write_todos to track next actions when task complexity is high.
- Ensure 'output.csv' contains the required columns and is saved before ending.
- Before sending the final 'output.csv', ensure all urls in the file exist and are accessible (i.e. not 404).

Web fetching delegation policy (mandatory):
- When you have to retrieve information from similar urls, delegate the task to subagents. Only do the fetching once to ensure its feasibility. 
  1) fetch one representative URL yourself first to validate extraction logic,
  2) then delegate the remaining URL extraction workload to one or more task subagents,
  3) aggregate subagent outputs 
- For large batches, prefer parallel subagent calls with independent URL chunks.
"""

            # Initial user message: lists workspace files and required output columns
            initial_message = f"""Start processing the data now.

Input files available in your workspace:
{chr(10).join([f"- {name}" for name in copied_files])}

The 'output.csv' MUST have the following columns.
IMPORTANT: Each column description is a strict instruction for how to populate that column.
{columns_info}
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

            # DeepAgents: main agent + subagent for URL batch fetching (reduces context size)
            backend = FilesystemBackend(root_dir=workspace_root, virtual_mode=False)
            subagents = [
                SubAgent(
                    name="web_fetch_batch_worker",
                    description=(
                        "Use proactively for URL-heavy web extraction tasks. Ideal when processing more than 10 URLs, so the main agent keeps a small context."
                    ),
                    system_prompt=(
                        "You are a sub-agent specialized in web fetching for CSV enrichment. Focus on the assigned URLs and return concise structured results."
                    ),
                    tools=[fetch_html],
                ),
            ]  # Subagent handles heavy URL extraction; main agent delegates and aggregates
            agent = create_deep_agent(
                model=model_name,
                tools=[
                    PythonREPLTool(),
                    internet_search,
                    fetch_page_content,
                    fetch_html,
                ],
                system_prompt=system_prompt,
                backend=backend,
                subagents=subagents,
            )  # PythonREPL, search, fetch_page_content, fetch_html

            logger.info("Invoking agent stream")
            message_log = []
            # Stream agent responses; capture final state and log model/tool activity
            for stream_mode, chunk in agent.stream(
                {"messages": [HumanMessage(content=initial_message)]},
                config={"configurable": {"thread_id": "data_proc_session"}},
                stream_mode=["updates", "values"],
            ):
                # "values" = full state snapshot; "updates" = incremental model/tool output
                if stream_mode == "values":
                    message_log = chunk  # Keep latest state for UI display
                    continue

                # Log model reasoning and tool calls for debugging/transparency
                if not chunk.get("model") and not chunk.get("tools"):
                    logger.debug("Received chunk: {}", chunk)

                if model_chunk := chunk.get("model"):
                    for message in model_chunk.get("messages", []):
                        message: AIMessage
                        if message.content:
                            if isinstance(message.content, str):
                                logger.info("Model - {}", message.content)
                            elif (
                                isinstance(message.content, list)
                                and message.content[0]["type"] == "text"
                            ):
                                logger.info("Model - {}", message.content[0]["text"])
                        if message.tool_calls:
                            for tool_call in message.tool_calls:
                                tool_call: dict
                                logger.info("Model - Tool call: {}", tool_call["name"])
                if tool_chunk := chunk.get("tools"):
                    for message in tool_chunk.get("messages", []):
                        message: ToolMessage
                        if message.content:
                            logger.info(
                                "Tool {} - {}...", message.name, str(message.content)[:50]
                            )

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

            result_df = pd.read_csv(output_path)  # Return parsed CSV + message log for UI
            logger.info(
                "Agent completed: {} row(s), {} column(s), {} logged message(s)",
                len(result_df),
                len(result_df.columns),
                len(message_log),
            )
            return result_df, message_log
        finally:
            os.chdir(original_cwd)  # Restore cwd even on error


def process_data_two_phase(
    input_path: Path,
    output_columns: List[Dict[str, str]],
    additional_instructions: Optional[str],
    model_name: str = "google_genai:gemini-3-pro-preview",
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
            phase1_df, phase1_messages = process_data(  # Single run on sample
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
        phase2_df, phase2_messages = process_data(  # Run with example_output_path
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
