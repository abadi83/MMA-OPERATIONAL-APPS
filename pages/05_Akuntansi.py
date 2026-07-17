"""Akuntansi Page - Settlement + Neraca + Iklan"""
import streamlit as st
st.set_page_config(page_title="ðŸ“Š Akuntansi", page_icon="ðŸ“Š", layout="wide")

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); from modules.shared import *
import pandas as pd
from datetime import datetime

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("pages/00_Login.py")
    st.stop()

db = st.session_state.db
user = st.session_state.user
auto_amortisasi_bulanan(db)
render_sidebar()

tab1, tab2, tab3 = st.tabs(["ðŸ“¥ Settlement Harian", "ðŸ“Š Neraca Akrual", "ðŸ“¢ Biaya Iklan"])

with tab1:
    st.subheader("ðŸ“¥ Settlement Harian")
    render_settlement_daily_import()

with tab2:
    st.subheader("ðŸ“Š Neraca Akrual")
    n = get_neraca_akrual(db)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Aset", f"Rp {n['total_aset']:,.0f}")
    c2.metric("Total Liabilitas", f"Rp {n['total_liabilitas']:,.0f}")
    c3.metric("Total Ekuitas", f"Rp {n['total_ekuitas']:,.0f}")
    delta = n["balance"]
    if abs(delta) < 100:
        st.success(f"âœ… Balance: Rp {delta:,.0f}")
    else:
        st.error(f"âš ï¸ Tidak balance! Selisih: Rp {delta:,.0f}")

with tab3:
    st.subheader("ðŸ“¢ Biaya Iklan Harian")
    render_iklan_harian()
