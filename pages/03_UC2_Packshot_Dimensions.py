import streamlit as st

from p24_agent_node_poc.streamlit_test_pages import render_uc2_page

st.set_page_config(page_title="UC2 Packshot and Dimensions", layout="wide")
render_uc2_page()
