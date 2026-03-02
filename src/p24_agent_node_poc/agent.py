import os
import tempfile
from typing import Dict, List, Literal, Optional, Union

import pandas as pd
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from dotenv import load_dotenv
from langchain_experimental.tools import PythonREPLTool
from tavily import TavilyClient

load_dotenv()

tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def internet_search(
        query: str,
        max_results: int = 5,
        topic: Literal["general", "news", "finance"] = "general",
        include_raw_content: bool = False,
):
    """Run a web search"""
    return tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )


def process_data(
        inputs: List[Union[pd.DataFrame, str]],
        output_columns: List[Dict[str, str]],
        additional_instructions: Optional[str] = None,
        model_name: str = "google_genai:gemini-3-flash-preview",
) -> pd.DataFrame:
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
    # Create a temporary directory to act as the agent's workspace
    with tempfile.TemporaryDirectory() as workspace_root:
        # Prepare inputs
        input_files_info = []
        for i, item in enumerate(inputs):
            if isinstance(item, pd.DataFrame):
                filename = f"input_{i}.csv"
                filepath = os.path.join(workspace_root, filename)
                item.to_csv(filepath, index=False)
                input_files_info.append(f"- {filename} (DataFrame input {i})")
            elif isinstance(item, str):
                filename = f"input_{i}.txt"
                filepath = os.path.join(workspace_root, filename)
                with open(filepath, "w") as f:
                    f.write(item)
                input_files_info.append(f"- {filename} (String input {i})")

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
- The final 'output.csv' should contain the processed data with the specified columns.
- Ensure that the final file is saved as 'output.csv'.
"""

        if additional_instructions:
            system_prompt += f"\n\nAdditional instructions:\n{additional_instructions}"

        # Initialize the agent with the specified backend and Python REPL tool
        # We set virtual_mode=False to allow the agent to work with the local temporary directory
        backend = FilesystemBackend(root_dir=workspace_root, virtual_mode=False)

        agent = create_deep_agent(
            model=model_name,
            tools=[PythonREPLTool(), internet_search],
            system_prompt=system_prompt,
            backend=backend
        )

        initial_message = "Start processing the data now. The input files are available for you to read."

        # Run the agent
        # We use a one-off run with a thread_id
        agent.invoke(
            {"messages": [{"role": "user", "content": initial_message}]},
            config={"configurable": {"thread_id": "data_proc_session"}}
        )

        # After execution, check if output.csv exists in the workspace
        output_path = os.path.join(workspace_root, "output.csv")
        if os.path.exists(output_path):
            return pd.read_csv(output_path)
        else:
            raise RuntimeError("Agent failed to produce 'output.csv'. Please check the agent's logic and inputs.")


if __name__ == '__main__':
    df1 = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    _inputs = [df1]

    _output_columns = [
        {"name": "sum_A_B", "description": "The sum of column A and B"},
        {"name": "is_even", "description": "True if sum_A_B is even, False otherwise"}
    ]

    process_data(_inputs, _output_columns)
