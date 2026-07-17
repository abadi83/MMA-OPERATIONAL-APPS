"""Aset & Modal Page"""
import streamlit as st
st.set_page_config(page_title="ðŸ—ï¸ Aset & Modal", page_icon="ðŸ—ï¸", layout="wide")

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
render_sidebar()

tab1, tab2 = st.tabs(["ðŸ—ï¸ Aset Tetap", "ðŸ’° Modal & Pinjaman"])

with tab1:
    st.subheader("ðŸ—ï¸ Aset Tetap & Depresiasi")
    col1, col2 = st.columns(2)
    with col1:
        a_nama = st.text_input("Nama Aset", key="aset_nama")
        a_harga = st.number_input("Harga Perolehan (Rp)", min_value=0, step=100000, key="aset_harga")
        a_masa = st.number_input("Masa Manfaat (tahun)", min_value=1, value=4, key="aset_masa")
    with col2:
        a_tgl = st.date_input("Tanggal Perolehan", datetime.now(), key="aset_tgl")
        a_sisa = st.number_input("Nilai Sisa (Rp)", min_value=0, step=100000, key="aset_sisa")

    if st.button("âž• Tambah Aset", type="primary") and a_nama and a_harga > 0:
        db.execute("INSERT INTO aset_tetap (nama_aset,tanggal_perolehan,harga_perolehan,masa_manfaat,nilai_sisa) VALUES (?,?,?,?,?)",
                   (a_nama, a_tgl.strftime("%d-%m-%Y"), a_harga, a_masa, a_sisa))
        st.success(f"âœ… Aset {a_nama} ditambahkan!")
        st.rerun()

    aset_list = db.fetch_all("SELECT * FROM aset_tetap ORDER BY id DESC")
    if aset_list:
        df_a = pd.DataFrame([dict(r) for r in aset_list])
        df_a["Nilai Buku"] = df_a["harga_perolehan"] - df_a["akumulasi_depresiasi"]
        st.dataframe(df_a, width="stretch", hide_index=True)

with tab2:
    st.subheader("ðŸ’° Modal & Pinjaman")
    # Modal
    st.caption("Modal Disetor")
    m_jumlah = st.number_input("Jumlah Modal (Rp)", min_value=0, step=1000000, key="modal_jumlah")
    m_ket = st.text_input("Keterangan", key="modal_ket")
    if st.button("âž• Tambah Modal") and m_jumlah > 0:
        db.execute("INSERT INTO modal (jenis,tanggal,jumlah,keterangan) VALUES (?,?,?,?)",
                   ("TAMBAHAN", datetime.now().strftime("%d-%m-%Y"), m_jumlah, m_ket))
        st.success("âœ… Modal ditambahkan!")
        st.rerun()

    modal_list = db.fetch_all("SELECT * FROM modal ORDER BY id DESC LIMIT 10")
    if modal_list:
        st.dataframe(pd.DataFrame([dict(r) for r in modal_list]), width="stretch", hide_index=True)

    # Pinjaman
    st.divider()
    st.caption("Pinjaman Bank")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        p_bank = st.text_input("Nama Bank", key="pinj_bank")
        p_pokok = st.number_input("Pokok Pinjaman (Rp)", min_value=0, step=1000000, key="pinj_pokok")
        p_bunga = st.number_input("Bunga (%/tahun)", min_value=0.0, value=6.0, step=0.5, key="pinj_bunga")
    with col_p2:
        p_tenor = st.number_input("Tenor (bulan)", min_value=1, value=12, key="pinj_tenor")
        p_cicilan = st.number_input("Cicilan/Bulan (Rp)", min_value=0, step=100000, key="pinj_cicilan")
        p_tgl = st.date_input("Tanggal Mulai", datetime.now(), key="pinj_tgl")

    if st.button("âž• Tambah Pinjaman") and p_bank and p_pokok > 0:
        db.execute("INSERT INTO pinjaman (nama_bank,pokok,bunga_persen,tenor_bulan,cicilan_per_bulan,tanggal_mulai,sisa_pokok) VALUES (?,?,?,?,?,?,?)",
                   (p_bank, p_pokok, p_bunga, p_tenor, p_cicilan, p_tgl.strftime("%d-%m-%Y"), p_pokok))
        st.success("âœ… Pinjaman ditambahkan!")
        st.rerun()

    pinj_list = db.fetch_all("SELECT * FROM pinjaman ORDER BY id DESC")
    if pinj_list:
        st.dataframe(pd.DataFrame([dict(r) for r in pinj_list]), width="stretch", hide_index=True)
