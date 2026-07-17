"""Dashboard - iScan Pro Multipage"""
import streamlit as st
st.set_page_config(page_title="ðŸ“Š Dashboard", page_icon="ðŸ“¦", layout="wide", initial_sidebar_state="expanded")

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

st.title("ðŸ“Š Dashboard Operasional")
st.caption(f"Selamat datang, {user['nama_lengkap']} â€” {datetime.now().strftime('%d %B %Y, %H:%M')}")

# Stats
col1, col2, col3 = st.columns(3)
p = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status='PACKED'")
col1.metric("âœ… Packed", f"{p['cnt']:,}" if p else "0")
pe = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status='PENDING'")
col2.metric("â³ Pending", f"{pe['cnt']:,}" if pe else "0")
o = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan")
col3.metric("ðŸ“¦ Total Orders", f"{o['cnt']:,}" if o else "0")
