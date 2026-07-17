"""Master Data Page - SKU, Supplier, Toko"""
import streamlit as st
st.set_page_config(page_title="🗄️ Master Data", page_icon="🗄️", layout="wide")

from app import *
import pandas as pd

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("pages/00_Login.py")
    st.stop()

db = st.session_state.db
user = st.session_state.user
_auto_amortisasi_bulanan(db)
render_sidebar()

tab1, tab2, tab3 = st.tabs(["🏷️ SKU", "🏪 Supplier", "🏬 Toko"])

with tab1:
    st.subheader("🏷️ Manajemen SKU")
    col1, col2 = st.columns(2)
    with col1:
        sku_kode = st.text_input("Kode SKU", key="sku_kode")
        sku_nama = st.text_input("Nama Barang", key="sku_nama")
        sku_kat = st.text_input("Kategori", key="sku_kat")
    with col2:
        sku_stok = st.number_input("Stok Awal", min_value=0, value=0, key="sku_stok")
        sku_beli = st.number_input("Harga Modal", min_value=0, step=1000, key="sku_beli")
        sku_jual = st.number_input("Harga Jual", min_value=0, step=1000, key="sku_jual")

    if st.button("💾 Simpan/Tambah SKU", type="primary") and sku_kode and sku_nama:
        try:
            db.execute("INSERT INTO sku (kode_sku,nama_barang,kategori,stok,harga_beli,harga_jual) VALUES (?,?,?,?,?,?)",
                       (sku_kode.upper(), sku_nama, sku_kat, sku_stok, sku_beli, sku_jual))
            st.success(f"✅ SKU {sku_kode} ditambahkan!")
        except:
            db.execute("UPDATE sku SET nama_barang=?,kategori=?,harga_beli=?,harga_jual=?,updated_at=CURRENT_TIMESTAMP WHERE kode_sku=?",
                       (sku_nama, sku_kat, sku_beli, sku_jual, sku_kode.upper()))
            st.success(f"✅ SKU {sku_kode} diupdate!")
        st.rerun()

    sku_list = db.fetch_all("SELECT * FROM sku ORDER BY kode_sku LIMIT 100")
    if sku_list:
        st.dataframe(pd.DataFrame([dict(r) for r in sku_list]), width="stretch", height=400, hide_index=True)

with tab2:
    st.subheader("🏪 Supplier")
    s_name = st.text_input("Nama Supplier", key="sup_name")
    s_kontak = st.text_input("Kontak", key="sup_kontak")
    if st.button("➕ Tambah Supplier") and s_name:
        try:
            db.execute("INSERT INTO supplier (nama,kontak) VALUES (?,?)", (s_name, s_kontak))
            st.success(f"✅ {s_name} ditambahkan!")
        except:
            st.error("Supplier sudah ada!")

    sup_list = db.fetch_all("SELECT * FROM supplier ORDER BY nama")
    if sup_list:
        st.dataframe(pd.DataFrame([dict(r) for r in sup_list]), width="stretch", hide_index=True)

with tab3:
    st.subheader("🏬 Toko / Cabang")
    t_name = st.text_input("Nama Toko", key="toko_name")
    if st.button("➕ Tambah Toko") and t_name:
        try:
            db.execute("INSERT INTO toko (nama) VALUES (?)", (t_name,))
            st.success(f"✅ {t_name} ditambahkan!")
        except:
            st.error("Toko sudah ada!")

    toko_list = db.fetch_all("SELECT * FROM toko ORDER BY nama")
    if toko_list:
        st.dataframe(pd.DataFrame([dict(r) for r in toko_list]), width="stretch", hide_index=True)
