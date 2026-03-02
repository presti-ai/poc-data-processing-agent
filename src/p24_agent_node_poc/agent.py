import os
import tempfile
from typing import Dict, List, Optional, Union

import pandas as pd
from deepagents import create_deep_agent, SubAgent
from deepagents.backends.filesystem import FilesystemBackend
from dotenv import load_dotenv
from langchain_experimental.tools import PythonREPLTool
from loguru import logger

from p24_agent_node_poc.tools import fetch_html, internet_search

load_dotenv()


def process_data(
        inputs: List[Union[pd.DataFrame, str]],
        output_columns: List[Dict[str, str]],
        additional_instructions: Optional[str] = None,
        model_name: str = "google_genai:gemini-3-flash-preview",
) -> tuple[pd.DataFrame, List[Dict[str, str]]]:
    """
    Process input data using a Deep Agent and return a DataFrame.

    Args:
        inputs: A list of DataFrames or strings to be processed.
        output_columns: A list of dicts, each with 'name' and 'description' for output columns.
        additional_instructions: Optional additional help for the agent.
        model_name: The name of the model to use (default: "google_genai:gemini-3-flash-preview").

    Returns:
        A pandas DataFrame with the requested columns.
    """
    logger.info("Starting data processing task")
    # Create a temporary directory to act as the agent's workspace
    with tempfile.TemporaryDirectory() as workspace_root:
        logger.debug(f"Workspace root created at: {workspace_root}")
        # Change current working directory to workspace_root for PythonREPLTool
        original_cwd = os.getcwd()
        os.chdir(workspace_root)
        logger.debug(f"Changed CWD to: {workspace_root}")

        try:
            # Prepare inputs
            input_files_info = []
            for i, item in enumerate(inputs):
                if isinstance(item, pd.DataFrame):
                    filename = f"input_{i}.csv"
                    filepath = os.path.join(workspace_root, filename)
                    item.to_csv(filepath, index=False)
                    input_files_info.append(f"- {filename} (DataFrame input {i})")
                    logger.debug(f"Input DataFrame {i} saved as {filename}")
                elif isinstance(item, str):
                    filename = f"input_{i}.txt"
                    filepath = os.path.join(workspace_root, filename)
                    with open(filepath, "w") as f:
                        f.write(item)
                    input_files_info.append(f"- {filename} (String input {i})")
                    logger.debug(f"Input String {i} saved as {filename}")

            # Format output columns instructions
            columns_info = "\n".join([f"- {col['name']}: {col['description']}" for col in output_columns])

            # Prepare system prompt
            system_prompt = f"""You are a data processing agent. Your goal is to process the provided input files and create a final CSV file named 'output.csv'.

Input files available in your workspace:
{"\n".join(input_files_info)}

The 'output.csv' MUST have the following columns:
{columns_info}

Instructions for output:
- Read the input files using pandas.
- Process the data according to the column descriptions.
- Use the Python REPL tool to perform data manipulation and to save the final result as 'output.csv' in the current directory.
- Use the internet_search tool to perform web searches via research-agent.
- Use the fetch_html tool directly if you need to process HTML with your Python code.
- Use your write_todos tool to write a list of TODOs for the next steps.
- In your returned messages, explain what you are doing at each step.
- The final 'output.csv' should contain the processed data with the specified columns.
- Ensure that the final file is saved as 'output.csv'.
"""

            if additional_instructions:
                system_prompt += f"\n\nAdditional instructions:\n{additional_instructions}"

            # Initialize the agent with the specified backend and Python REPL tool
            # We set virtual_mode=False to allow the agent to work with the local temporary directory
            backend = FilesystemBackend(root_dir=workspace_root, virtual_mode=False)

            # research_subagent = SubAgent(
            #     name="research-agent",
            #     description="Used to research more in depth questions",
            #     system_prompt="You are a great researcher. Use internet_search to find information and fetch_html to get the raw HTML of specific pages if needed.",
            #     tools=[internet_search, fetch_html],
            # )
            #
            # html_fetcher_subagent = SubAgent(
            #     name="html-fetcher-agent",
            #     description="Used to answer questions by fetching the HTML of a specific URL. It is better for structured data extraction or finding information buried in HTML.",
            #     system_prompt="You are a HTML extraction specialist. Given a URL and a query, use fetch_html to retrieve the content and then extract the relevant information from the HTML to answer the query.",
            #     tools=[fetch_html],
            # )
            # subagents = [research_subagent, html_fetcher_subagent]

            logger.info(f"Creating deep agent with model: {model_name}")

            agent = create_deep_agent(
                model=model_name,
                tools=[PythonREPLTool(), fetch_html],
                system_prompt=system_prompt,
                backend=backend,
                # subagents=subagents
            )

            initial_message = "Start processing the data now. The input files are available for you to read."

            # Run the agent in streaming mode
            logger.info("Invoking agent in streaming mode...")
            seen_message_ids = set()
            result = {}
            for chunk in agent.stream(
                {"messages": [{"role": "user", "content": initial_message}]},
                config={"configurable": {"thread_id": "data_proc_session"}},
                stream_mode="values"
            ):
                result = chunk
                if "messages" in chunk:
                    for msg in chunk["messages"]:
                        msg_id = getattr(msg, "id", str(id(msg)))
                        if msg_id not in seen_message_ids:
                            seen_message_ids.add(msg_id)
                            role = getattr(msg, "type", "unknown") if not isinstance(msg, dict) else msg.get("role", "unknown")
                            content = getattr(msg, "content", "") if not isinstance(msg, dict) else msg.get("content", "")
                            
                            if content:
                                if role == "tool":
                                    tool_name = tc.get("name", "unknown")
                                    logger.info(f"[{role} - {tool_name}] {content[:100]}")
                                else:
                                    logger.info(f"[{role}] {content}")

                            # Log tool calls if present in the message
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    tool_name = tc.get("name", "unknown")
                                    args = str(tc.get("args", ""))
                                    summarized_args = (args[:20] + "...") if len(args) > 20 else args
                                    logger.info(f"   Tool Call: {tool_name} with args: {summarized_args}")

            logger.info("Agent invocation completed.")

            # After execution, check if output.csv exists in the workspace
            output_path = os.path.join(workspace_root, "output.csv")
            if os.path.exists(output_path):
                logger.info("Found output.csv, reading result...")
                return pd.read_csv(output_path), result
            else:
                # Log directory contents for debugging
                files = os.listdir(workspace_root)
                logger.error(f"output.csv not found in {workspace_root}. Files in workspace: {files}")
                raise RuntimeError("Agent failed to produce 'output.csv'. Please check the agent's logic and inputs.")
        finally:
            os.chdir(original_cwd)
            logger.debug(f"Restored CWD to: {original_cwd}")


