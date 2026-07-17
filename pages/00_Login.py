"""Login Page"""
import streamlit as st
st.set_page_config(page_title="🔐 Login", page_icon="📦", layout="wide")

from app import init_session, inject_pwa, authenticate_user, generate_auth_token

inject_pwa()
init_session()

# Already logged in → dashboard
if st.session_state.get("authenticated"):
    st.switch_page("pages/01_Dashboard.py")
    st.stop()

# ── Login Form ──
st.markdown("<br><br>", unsafe_allow_html=True)
col = st.columns([1, 2, 1])
with col[1]:
    st.markdown("""<div style="text-align:center;margin-bottom:30px;">
        <span style="font-size:42px;font-weight:800;color:#FFFFFF;">iScan</span>
        <span style="font-size:32px;font-weight:700;color:#0A84FF;">Pro</span>
    </div>""", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("### 🔐 Login")
        u = st.text_input("Username", placeholder="Masukkan username", key="login_u")
        p = st.text_input("Password", type="password", placeholder="Masukkan password", key="login_p")
        if st.button("🔓 Masuk", type="primary", width="stretch"):
            if not u.strip() or not p.strip():
                st.error("Username dan password harus diisi!")
            else:
                user = authenticate_user(st.session_state.db, u.strip(), p.strip())
                if user:
                    token = generate_auth_token(st.session_state.db, user["id"])
                    st.session_state.authenticated = True
                    st.session_state.user = user
                    st.query_params["auth"] = token
                    st.switch_page("pages/01_Dashboard.py")
                else:
                    st.error("❌ Username atau password salah!")
    st.caption("admin / admin123")
