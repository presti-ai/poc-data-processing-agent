import os
import re
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
from deepagents import SubAgent, create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_experimental.tools import PythonREPLTool
from loguru import logger

from p24_agent_node_poc.tools import fetch_html, fetch_page_content, internet_search

load_dotenv()

URL_PATTERN = re.compile(r"https?://[^\s,;|\"'<>]+")
URL_DELEGATION_THRESHOLD = 10


def _extract_urls_from_text(raw_text: str) -> set[str]:
    return set(URL_PATTERN.findall(raw_text or ""))


def _extract_urls_from_dataframe(df: pd.DataFrame) -> set[str]:
    urls: set[str] = set()
    if df.empty:
        return urls
    for col in df.columns:
        for value in df[col].dropna().astype(str):
            urls.update(_extract_urls_from_text(value))
    return urls


def _extract_urls_from_uploaded_files(files: Optional[List[Tuple[str, bytes]]]) -> set[str]:
    urls: set[str] = set()
    if not files:
        return urls
    for _, raw_content in files:
        try:
            decoded = raw_content.decode("utf-8", errors="ignore")
        except Exception:
            continue
        urls.update(_extract_urls_from_text(decoded))
    return urls


def _extract_candidate_urls(
    combined_inputs: List[Union[pd.DataFrame, str]],
    files: Optional[List[Tuple[str, bytes]]],
) -> set[str]:
    urls: set[str] = set()
    for item in combined_inputs:
        if isinstance(item, pd.DataFrame):
            urls.update(_extract_urls_from_dataframe(item))
        elif isinstance(item, str):
            urls.update(_extract_urls_from_text(item))
    urls.update(_extract_urls_from_uploaded_files(files))
    return urls


def _coerce_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _get_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", msg.get("type", "unknown")))
    return str(getattr(msg, "type", "unknown"))


def _tool_calls_for_message(msg: Any) -> List[str]:
    tool_calls: Any = msg.get("tool_calls", []) if isinstance(msg, dict) else getattr(msg, "tool_calls", [])
    names: List[str] = []
    for call in tool_calls or []:
        if isinstance(call, dict):
            names.append(str(call.get("name", "unknown")))
        else:
            names.append(str(getattr(call, "name", "unknown")))
    return names


def _tool_name_for_tool_message(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("name", "unknown"))
    return str(getattr(msg, "name", "unknown"))


def _append_message_log(
    log: List[Dict[str, str]],
    seen: set[str],
    role: str,
    display: str,
    message_type: str = "text",
) -> None:
    normalized_display = display.strip() if isinstance(display, str) else str(display)
    signature = f"{role}|{message_type}|{normalized_display}"
    if signature in seen:
        return
    seen.add(signature)
    log.append(
        {
            "role": role,
            "type": message_type,
            "display": normalized_display or "(empty message)",
        }
    )


def _build_web_fetch_subagent() -> SubAgent:
    return {
        "name": "web_fetch_batch_worker",
        "description": (
            "Use proactively for URL-heavy web extraction tasks. "
            "Ideal when processing more than 10 URLs, so the main agent keeps a small context."
        ),
        "system_prompt": (
            "You are a sub-agent specialized in web fetching for CSV enrichment.\n"
            "Rules:\n"
            "- Focus on the URLs assigned in the task instructions.\n"
            "- Use fetch tools to collect the required fields.\n"
            "- Return only concise, structured rows that can be merged into output.csv.\n"
            "- Do not include long reasoning, only the extracted results and short notes for missing fields."
        ),
    }


def process_data(
    inputs: Optional[List[Union[pd.DataFrame, str]]],
    output_columns: List[Dict[str, str]],
    additional_instructions: Optional[str] = None,
    model_name: str = "google_genai:gemini-3-flash-preview",
    main_dataset: Optional[pd.DataFrame] = None,
    files: Optional[List[Tuple[str, bytes]]] = None,
) -> tuple[pd.DataFrame, List[Dict[str, str]]]:
    """
    Process input data using a Deep Agent and return a DataFrame plus a structured message log.
    """
    logger.info("Starting data processing task")
    with tempfile.TemporaryDirectory() as workspace_root:
        logger.debug(f"Workspace root created at: {workspace_root}")
        original_cwd = os.getcwd()
        os.chdir(workspace_root)
        logger.debug(f"Changed CWD to: {workspace_root}")

        try:
            input_files_info: List[str] = []
            combined_inputs: List[Union[pd.DataFrame, str]] = []

            if main_dataset is not None:
                combined_inputs.append(main_dataset)
            if inputs:
                combined_inputs.extend(inputs)

            detected_urls = _extract_candidate_urls(combined_inputs, files)
            detected_url_count = len(detected_urls)

            for i, item in enumerate(combined_inputs):
                if isinstance(item, pd.DataFrame):
                    filename = f"input_{i}.csv"
                    filepath = os.path.join(workspace_root, filename)
                    item.to_csv(filepath, index=False)
                    input_files_info.append(f"- {filename} (DataFrame input {i})")
                    logger.debug(f"Input DataFrame {i} saved as {filename}")
                elif isinstance(item, str):
                    filename = f"input_{i}.txt"
                    filepath = os.path.join(workspace_root, filename)
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(item)
                    input_files_info.append(f"- {filename} (String input {i})")
                    logger.debug(f"Input String {i} saved as {filename}")

            if files:
                for original_name, content in files:
                    safe_name = os.path.basename(original_name) or "uploaded_file"
                    base, ext = os.path.splitext(safe_name)
                    candidate_name = safe_name
                    target_path = os.path.join(workspace_root, candidate_name)
                    counter = 1
                    while os.path.exists(target_path):
                        candidate_name = f"{base}_{counter}{ext}"
                        target_path = os.path.join(workspace_root, candidate_name)
                        counter += 1

                    with open(target_path, "wb") as f:
                        f.write(content)

                    input_files_info.append(f"- {candidate_name} (Uploaded file)")
                    logger.debug(f"Uploaded file saved as {candidate_name}")

            columns_info = "\n".join([f"- {col['name']}: {col['description']}" for col in output_columns])

            system_prompt = f"""You are a data processing agent. Your goal is to process input files and create a final CSV file named 'output.csv'.

General instructions:
- Read input files with pandas.
- Use PythonREPLTool for data manipulation and to save the final 'output.csv' in the current directory.
- Use Internet_search when web search is needed.
- Use Fetch_page_content first for most pages; use Fetch_HTML_from_URL when cleaned content is not enough.
- Keep tool-use explanations brief and practical.
- Use write_todos to track next actions when task complexity is high.
- Ensure 'output.csv' contains the required columns and is saved before ending.

Web fetching delegation policy (mandatory):
- URL delegation threshold = {URL_DELEGATION_THRESHOLD}.
- If candidate URL count is <= {URL_DELEGATION_THRESHOLD}, fetch directly in the main agent and do not delegate URL extraction to task subagents.
- If candidate URL count is > {URL_DELEGATION_THRESHOLD}:
  1) fetch one representative URL yourself first to validate extraction logic,
  2) then delegate the remaining URL extraction workload to one or more task subagents,
  3) aggregate subagent outputs into final output.csv.
- For large batches, prefer parallel subagent calls with independent URL chunks.
"""

            initial_message = f"""Start processing the data now.

Input files available in your workspace:
{"\n".join(input_files_info)}

Detected URL candidates in provided inputs: {detected_url_count}
URL delegation threshold: {URL_DELEGATION_THRESHOLD}

The 'output.csv' MUST have the following columns.
IMPORTANT: Each column description is a strict instruction for how to populate that column.
{columns_info}
"""

            if additional_instructions:
                initial_message += f"\nAdditional instructions:\n{additional_instructions}"

            backend = FilesystemBackend(root_dir=workspace_root, virtual_mode=False)
            subagents: List[SubAgent] = [_build_web_fetch_subagent()]

            logger.info(f"Creating deep agent with model: {model_name}")
            agent = create_deep_agent(
                model=model_name,
                tools=[PythonREPLTool(), internet_search, fetch_page_content, fetch_html],
                system_prompt=system_prompt,
                backend=backend,
                subagents=subagents,
            )

            logger.info("Invoking agent in streaming mode...")
            message_log: List[Dict[str, str]] = []
            seen_signatures: set[str] = set()
            _append_message_log(message_log, seen_signatures, "system", system_prompt)
            _append_message_log(message_log, seen_signatures, "human", initial_message)

            for chunk in agent.stream(
                {"messages": [HumanMessage(content=initial_message)]},
                config={"configurable": {"thread_id": "data_proc_session"}},
                stream_mode="values",
            ):
                if "messages" not in chunk:
                    continue
                for msg in chunk["messages"]:
                    role = _get_role(msg)
                    content = _coerce_text(msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", ""))
                    tool_call_names = _tool_calls_for_message(msg)

                    if role == "tool":
                        tool_name = _tool_name_for_tool_message(msg)
                        _append_message_log(message_log, seen_signatures, role, tool_name, "tool")
                        logger.info(f"[tool] {tool_name}")
                        continue

                    if content.strip():
                        _append_message_log(message_log, seen_signatures, role, content, "text")
                        logger.info(f"[{role}] {content[:120]}")
                    elif tool_call_names:
                        _append_message_log(
                            message_log,
                            seen_signatures,
                            role,
                            ", ".join(tool_call_names),
                            "tool_call",
                        )
                        logger.info(f"[{role} tool_call] {', '.join(tool_call_names)}")

            logger.info("Agent invocation completed.")

            output_path = os.path.join(workspace_root, "output.csv")
            if os.path.exists(output_path):
                logger.info("Found output.csv, reading result...")
                return pd.read_csv(output_path), message_log

            local_files = os.listdir(workspace_root)
            logger.error(f"output.csv not found in {workspace_root}. Files in workspace: {local_files}")
            raise RuntimeError("Agent failed to produce 'output.csv'. Please check the agent's logic and inputs.")
        finally:
            os.chdir(original_cwd)
            logger.debug(f"Restored CWD to: {original_cwd}")

