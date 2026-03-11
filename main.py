from pathlib import Path

from p24_agent_node_poc.agent import process_data

_inputs = [
    Path("data/test_cases/uc4_match_tables_chairs/small_tables.csv"),
    Path("data/test_cases/uc4_match_tables_chairs/small_chairs.csv"),
]

_output_columns = [
    {"name": "Table EAN", "description": "The EAN (product identifier) of the table"},
    {"name": "Table link", "description": "The link to the table product page"},
    {
        "name": "Best Chair EAN",
        "description": "The EAN (product identifier) of the best chair for the table. This should be based on the description of the table and the chairs fetched from the URLS.",
    },
    {
        "name": "Best Chair link",
        "description": "The link to the best chair product page.",
    },
]

additional_instructions = ""

res, messages = process_data(input_files=_inputs, output_columns=_output_columns,
                             additional_instructions=additional_instructions)
