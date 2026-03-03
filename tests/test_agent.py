import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

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
                    yield {"messages": [{"role": "assistant", "content": "Done"}]}

                mock_agent.stream.side_effect = stream_with_file

                result_df, agent_messages = process_data(
                    input_files=[src_root / "input.csv", src_root / "notes.txt"],
                    output_columns=output_columns,
                )

                pd.testing.assert_frame_equal(
                    result_df,
                    pd.DataFrame({"sum_A_B": [4, 6], "is_even": [True, True]}),
                )
                self.assertIsInstance(agent_messages, list)
                self.assertTrue(any(msg.get("role") == "system" for msg in agent_messages))
                self.assertTrue(
                    any(msg.get("role") == "assistant" and msg.get("display") == "Done" for msg in agent_messages)
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
                    yield {"messages": [{"role": "assistant", "content": "Failed to create file"}]}

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
                    yield {"messages": [{"role": "assistant", "content": "Done"}]}

                mock_agent.stream.side_effect = stream_with_file
                process_data(input_files=[src_root / "urls.csv"], output_columns=output_columns)

                system_prompt = mock_create_agent.call_args.kwargs["system_prompt"]
                self.assertIn("URL delegation threshold = 10", system_prompt)

                stream_call = mock_agent.stream.call_args
                initial_state = stream_call.args[0]
                initial_message = initial_state["messages"][0].content
                self.assertIn("Detected URL candidates in provided inputs: 12", initial_message)

                if os.path.exists(workspace):
                    shutil.rmtree(workspace)

        if src_root.exists():
            shutil.rmtree(src_root)


if __name__ == "__main__":
    unittest.main()
