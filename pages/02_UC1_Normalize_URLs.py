import streamlit as st

from p24_agent_node_poc.streamlit_test_pages import render_test_case_page

st.set_page_config(page_title="UC1 Normalize URLs", layout="wide")
render_test_case_page("uc1_normalize_urls")
