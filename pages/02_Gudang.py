"""Gudang Inventory Page"""
import streamlit as st
st.set_page_config(page_title="📦 Gudang", page_icon="📦", layout="wide")

from app import init_session, inject_pwa, render_sidebar, render_gudang_inventory

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("pages/00_Login.py")
    st.stop()

render_sidebar()
render_gudang_inventory()
