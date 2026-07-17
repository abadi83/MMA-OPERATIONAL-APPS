"""Purchase + OPEX Page"""
import streamlit as st
st.set_page_config(page_title="📦 Purchase/OPEX", page_icon="📦", layout="wide")

from app import *
import pandas as pd
from datetime import datetime

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("pages/00_Login.py")
    st.stop()

db = st.session_state.db
user = st.session_state.user
_auto_amortisasi_bulanan(db)
render_sidebar()

tab1, tab2 = st.tabs(["📦 Pembelian SKU", "💸 Input OPEX"])

with tab1:
    st.subheader("📦 Pembelian SKU / Inventory")
    col1, col2 = st.columns(2)
    with col1:
        supplier = st.text_input("Supplier", key="beli_supplier")
        no_faktur = st.text_input("No Faktur", key="beli_faktur")
        kode_sku = st.text_input("Kode SKU", key="beli_sku")
        nama_barang = st.text_input("Nama Barang", key="beli_nama")
    with col2:
        qty = st.number_input("Qty", min_value=1, value=1, key="beli_qty")
        harga = st.number_input("Harga Beli (Rp)", min_value=0, step=1000, key="beli_harga")
        total = qty * harga
        st.metric("Total", f"Rp {total:,.0f}")
        status = st.selectbox("Status Bayar", ["PENDING", "LUNAS", "KONTRA BON"], key="beli_status")

    if st.button("💾 Simpan Pembelian", type="primary") and supplier and kode_sku:
        tgl = datetime.now().strftime("%d-%m-%Y")
        db.execute("INSERT INTO pembelian (no_faktur,tanggal,supplier,kode_sku,nama_barang,qty,harga_beli,total_harga,status_bayar) VALUES (?,?,?,?,?,?,?,?,?)",
                   (no_faktur, tgl, supplier, kode_sku, nama_barang, qty, harga, total, status))
        # Update stok
        existing = db.fetch_one("SELECT stok FROM sku WHERE kode_sku=?", (kode_sku,))
        if existing:
            db.execute("UPDATE sku SET stok=stok+?, updated_at=CURRENT_TIMESTAMP WHERE kode_sku=?", (qty, kode_sku))
        st.success(f"✅ Pembelian {no_faktur} tersimpan! Stok +{qty}")
        st.rerun()

with tab2:
    st.subheader("💸 Input Biaya Operasional (OPEX)")
    col_o1, col_o2 = st.columns(2)
    with col_o1:
        opex_kat = st.selectbox("Kategori", ["Bubble Wrap","Kardus","Lakban","Bensin","Gaji","Internet","Listrik","Air","Sewa","Maintenance","ATK","Lainnya"], key="opex_kat")
        opex_desc = st.text_input("Deskripsi", key="opex_desc")
        opex_tipe = st.selectbox("Tipe", ["VARIABLE", "TETAP"], key="opex_tipe")
    with col_o2:
        opex_jumlah = st.number_input("Jumlah (Rp)", min_value=0, step=10000, key="opex_jumlah")
        opex_status = st.selectbox("Status Bayar", ["PENDING", "LUNAS"], key="opex_status")

    if st.button("💾 Simpan OPEX", type="primary") and opex_desc and opex_jumlah > 0:
        tgl = datetime.now().strftime("%d-%m-%Y")
        db.execute("INSERT INTO opex (kategori,deskripsi,total_harga,tanggal,status_bayar,tipe) VALUES (?,?,?,?,?,?)",
                   (opex_kat, opex_desc, opex_jumlah, tgl, opex_status, opex_tipe))
        st.success(f"✅ OPEX {opex_desc} tersimpan!")
        st.rerun()

    opex_list = db.fetch_all("SELECT * FROM opex ORDER BY id DESC LIMIT 30")
    if opex_list:
        st.dataframe(pd.DataFrame([dict(r) for r in opex_list]), width="stretch", hide_index=True)
