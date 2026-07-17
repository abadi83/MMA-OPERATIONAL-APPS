"""Gudang Inventory Page"""
import streamlit as st
st.set_page_config(page_title="ðŸ“¦ Gudang", page_icon="ðŸ“¦", layout="wide")

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); from modules.shared import *

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("pages/00_Login.py")
    st.stop()

render_gudang_inventory()
