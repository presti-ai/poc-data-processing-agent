# CLAUDE.md — P24 Agent Node POC

## Project Overview
LLM-based data processing agent. Takes CSV input(s), uses AI tools (Python REPL, web search, page fetching) to process data, and always produces a final `output.csv`. Serves a FastAPI + Vanilla JS frontend at `http://localhost:5001`.

## Running the App
```bash
poetry run uvicorn server:app --reload --host 0.0.0.0 --port 5001
```
> Avoid ports 8000 and 8080 — Cursor occupies both.

## Stack
- **Python 3.12+** with **Poetry** for dependency management
- **FastAPI** + **uvicorn** for the backend
- **deepagents** for agent orchestration (LangChain-based)
- **LangChain** tools: `PythonREPLTool`, custom web tools
- **Vanilla JS** SPA frontend (no framework, no build step)
- **GCS** (`presti-tmp-test` bucket, `haithem/` prefix) for run history and file storage
- **Loguru** for logging

## Project Structure
```
src/p24_agent_node_poc/
  agent.py            # Core: process_data() + process_data_two_phase()
  tools.py            # LangChain tools: internet_search, fetch_page_content, fetch_html, fetch_wayback_page
  gcs_storage.py      # GCS read/write for run history and uploads
  test_case_configs.py # 6 predefined use case configs (UC1–UC6)
  streamlit_test_pages.py
server.py             # FastAPI routes + SSE streaming
frontend/             # Vanilla JS SPA (index.html, js/app.js, css/style.css)
data/
  input/              # Auto-saved copies of each run's input
  output/             # Auto-saved copies of each run's output
  test_cases/         # Predefined datasets for UC1–UC6 (small/medium/large variants)
tests/test_agent.py   # Unit tests (mock agent, no real API calls)
main.py               # CLI entry point for quick manual runs
```

## Key Concepts

### `process_data()` — `agent.py:91`
Main function. Creates an isolated temp workspace, copies input files into it, builds a system prompt + initial message, runs the `deepagents` agent with streaming, then reads the produced `output.csv`. Saves inputs to `data/input/` and outputs to `data/output/` with timestamps.

### `process_data_two_phase()` — `agent.py:460`
Two-phase scaling strategy:
- **Phase 1:** runs on first N rows (default 5), returns sample output for human validation
- **Phase 2:** runs on remaining rows using Phase 1 validated output as a reference (`validated_sample.csv`)

### Agent Tools (`tools.py`)
| Tool | Purpose |
|------|---------|
| `PythonREPLTool` | Data manipulation with pandas, saving output.csv |
| `Internet_search` | Tavily-powered web search |
| `Fetch_page_content` | Jina Reader — returns clean text (first choice) |
| `Fetch_HTML_from_URL` | Raw HTML with Jina fallback on 403 |
| `Fetch_wayback_page` | Wayback Machine fallback when direct fetch fails |

### Subagent
A `web_fetch_batch_worker` subagent handles URL-heavy extraction tasks. Main agent delegates batches of >5 URLs to it to avoid context bloat. Subagent is limited to 6 tool calls per delegation (`ToolCallLimitMiddleware`).

### SSE Streaming (`server.py`)
`POST /api/run` returns a `text/event-stream`. The frontend reads it in real time. Events: `chunk` (model/tool activity), `retry` (rate limit), `done` (final CSV or error).

### GCS Storage (`gcs_storage.py`)
- Bucket: `presti-tmp-test`
- All files under prefix: `haithem/`
- Run history: `haithem/runs_history.json`
- Outputs: `haithem/outputs/output_{run_id}.csv`
- Uploads: `haithem/uploads/{run_id}/`
- Uses Application Default Credentials (no key in `.env`)

## Environment Variables (`.env`)
```
TAVILY_API_KEY=...       # Required — Tavily web search
JINA_API_KEY=...         # Optional — higher Jina Reader quota
GOOGLE_API_KEY=...       # Required — Gemini model access
```
GCS auth is via ADC (`gcloud auth application-default login`), not in `.env`.

## Models
| Role | Default | Alternatives |
|------|---------|-------------|
| Main agent | `anthropic:claude-opus-4-6` | `anthropic:claude-sonnet-4-6`, `google_genai:gemini-3.1-pro-preview` |
| Subagent | `openai:gpt-5.4` | `openai:gpt-4o`, `anthropic:claude-sonnet-4-6` |

## 6 Predefined Use Cases (`test_case_configs.py`)
| Key | Title |
|-----|-------|
| `uc1_normalize_urls` | Normalize messy URL inputs (1 URL per row) |
| `uc2_packshot_dimensions` | Extract product image + dimensions from product URL |
| `uc3_product_multi_images` | Extract all product images from a product URL |
| `uc4_match_tables_chairs` | Match tables to best chair (2 input files) |
| `uc5_complementary_products` | Find complementary products for a given product URL |
| `uc6_inspiration_lifestyle_images` | Collect lifestyle inspiration image URLs |

Each use case has `small`, `medium`, `large` dataset variants in `data/test_cases/`.

## Debug Logging
Every run appends to `log.txt` in the project root. Contains:
- Full system prompt + initial message
- All model reasoning (AI messages)
- All tool calls + results (truncated at 8000 chars)
- Subagent stream events

## Testing
```bash
poetry run python -m pytest tests/
```
Tests in `tests/test_agent.py` mock `create_deep_agent` and `tempfile.TemporaryDirectory` — no real API calls needed.

## Frontend
Single-page app with hash routing:
- `#/` — Run page (upload files, define output schema, run agent)
- `#/history` — Run history from GCS (click row to rerun with preset)
- `#/rerun/{run_id}` — Loads a previous run's inputs/params as preset

## Important Constraints
- The agent **must** produce `output.csv` in its workspace or the run raises `RuntimeError`
- Rate limit (429) triggers automatic retry up to 3 times with 65s wait
- CORS is currently locked to `localhost:8000` — needs updating if port changes
- Output columns are passed as `[{name, description}]` — descriptions act as strict instructions
- Workspace is a temp dir; agent uses relative paths only
