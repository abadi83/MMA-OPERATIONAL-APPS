"""Akuntansi Page - Settlement + Neraca + Iklan"""
import streamlit as st
st.set_page_config(page_title="Akuntansi", page_icon="📊", layout="wide")

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.shared import *
import pandas as pd
from datetime import datetime

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("pages/00_Login.py")
    st.stop()

db = st.session_state.db
auto_amortisasi_bulanan(db)

tab1, tab2, tab3 = st.tabs(["Settlement", "Neraca", "Iklan"])

with tab1:
    st.subheader("Settlement Harian")
    mp = st.selectbox("Marketplace", ["Shopee","TikTok","Lazada","Tokopedia"], key="stl_mp")
    tgl = st.date_input("Tanggal", datetime.now(), key="stl_tgl")
    uploaded = st.file_uploader("Upload CSV/Excel", type=["csv","xlsx"], key="stl_file")
    if uploaded:
        try:
            df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
            st.dataframe(df.head(5), width="stretch")
            total = df.select_dtypes(include="number").sum().sum()
            st.metric("Total", f"Rp {total:,.0f}")
            if st.button("Simpan Settlement", type="primary"):
                tgl_str = tgl.strftime("%d-%m-%Y")
                db.execute("INSERT INTO settlement_harian (tanggal,marketplace,total_penjualan) VALUES (?,?,?)", (tgl_str, mp, total))
                st.success(f"Settlement {mp} {tgl_str} tersimpan!")
                st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

with tab2:
    st.subheader("Neraca Akrual")
    aset = db.fetch_one("SELECT SUM(debit)-SUM(kredit) as total FROM jurnal_umum WHERE kode_akun LIKE '1-%'")
    liab = db.fetch_one("SELECT SUM(kredit)-SUM(debit) as total FROM jurnal_umum WHERE kode_akun LIKE '2-%'")
    ekuitas = db.fetch_one("SELECT SUM(kredit)-SUM(debit) as total FROM jurnal_umum WHERE kode_akun LIKE '3-%'")
    laba = db.fetch_one("SELECT (SELECT SUM(kredit)-SUM(debit) FROM jurnal_umum WHERE kode_akun LIKE '4-%') - (SELECT SUM(debit)-SUM(kredit) FROM jurnal_umum WHERE kode_akun LIKE '5-%') as total")
    a = aset["total"] or 0 if aset else 0
    l = liab["total"] or 0 if liab else 0
    e = (ekuitas["total"] or 0 if ekuitas else 0) + (laba["total"] or 0 if laba else 0)
    c1,c2,c3 = st.columns(3)
    c1.metric("Aset", f"Rp {a:,.0f}")
    c2.metric("Liabilitas", f"Rp {l:,.0f}")
    c3.metric("Ekuitas", f"Rp {e:,.0f}")
    if abs(a-l-e) < 100: st.success("Balance!")
    else: st.error(f"Selisih: Rp {a-l-e:,.0f}")

with tab3:
    st.subheader("Biaya Iklan Harian")
    iklan_mp = st.selectbox("Marketplace", ["Shopee","TikTok","Lazada","Tokopedia"], key="iklan_mp")
    iklan_tgl = st.date_input("Tanggal", datetime.now(), key="iklan_tgl")
    iklan_biaya = st.number_input("Biaya (Rp)", min_value=0, step=10000, key="iklan_biaya")
    if st.button("Simpan Iklan", type="primary") and iklan_biaya > 0:
        tgl_str = iklan_tgl.strftime("%d-%m-%Y")
        db.execute("INSERT INTO iklan_harian (tanggal,marketplace,biaya) VALUES (?,?,?)", (tgl_str, iklan_mp, iklan_biaya))
        post_jurnal(db, tgl_str, f"ADS-{iklan_mp}", f"Iklan {iklan_mp}", [("5-2300","Beban Iklan",iklan_biaya,0),("1-1000","Kas & Bank",0,iklan_biaya)], "iklan", 0)
        st.success(f"Iklan {iklan_mp}: Rp {iklan_biaya:,.0f}")
        st.rerun()
    rows = db.fetch_all("SELECT * FROM iklan_harian ORDER BY tanggal DESC LIMIT 30")
    if rows: st.dataframe(pd.DataFrame([dict(r) for r in rows]), width="stretch", hide_index=True)