import pandas as pd

from p24_agent_node_poc.agent import process_data

if __name__ == '__main__':
    df1 = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    _inputs = [df1]

    _output_columns = [
        {"name": "sum_A_B", "description": "The sum of column A and B"},
        {"name": "is_even", "description": "True if sum_A_B is even, False otherwise"}
    ]

    res, messages = process_data(_inputs, _output_columns)
