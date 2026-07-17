"""Dashboard - iScan Pro Multipage"""
import streamlit as st
st.set_page_config(page_title="📊 Dashboard", page_icon="📦", layout="wide", initial_sidebar_state="expanded")

from app import init_session, inject_pwa, render_sidebar, _auto_amortisasi_bulanan, user_has_access, ROLES
import pandas as pd
from datetime import datetime

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("app")
    st.stop()

db = st.session_state.db
user = st.session_state.user

_auto_amortisasi_bulanan(db)
render_sidebar()

st.title("📊 Dashboard Operasional")
st.caption(f"Selamat datang, {user['nama_lengkap']} — {datetime.now().strftime('%d %B %Y, %H:%M')}")

# Stats
col1, col2, col3 = st.columns(3)
p = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status='PACKED'")
col1.metric("✅ Packed", f"{p['cnt']:,}" if p else "0")
pe = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status='PENDING'")
col2.metric("⏳ Pending", f"{pe['cnt']:,}" if pe else "0")
o = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan")
col3.metric("📦 Total Orders", f"{o['cnt']:,}" if o else "0")
