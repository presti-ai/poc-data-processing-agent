import os
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from p24_agent_node_poc.agent import process_data

class TestDataProcessingAgent(unittest.TestCase):

    def test_process_data_structure(self):
        # Sample inputs
        df1 = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        inputs = [df1, "Some additional context string"]
        
        output_columns = [
            {"name": "sum_A_B", "description": "The sum of column A and B"},
            {"name": "is_even", "description": "True if sum_A_B is even, False otherwise"}
        ]
        
        # We'll mock the agent since we don't have an API key
        with patch("p24_agent_node_poc.agent.create_deep_agent") as mock_create_agent:
            mock_agent = MagicMock()
            mock_create_agent.return_value = mock_agent
            
            # Mock the stream for default behavior
            def side_effect(inputs, config, stream_mode="values"):
                yield {"messages": [{"role": "assistant", "content": "Done"}]}

            mock_agent.stream.side_effect = side_effect
            
            # Since our process_data function uses a temp directory, we need to mock tempfile.TemporaryDirectory
            # to know where to put the output.csv file.
            with patch("tempfile.TemporaryDirectory") as mock_temp_dir:
                workspace = os.path.abspath("test_workspace")
                os.makedirs(workspace, exist_ok=True)
                mock_temp_dir.return_value.__enter__.return_value = workspace
                
                # Mock the stream to write the file and return messages
                def stream_with_file(state, config, stream_mode="values"):
                    output_df = pd.DataFrame({"sum_A_B": [4, 6], "is_even": [True, True]})
                    output_df.to_csv(os.path.join(workspace, "output.csv"), index=False)
                    # Yield a single chunk in "values" mode
                    yield {"messages": [{"role": "assistant", "content": "Done"}]}
                
                mock_agent.stream.side_effect = stream_with_file
                
                result_df, agent_messages = process_data(inputs, output_columns)
                
                pd.testing.assert_frame_equal(
                    result_df,
                    pd.DataFrame({"sum_A_B": [4, 6], "is_even": [True, True]})
                )
                self.assertIsInstance(agent_messages, list)
                self.assertTrue(any(msg.get("role") == "system" for msg in agent_messages))
                self.assertTrue(
                    any(msg.get("role") == "assistant" and msg.get("display") == "Done" for msg in agent_messages)
                )
                
                # Clean up
                import shutil
                if os.path.exists(workspace):
                    shutil.rmtree(workspace)

    def test_process_data_error_handling(self):
        # Sample inputs
        inputs = ["Some input"]
        output_columns = [{"name": "col", "description": "desc"}]
        
        with patch("p24_agent_node_poc.agent.create_deep_agent") as mock_create_agent:
            mock_agent = MagicMock()
            mock_create_agent.return_value = mock_agent
            
            with patch("tempfile.TemporaryDirectory") as mock_temp_dir:
                workspace = os.path.abspath("test_workspace_error")
                os.makedirs(workspace, exist_ok=True)
                mock_temp_dir.return_value.__enter__.return_value = workspace
                
                # Mock the stream to NOT write the file
                def stream_no_file(state, config, stream_mode="values"):
                    yield {"messages": [{"role": "assistant", "content": "Failed to create file"}]}
                
                mock_agent.stream.side_effect = stream_no_file
                
                with self.assertRaisesRegex(RuntimeError, "Agent failed to produce 'output.csv'"):
                    process_data(inputs, output_columns)
                
                # Clean up
                import shutil
                if os.path.exists(workspace):
                    shutil.rmtree(workspace)

    def test_large_url_batch_instructions_present(self):
        urls = [f"https://example.com/item/{i}" for i in range(12)]
        df = pd.DataFrame({"url": urls})
        output_columns = [{"name": "url", "description": "copy"}]

        with patch("p24_agent_node_poc.agent.create_deep_agent") as mock_create_agent:
            mock_agent = MagicMock()
            mock_create_agent.return_value = mock_agent

            with patch("tempfile.TemporaryDirectory") as mock_temp_dir:
                workspace = os.path.abspath("test_workspace_urls")
                os.makedirs(workspace, exist_ok=True)
                mock_temp_dir.return_value.__enter__.return_value = workspace

                def stream_with_file(state, config, stream_mode="values"):
                    pd.DataFrame({"url": urls}).to_csv(os.path.join(workspace, "output.csv"), index=False)
                    yield {"messages": [{"role": "assistant", "content": "Done"}]}

                mock_agent.stream.side_effect = stream_with_file

                process_data([df], output_columns)

                system_prompt = mock_create_agent.call_args.kwargs["system_prompt"]
                self.assertIn("URL delegation threshold = 10", system_prompt)

                stream_call = mock_agent.stream.call_args
                initial_state = stream_call.args[0]
                initial_message = initial_state["messages"][0].content
                self.assertIn("Detected URL candidates in provided inputs: 12", initial_message)

                import shutil
                if os.path.exists(workspace):
                    shutil.rmtree(workspace)

if __name__ == "__main__":
    unittest.main()
