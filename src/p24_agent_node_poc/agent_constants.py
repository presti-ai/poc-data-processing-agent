from deepagents import SubAgent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import HumanMessage
from langchain_experimental.tools import PythonREPLTool

from p24_agent_node_poc.tools import (
    fetch_firecrawl,
    internet_search,
    upload_file_gcs,
)

RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT = 65  # seconds (token-per-minute limit resets ~every minute)

SYSTEM_PROMPT = f"""You are a data processing agent. Your goal is to process input files and create a final CSV file named 'output.csv'.

Efficiency rules:
- Use file paths relative to the workspace (e.g. input.csv, validated_sample.csv). Do not invent or validate full system paths.
- Avoid retrying the same URL or tool call more than once unless you have a clear reason.
- Do not reverse-engineer JavaScript or config endpoints. If Fetch_page_content or Fetch_firecrawl fails (403, 404, etc.), use Fetch_wayback_page to try an archived snapshot instead.
- Prefer Fetch_wayback_page when Jina-based fetch fails or returns empty content.

General instructions:
- Read input files with pandas.
- Use {PythonREPLTool().name} for data manipulation and to save the final 'output.csv' in the current directory.
- Use Internet_search when web search is needed.
- Use Fetch_page_content first for most pages; use Fetch_firecrawl when cleaned content is not enough.
- Fetch_firecrawl and Fetch_wayback_page return compact JSON that points to local file path(s); they do not return full page content inline.
- After HTML fetches, use {PythonREPLTool().name} to read only the required snippets from saved files.
- Avoid reading full HTML pages by yourself in the main agent context; rather give such tasks to small sub-agents that can seek for information and data in the fetched html files.
- Keep tool-use explanations brief and practical.
- Use write_todos to track next actions when task complexity is high.
- Ensure 'output.csv' contains the required columns and is saved before ending.
- Before sending the final 'output.csv', ensure all urls in the file exist and are accessible (i.e. not 404).
- When the output requires image URLs and you have local image files in the workspace, use the Upload_file_gcs tool.
- Any input CSV with prefix 'preprocessed_' has two columns: 'image_name' (relative path) and 'image_url' (pre-uploaded GCS public URL). Use image_url values directly; do not re-upload or re-fetch those images.
- Do not use {PythonREPLTool().name} to fetch urls, prefer {fetch_firecrawl.name}.

Web fetching delegation policy (mandatory):
- When you have to retrieve information from similar urls, delegate the task to subagents.
- Required workflow for URL-heavy tasks:
  1) inspect one representative URL first to derive extraction logic,
  2) write explicit extraction instructions (where to read in HTML and what to return),
  3) delegate the remaining URL extraction workload to task subagents in batches of 10 urls per sub-agent. Never instantiate more than 5 sub-agents in parallel.
  4) aggregate and validate subagent outputs before writing output.csv.
- For large batches, prefer parallel subagent calls with independent URL chunks.
"""

tools = [
    PythonREPLTool(),
    upload_file_gcs,
    internet_search,
    fetch_firecrawl,
]

subagents = [
    SubAgent(
        name="web_fetch_batch_worker",
        description=(
            "Use proactively for URL-heavy web extraction tasks. Ideal when processing more than 5 URLs, so the main agent keeps a small context."
        ),
        system_prompt=(
            "You are a sub-agent specialized in web fetching. Use Fetch_firecrawl to save page content to files, then extract requested information by reading the files or using PythonREPLTool. Do not return full page content; return concise structured results."
        ),
        tools=[fetch_firecrawl, PythonREPLTool()],
        model="google_genai:gemini-3-flash-preview",
    ),
]


def get_agent_messages(
    copied_files: list[str],
    output_columns: list[dict[str, str]],
    additional_instructions: str | None = None,
    example_output_path: str | None = None,
) -> tuple[str, list[HumanMessage]]:
    columns_info = "\n".join(
        [f"- {col['name']}: {col['description']}" for col in output_columns]
    )

    initial_message = f"""Start processing the data now.

Input files available in your workspace:
{"\n".join([f"- {name}" for name in copied_files])}

The first row of the 'output.csv' must contain the columns names.
The 'output.csv' MUST have the following columns.
IMPORTANT: Each column description is a strict instruction for how to populate that column.
{columns_info}
"""

    if additional_instructions:
        initial_message += f"\nAdditional instructions:\n{additional_instructions}"

    if example_output_path:
        initial_message += """\n\nREFERENCE OUTPUT: The file 'validated_sample.csv' contains validated output from a prior run on a subset of data.
Use it as a strict reference for column format, extraction logic, and URL structure. Process the remaining input files accordingly.
"""

    return initial_message, [HumanMessage(content=initial_message)]
