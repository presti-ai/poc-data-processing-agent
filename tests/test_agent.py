import os
import shutil
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

if "tavily" not in sys.modules:
    tavily_stub = types.ModuleType("tavily")

    class _StubTavilyClient:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, *args, **kwargs):
            return {"results": []}

    tavily_stub.TavilyClient = _StubTavilyClient
    sys.modules["tavily"] = tavily_stub

if "deepagents" not in sys.modules:
    deepagents_stub = types.ModuleType("deepagents")

    class _StubSubAgent:
        def __init__(self, *args, **kwargs):
            pass

    def _stub_create_deep_agent(*args, **kwargs):
        raise RuntimeError("create_deep_agent should be patched in tests")

    deepagents_stub.SubAgent = _StubSubAgent
    deepagents_stub.create_deep_agent = _stub_create_deep_agent
    sys.modules["deepagents"] = deepagents_stub

if "deepagents.backends.filesystem" not in sys.modules:
    backend_stub = types.ModuleType("deepagents.backends.filesystem")

    class _StubFilesystemBackend:
        def __init__(self, *args, **kwargs):
            pass

    backend_stub.FilesystemBackend = _StubFilesystemBackend
    sys.modules["deepagents.backends.filesystem"] = backend_stub

if "langchain.agents.middleware" not in sys.modules:
    middleware_stub = types.ModuleType("langchain.agents.middleware")

    class _StubToolCallLimitMiddleware:
        def __init__(self, *args, **kwargs):
            pass

    middleware_stub.ToolCallLimitMiddleware = _StubToolCallLimitMiddleware
    sys.modules["langchain.agents.middleware"] = middleware_stub

if "langchain.agents" not in sys.modules:
    agents_stub = types.ModuleType("langchain.agents")
    agents_stub.middleware = sys.modules["langchain.agents.middleware"]
    sys.modules["langchain.agents"] = agents_stub

if "langchain" not in sys.modules:
    langchain_stub = types.ModuleType("langchain")
    langchain_stub.agents = sys.modules["langchain.agents"]
    sys.modules["langchain"] = langchain_stub

if "langchain_experimental.tools" not in sys.modules:
    experimental_tools_stub = types.ModuleType("langchain_experimental.tools")

    class _StubPythonREPLTool:
        def __init__(self, *args, **kwargs):
            pass

    experimental_tools_stub.PythonREPLTool = _StubPythonREPLTool
    sys.modules["langchain_experimental.tools"] = experimental_tools_stub

from p24_agent_node_poc.agent import process_data


class TestDataProcessingAgent(unittest.TestCase):
    def test_process_data_structure(self):
        output_columns = [
            {"name": "sum_A_B", "description": "The sum of column A and B"},
            {"name": "is_even", "description": "True if sum_A_B is even, False otherwise"},
        ]

        src_root = Path("test_sources_structure").resolve()
        src_root.mkdir(exist_ok=True)
        (src_root / "input.csv").write_text("A,B\n1,3\n2,4\n", encoding="utf-8")
        (src_root / "notes.txt").write_text("Some additional context string", encoding="utf-8")

        with patch("p24_agent_node_poc.agent.create_deep_agent") as mock_create_agent:
            mock_agent = MagicMock()
            mock_create_agent.return_value = mock_agent

            with patch("p24_agent_node_poc.agent.tempfile.TemporaryDirectory") as mock_temp_dir:
                workspace = os.path.abspath("test_workspace")
                os.makedirs(workspace, exist_ok=True)
                mock_temp_dir.return_value.__enter__.return_value = workspace

                def stream_with_file(state, config, stream_mode="values"):
                    output_df = pd.DataFrame({"sum_A_B": [4, 6], "is_even": [True, True]})
                    output_df.to_csv(os.path.join(workspace, "output.csv"), index=False)
                    yield (
                        "values",
                        {"messages": [{"role": "assistant", "content": "Done"}]},
                    )

                mock_agent.stream.side_effect = stream_with_file

                result_df, agent_messages = process_data(
                    input_files=[src_root / "input.csv", src_root / "notes.txt"],
                    output_columns=output_columns,
                    save_output_dir=Path(workspace) / "saved_output",
                )

                pd.testing.assert_frame_equal(
                    result_df,
                    pd.DataFrame({"sum_A_B": [4, 6], "is_even": [True, True]}),
                )
                self.assertIsInstance(agent_messages, dict)
                messages = agent_messages.get("messages", [])
                self.assertIsInstance(messages, list)
                self.assertTrue(
                    any(msg.get("role") == "assistant" and msg.get("content") == "Done" for msg in messages)
                )

                if os.path.exists(workspace):
                    shutil.rmtree(workspace)

        if src_root.exists():
            shutil.rmtree(src_root)

    def test_process_data_error_handling(self):
        output_columns = [{"name": "col", "description": "desc"}]

        src_root = Path("test_sources_error").resolve()
        src_root.mkdir(exist_ok=True)
        (src_root / "input.txt").write_text("Some input", encoding="utf-8")

        with patch("p24_agent_node_poc.agent.create_deep_agent") as mock_create_agent:
            mock_agent = MagicMock()
            mock_create_agent.return_value = mock_agent

            with patch("p24_agent_node_poc.agent.tempfile.TemporaryDirectory") as mock_temp_dir:
                workspace = os.path.abspath("test_workspace_error")
                os.makedirs(workspace, exist_ok=True)
                mock_temp_dir.return_value.__enter__.return_value = workspace

                def stream_no_file(state, config, stream_mode="values"):
                    yield (
                        "values",
                        {
                            "messages": [
                                {"role": "assistant", "content": "Failed to create file"}
                            ]
                        },
                    )

                mock_agent.stream.side_effect = stream_no_file

                with self.assertRaisesRegex(RuntimeError, "Agent failed to produce 'output.csv'"):
                    process_data(input_files=[src_root / "input.txt"], output_columns=output_columns)

                if os.path.exists(workspace):
                    shutil.rmtree(workspace)

        if src_root.exists():
            shutil.rmtree(src_root)

    def test_large_url_batch_instructions_present(self):
        urls = [f"https://example.com/item/{i}" for i in range(12)]
        output_columns = [{"name": "url", "description": "copy"}]

        src_root = Path("test_sources_urls").resolve()
        src_root.mkdir(exist_ok=True)
        pd.DataFrame({"url": urls}).to_csv(src_root / "urls.csv", index=False)

        with patch("p24_agent_node_poc.agent.create_deep_agent") as mock_create_agent:
            mock_agent = MagicMock()
            mock_create_agent.return_value = mock_agent

            with patch("p24_agent_node_poc.agent.tempfile.TemporaryDirectory") as mock_temp_dir:
                workspace = os.path.abspath("test_workspace_urls")
                os.makedirs(workspace, exist_ok=True)
                mock_temp_dir.return_value.__enter__.return_value = workspace

                def stream_with_file(state, config, stream_mode="values"):
                    pd.DataFrame({"url": urls}).to_csv(os.path.join(workspace, "output.csv"), index=False)
                    yield (
                        "values",
                        {"messages": [{"role": "assistant", "content": "Done"}]},
                    )

                mock_agent.stream.side_effect = stream_with_file
                process_data(
                    input_files=[src_root / "urls.csv"],
                    output_columns=output_columns,
                    save_output_dir=Path(workspace) / "saved_output",
                )

                system_prompt = mock_create_agent.call_args.kwargs["system_prompt"]
                self.assertIn("delegate the task to subagents", system_prompt)
                self.assertIn("avoid reading full html pages", system_prompt.lower())
                self.assertIn("return compact JSON that points to local HTML file path", system_prompt)

                if os.path.exists(workspace):
                    shutil.rmtree(workspace)

        if src_root.exists():
            shutil.rmtree(src_root)


if __name__ == "__main__":
    unittest.main()
