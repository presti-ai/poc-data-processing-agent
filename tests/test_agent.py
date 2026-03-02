import pandas as pd
from p24_agent_node_poc.agent import process_data
import unittest
from unittest.mock import patch, MagicMock
import os

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
            
            # We need to simulate the agent creating the output.csv file
            def side_effect(inputs, config):
                # The workspace_root is a temporary directory, we need to find it.
                # In the real code, it's a context manager.
                # For testing, we can just mock it or intercept the call.
                return {"messages": [{"role": "assistant", "content": "Done"}]}

            mock_agent.invoke.side_effect = side_effect
            
            # Since our process_data function uses a temp directory, we need to mock tempfile.TemporaryDirectory
            # to know where to put the output.csv file.
            with patch("tempfile.TemporaryDirectory") as mock_temp_dir:
                workspace = "test_workspace"
                os.makedirs(workspace, exist_ok=True)
                mock_temp_dir.return_value.__enter__.return_value = workspace
                
                # Mock the invoke to write the file
                def invoke_with_file(state, config):
                    output_df = pd.DataFrame({"sum_A_B": [4, 6], "is_even": [True, True]})
                    output_df.to_csv(os.path.join(workspace, "output.csv"), index=False)
                    return {"messages": [{"role": "assistant", "content": "Done"}]}
                
                mock_agent.invoke.side_effect = invoke_with_file
                
                result_df = process_data(inputs, output_columns)
                
                pd.testing.assert_frame_equal(
                    result_df,
                    pd.DataFrame({"sum_A_B": [4, 6], "is_even": [True, True]})
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
                workspace = "test_workspace_error"
                os.makedirs(workspace, exist_ok=True)
                mock_temp_dir.return_value.__enter__.return_value = workspace
                
                # Mock the invoke to NOT write the file
                mock_agent.invoke.return_value = {"messages": [{"role": "assistant", "content": "Failed to create file"}]}
                
                with self.assertRaisesRegex(RuntimeError, "Agent failed to produce 'output.csv'"):
                    process_data(inputs, output_columns)
                
                # Clean up
                import shutil
                if os.path.exists(workspace):
                    shutil.rmtree(workspace)

if __name__ == "__main__":
    unittest.main()
