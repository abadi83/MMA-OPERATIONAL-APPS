"""Sales Page - Input Resi + Retur Klaim"""
import streamlit as st
st.set_page_config(page_title="ðŸ“‹ Sales", page_icon="ðŸ“‹", layout="wide")

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

tab1, tab2 = st.tabs(["ðŸ“‹ Input Resi & Pesanan", "ðŸ”„ Retur & Klaim"])

with tab1:
    st.subheader("ðŸ“‹ Input Resi & Pesanan")
    st.caption("Input manual pesanan + resi dari marketplace.")

    mp = st.selectbox("Marketplace", ["Shopee", "TikTok", "Lazada", "Tokopedia"], key="sales_mp")
    col1, col2 = st.columns(2)
    with col1:
        no_pesanan = st.text_input("No Pesanan", key="sales_order")
        no_resi = st.text_input("No Resi", key="sales_resi")
        nama_produk = st.text_input("Nama Produk", key="sales_produk")
    with col2:
        qty = st.number_input("Qty", min_value=1, value=1, key="sales_qty")
        harga = st.number_input("Harga Jual (Rp)", min_value=0, value=0, step=1000, key="sales_harga")
        total = qty * harga
        st.metric("Total", f"Rp {total:,.0f}")

    kurir = st.text_input("Kurir", placeholder="JNE, J&T, SiCepat...", key="sales_kurir")
    nama_toko = st.text_input("Nama Toko", value=st.session_state.get("selected_store", "Mitra Mulia Abadi"), key="sales_toko")

    if st.button("ðŸ’¾ Simpan Pesanan", type="primary"):
        if no_pesanan and nama_produk:
            db.execute("INSERT INTO penjualan (marketplace,no_pesanan,no_resi,nama_produk,qty,harga_jual,total_harga,kurir,nama_toko,tanggal_pesanan,status_pesanan) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (mp, no_pesanan, no_resi, nama_produk, qty, harga, total, kurir, nama_toko, datetime.now().strftime("%d-%m-%Y"), "PROSES"))
            st.success(f"âœ… Pesanan {no_pesanan} tersimpan!")
            st.rerun()
        else:
            st.error("No Pesanan dan Nama Produk wajib diisi!")

    # Recent orders
    st.divider()
    orders = db.fetch_all("SELECT * FROM penjualan ORDER BY id DESC LIMIT 20")
    if orders:
        st.dataframe(pd.DataFrame([dict(r) for r in orders]), width="stretch", hide_index=True)

with tab2:
    st.subheader("ðŸ”„ Retur & Klaim")
    st.caption("Catat retur atau klaim dari pembeli.")

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        retur_resi = st.text_input("No Resi / Pesanan", key="retur_resi")
        retur_mp = st.selectbox("Marketplace", ["Shopee", "TikTok", "Lazada", "Tokopedia"], key="retur_mp")
    with col_r2:
        retur_nominal = st.number_input("Nominal Klaim (Rp)", min_value=0, step=1000, key="retur_nominal")
        retur_status = st.selectbox("Status", ["PROSES", "BERHASIL", "GAGAL"], key="retur_status")

    if st.button("ðŸ’¾ Catat Retur", type="primary") and retur_resi:
        db.execute("INSERT INTO retur_klaim (no_resi, marketplace, nominal_klaim, status_klaim, tanggal) VALUES (?,?,?,?,?)",
                   (retur_resi, retur_mp, retur_nominal, retur_status, datetime.now().strftime("%d-%m-%Y")))
        st.success("âœ… Retur tercatat!")
        st.rerun()

    retur_list = db.fetch_all("SELECT * FROM retur_klaim ORDER BY id DESC LIMIT 30")
    if retur_list:
        st.dataframe(pd.DataFrame([dict(r) for r in retur_list]), width="stretch", hide_index=True)
