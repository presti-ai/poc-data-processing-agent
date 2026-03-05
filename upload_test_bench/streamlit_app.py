"""
Upload Test Bench: run the 6 use cases with your own CSV uploads.

Each page corresponds to one use case. Upload your CSV file(s) (max 20 rows per file),
and run the agent with the predefined output schema and instructions.
"""

import streamlit as st

st.set_page_config(page_title="P24 Upload Test Bench", layout="wide")

st.title("P24 Upload Test Bench")
st.write(
    "Run the six use cases with your own data. Upload CSV file(s) (maximum 20 rows per file). "
    "Each use case has a fixed output schema and instructions."
)

st.subheader("Available pages")
st.markdown("- `01 UC1 Upload` - Normalize URLs")
st.markdown("- `02 UC2 Upload` - Product Packshot and Dimensions")
st.markdown("- `03 UC3 Upload` - Product Multi Images")
st.markdown("- `04 UC4 Upload` - Match Tables Chairs (upload 2 files)")
st.markdown("- `05 UC5 Upload` - Complementary Products")
st.markdown("- `06 UC6 Upload` - Inspiration Lifestyle Images")

st.subheader("Notes")
st.markdown("- Maximum 20 rows per uploaded file.")
st.markdown("- Output schema and instructions are fixed per use case.")
st.markdown("- Run from project root: `poetry run streamlit run upload_test_bench/streamlit_app.py`")
