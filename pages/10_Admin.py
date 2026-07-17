"""Admin Page - User Management"""
import streamlit as st
st.set_page_config(page_title="âš™ï¸ Admin", page_icon="âš™ï¸", layout="wide")

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); from modules.shared import *
import pandas as pd

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("pages/00_Login.py")
    st.stop()

db = st.session_state.db
user = st.session_state.user

# Admin only
if user.get("role") != "admin":
    st.error("â›” Hanya admin yang bisa mengakses halaman ini.")
    st.stop()

render_sidebar()

st.title("âš™ï¸ Admin - Manajemen User")
st.caption(f"Login sebagai: {user['username']} ({user['role']})")

tab1, tab2 = st.tabs(["ðŸ‘¥ Daftar User", "âž• Tambah User"])

with tab1:
    users = db.fetch_all("SELECT id, username, nama_lengkap, role, active, last_login FROM users ORDER BY id")
    if users:
        st.dataframe(pd.DataFrame([dict(r) for r in users]), width="stretch", hide_index=True)

with tab2:
    col1, col2 = st.columns(2)
    with col1:
        new_user = st.text_input("Username", key="admin_new_user")
        new_nama = st.text_input("Nama Lengkap", key="admin_new_nama")
    with col2:
        new_pass = st.text_input("Password", type="password", key="admin_new_pass")
        new_role = st.selectbox("Role", ["admin", "operasional", "warehouse", "finance"], key="admin_new_role")

    if st.button("âž• Buat User", type="primary") and new_user and new_pass:
        try:
            db.execute("INSERT INTO users (username,password_hash,nama_lengkap,role) VALUES (?,?,?,?)",
                       (new_user.lower(), hash_password(new_pass), new_nama, new_role))
            st.success(f"âœ… User {new_user} dibuat!")
            st.rerun()
        except:
            st.error("Username sudah ada!")

# Logout
st.divider()
if st.button("ðŸ”’ Logout", type="secondary"):
    user = st.session_state.get("user")
    if user:
        invalidate_auth_token(db, user_id=user["id"])
    st.session_state.authenticated = False
    st.session_state.user = None
    st.query_params.clear()
    st.switch_page("pages/00_Login.py")
