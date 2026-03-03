import streamlit as st

st.set_page_config(page_title="P24 Agent Test Bench", layout="wide")

st.title("P24 Agent Test Bench")
st.write(
    "Use the sidebar pages to run the six predefined test cases or the manual page. "
    "Each test case includes a small debug dataset and a 100-row dataset."
)

st.subheader("Available pages")
st.markdown("- `00 Manual Agent Run`: free-form dataset upload and schema definition.")
st.markdown("- `01 UC1 Normalize URLs`")
st.markdown("- `02 UC2 Packshot Dimensions`")
st.markdown("- `03 UC3 Product Multi Images`")
st.markdown("- `04 UC4 Match Tables Chairs`")
st.markdown("- `05 UC5 Complementary Products`")
st.markdown("- `06 UC6 Inspiration Lifestyle Images`")

st.subheader("Notes")
st.markdown("- Each dedicated test-case page shows input datasets, output schema, run button, and output table.")
st.markdown("- Agent discussion appears in the right column with one collapsed message block per agent message.")
