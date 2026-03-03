import streamlit as st

from p24_agent_node_poc.streamlit_test_pages import render_manual_page

st.set_page_config(page_title="Manual Agent Run", layout="wide")
render_manual_page()
