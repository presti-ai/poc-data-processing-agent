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

4. **Run the Streamlit multipage app**:
   ```bash
   poetry run streamlit run demo_app.py
   ```
   Then use the sidebar pages:
   - `01 Manual Agent Run`
   - `02-07` predefined use-case test benches (small + 100-row scenarios)

## 📂 Project Structure

- `main.py`: Entry point for the CLI data processing pipeline.
- `demo_app.py`: Streamlit app entrypoint (home page for multipage navigation).
- `pages/`: Streamlit pages including manual run page and 6 predefined test-case pages.
- `src/p24_agent_node_poc/agent.py`: Core agent logic and system prompts.
- `src/p24_agent_node_poc/tools.py`: Custom tools for search and web fetching.
- `data/test_cases/`: Test datasets for each use case (`small` + `100-row` scenarios).

Built with ❤️ for efficient data automation.
