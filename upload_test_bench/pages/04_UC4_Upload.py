import streamlit as st

from p24_agent_node_poc.streamlit_test_pages import render_upload_test_case_page

st.set_page_config(page_title="UC4 Upload - Match Tables Chairs", layout="wide")
render_upload_test_case_page("uc4_match_tables_chairs")
