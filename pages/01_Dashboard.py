"""
Dashboard - iScan Pro Multipage
"""
import streamlit as st

st.set_page_config(page_title="iScan Pro - Dashboard", page_icon="📊", layout="wide")

# Pastikan user sudah login
if not st.session_state.get("authenticated"):
    st.switch_page("app.py")

st.title("📊 Dashboard Operasional")
db = st.session_state.db
cache = st.session_state.cache

# Import shared helpers
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config, Theme
from constants import APP_NAME, APP_VERSION

# ── Stats Cards ──
packed = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED'")
pending = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PENDING'")
total_orders = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan")

col1, col2, col3 = st.columns(3)
col1.metric("✅ Packed", f"{packed['cnt']:,}" if packed else "0")
col2.metric("⏳ Pending", f"{pending['cnt']:,}" if pending else "0")  
col3.metric("📦 Total Orders", f"{total_orders['cnt']:,}" if total_orders else "0")

st.caption(f"iScan Pro v{APP_VERSION} — Multipage Edition")
