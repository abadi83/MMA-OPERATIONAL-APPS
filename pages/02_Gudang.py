"""Gudang Inventory Page"""
import streamlit as st
st.set_page_config(page_title="ðŸ“¦ Gudang", page_icon="ðŸ“¦", layout="wide")

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
st.title("📦 Gudang Inventory SKU")

tab1, tab2, tab3 = st.tabs(["📊 Stok", "🔍 Stock Opname", "🗄️ Rak"])

with tab1:
    search = st.text_input("Cari SKU", key="gudang_search")
    where = f"WHERE kode_sku LIKE '%{search}%' OR nama_barang LIKE '%{search}%'" if search else ""
    rows = db.fetch_all(f"SELECT kode_sku, nama_barang, kategori, stok, satuan, harga_beli, posisi_rak FROM sku {where} ORDER BY nama_barang LIMIT 200")
    if rows:
        df = pd.DataFrame([dict(r) for r in rows])
        c1, c2, c3 = st.columns(3)
        c1.metric("Total SKU", len(df))
        c2.metric("Total Stok", df["stok"].sum())
        c3.metric("Low Stock (≤5)", len(df[df["stok"] <= 5]))
        st.dataframe(df, width="stretch", height=400, hide_index=True)

with tab2:
    sku_list = [r["kode_sku"] for r in db.fetch_all("SELECT kode_sku FROM sku ORDER BY kode_sku LIMIT 500")]
    op_sku = st.selectbox("Pilih SKU", sku_list, key="opname_sku") if sku_list else None
    if op_sku:
        info = db.fetch_one("SELECT * FROM sku WHERE kode_sku=?", (op_sku,))
        if info:
            st.info(f"📦 {info['nama_barang']} | Stok: {info['stok']} | Rak: {info['posisi_rak'] or '-'}")
            stok_fisik = st.number_input("Stok Fisik", min_value=0, value=info["stok"], key="op_fisik")
            selisih = stok_fisik - info["stok"]
            if selisih != 0: st.metric("Selisih", f"{selisih:+d}")
            if st.button("💾 Simpan Opname") and stok_fisik != info["stok"]:
                db.execute("INSERT INTO stock_opname (kode_sku,stok_sistem,stok_fisik,selisih,tanggal) VALUES (?,?,?,?,?)",
                           (op_sku, info["stok"], stok_fisik, selisih, datetime.now().strftime("%d-%m-%Y %H:%M")))
                db.execute("UPDATE sku SET stok=?, updated_at=CURRENT_TIMESTAMP WHERE kode_sku=?", (stok_fisik, op_sku))
                st.success("✅ Opname tersimpan!")
                st.rerun()

with tab3:
    st.subheader("🗄️ Rak")
    kode = st.text_input("Kode Rak", key="rak_kode")
    nama = st.text_input("Nama Rak", key="rak_nama")
    if st.button("➕ Tambah Rak") and kode and nama:
        try:
            db.execute("INSERT INTO rak_gudang (kode,nama) VALUES (?,?)", (kode.upper(), nama))
            st.success(f"✅ Rak {kode} ditambahkan!")
            st.rerun()
        except: st.error("Kode sudah ada!")
    rak_list = db.fetch_all("SELECT * FROM rak_gudang ORDER BY kode")
    if rak_list:
        for r in rak_list:
            items = db.fetch_all("SELECT kode_sku, nama_barang, stok FROM sku WHERE posisi_rak=?", (r["kode"],))
            with st.expander(f"🗄️ {r['kode']} - {r['nama']} ({len(items)} SKU)"):
                if items: st.dataframe(pd.DataFrame([dict(i) for i in items]), width="stretch", hide_index=True)
    # Unassigned
    unassigned = db.fetch_all("SELECT kode_sku, nama_barang FROM sku WHERE posisi_rak='' OR posisi_rak IS NULL")
    if unassigned:
        st.warning(f"⚠️ {len(unassigned)} SKU belum punya rak!")
        st.dataframe(pd.DataFrame([dict(r) for r in unassigned]), width="stretch", hide_index=True)
