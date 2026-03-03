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

load_dotenv()

URL_DELEGATION_THRESHOLD = 10


def process_data(
    input_files: Sequence[Path | str],
    output_columns: List[Dict[str, str]],
    additional_instructions: Optional[str] = None,
    model_name: str = "google_genai:gemini-3-flash-preview",
) -> tuple[pd.DataFrame, List[Dict[str, str]]]:
    logger.info("Starting data processing task")
    resolved_input_files: List[Path] = []
    current_dir = Path.cwd()
    for raw_path in input_files:
        source_path = Path(raw_path).expanduser()
        if not source_path.is_absolute():
            source_path = (current_dir / source_path).resolve()
        else:
            source_path = source_path.resolve()
        resolved_input_files.append(source_path)

    with tempfile.TemporaryDirectory() as workspace_root:
        original_cwd = os.getcwd()
        os.chdir(workspace_root)

        try:
            copied_files: List[str] = []

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
                    pass

            columns_info = "\n".join(
                [f"- {col['name']}: {col['description']}" for col in output_columns]
            )

            system_prompt = """You are a data processing agent. Your goal is to process input files and create a final CSV file named 'output.csv'.

General instructions:
- Read input files with pandas.
- Use PythonREPLTool for data manipulation and to save the final 'output.csv' in the current directory.
- Use Internet_search when web search is needed.
- Use Fetch_page_content first for most pages; use Fetch_HTML_from_URL when cleaned content is not enough.
- Keep tool-use explanations brief and practical.
- Use write_todos to track next actions when task complexity is high.
- Ensure 'output.csv' contains the required columns and is saved before ending.

Web fetching delegation policy (mandatory):
- When you have to retrieve information from similar urls, delegate the task to subagents. Only do the fetching once to ensure its feasibility. 
  1) fetch one representative URL yourself first to validate extraction logic,
  2) then delegate the remaining URL extraction workload to one or more task subagents,
  3) aggregate subagent outputs 
- For large batches, prefer parallel subagent calls with independent URL chunks.
"""

            initial_message = f"""Start processing the data now.

Input files available in your workspace:
{chr(10).join([f"- {name}" for name in copied_files])}

The 'output.csv' MUST have the following columns.
IMPORTANT: Each column description is a strict instruction for how to populate that column.
{columns_info}
"""

            if additional_instructions:
                initial_message += (
                    f"\nAdditional instructions:\n{additional_instructions}"
                )

            logger.info("Workspace ready with {} file(s)", len(copied_files))

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
            ]
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
            )

            logger.info("Invoking agent stream")
            seen_message_ids: set[str] = set()

            message_log = []
            for stream_mode, chunk in agent.stream(
                {"messages": [HumanMessage(content=initial_message)]},
                config={"configurable": {"thread_id": "data_proc_session"}},
                stream_mode=["updates", "values"],
            ):
                if stream_mode == "values":
                    message_log = chunk
                    continue

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

            output_path = Path(workspace_root) / "output.csv"
            if not output_path.exists():
                logger.error(
                    "output.csv not found. Workspace files: {}",
                    sorted(os.listdir(workspace_root)),
                )
                raise RuntimeError(
                    "Agent failed to produce 'output.csv'. Please check the agent's logic and inputs."
                )

            result_df = pd.read_csv(output_path)
            logger.info(
                "Agent completed: {} row(s), {} column(s), {} logged message(s)",
                len(result_df),
                len(result_df.columns),
                len(message_log),
            )
            return result_df, message_log
        finally:
            os.chdir(original_cwd)
