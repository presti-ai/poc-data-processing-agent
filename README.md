# 🤖 P24 Agent Node POC

A powerful data processing agent proof-of-concept that combines LLMs with Python execution and web tools to automate complex data tasks.

## 🚀 Features

- 🧠 **Deep Agent Architecture**: Uses `deepagents` to manage complex multi-step reasoning.
- 🐍 **Code Execution**: Built-in `PythonREPLTool` for dynamic data manipulation with pandas.
- 🌐 **Web Intelligence**: 
    - `Internet_search`: Powered by Tavily for high-quality web results.
    - `Fetch_HTML_from_URL`: Robust HTML extraction with automatic Jina Reader fallback to bypass bot detection (403 errors) 🛡️.
- 📊 **CSV-to-CSV Workflow**: Input your data, define your goals, and get a structured `output.csv`.

## 🛠️ Quick Start

1. **Install dependencies**:
   ```bash
   poetry install
   ```

2. **Set up environment**:
   Create a `.env` file with your API keys:
   ```env
   TAVILY_API_KEY=your_key
   JINA_API_KEY=your_key (optional)
   GOOGLE_API_KEY=your_key
   ```

3. **Run the CLI demo**:
   ```bash
   poetry run python main.py
   ```

4. **Run the web app** (FastAPI + vanilla JS frontend):
   ```bash
   poetry run uvicorn server:app --reload --host 0.0.0.0 --port 8000
   ```
   Open http://localhost:8000 in your browser. The app provides a manual agent run interface for dataset upload, output schema definition, and real-time streaming of agent messages.

## 📂 Project Structure

- `main.py`: Entry point for the CLI data processing pipeline.
- `server.py`: FastAPI server with `/api/run` (SSE streaming) and static frontend.
- `frontend/`: Vanilla JS/HTML/CSS frontend (index.html, css/, js/).
- `src/p24_agent_node_poc/agent.py`: Core agent logic and system prompts.
- `src/p24_agent_node_poc/tools.py`: Custom tools for search and web fetching.
- `data/test_cases/`: Test datasets for each use case (`small` + `100-row` scenarios).

## 📋 Debug Logging

When running the agent (CLI or web app), a `log.txt` file is created in the working directory. It captures:
- Full system prompt and initial message
- Workspace path and copied files
- Main agent AI messages (reasoning)
- Tool calls with arguments
- Tool results (truncated if very long)
- Tool invocations from `tools.py` (Fetch_page_content, Fetch_HTML_from_URL, Internet_search)

Use it to debug agent behavior, understand what the main agent is doing, and trace subagent delegations.

Built with ❤️ for efficient data automation.
