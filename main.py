import pandas as pd

from p24_agent_node_poc.agent import process_data

df_tables = pd.read_csv("data/but/but-tables.csv")
df_chairs = pd.read_csv("data/but/but-chairs.csv")

_inputs = [df_tables.head(1), df_chairs.sample(10)]

_output_columns = [
    {"name": "Table EAN", "description": "The EAN (product identifier) of the table"},
    {"name": "Table link", "description": "The link to the table product page"},
    {"name": "Best Chair EAN", "description": "The EAN (product identifier) of the best chair for the table. This should be based on the description of the table and the chairs fetched from the URLS."},
    {"name": "Best Chair link", "description": "The link to the best chair product page."},
]

res, messages = process_data(_inputs, _output_columns)
