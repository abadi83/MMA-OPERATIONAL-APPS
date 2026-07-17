"""Scan Operasional Page"""
import streamlit as st
st.set_page_config(page_title="ðŸ“· Scan Ops", page_icon="ðŸ“¦", layout="wide")

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); from modules.shared import *
import pandas as pd
from datetime import datetime

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("pages/00_Login.py")
    st.stop()

db = st.session_state.db
cache = st.session_state.cache
user = st.session_state.user
auto_amortisasi_bulanan(db)
render_sidebar()
st.session_state.page = "Scan_Operasional"

# â”€â”€ Scan Operational (compact version) â”€â”€
st.title("ðŸ“· SCAN Operasional - Packing & Verifikasi")
st.caption("Scan resi fisik untuk verifikasi packing.")

# Stats
col1, col2, col3, col4 = st.columns(4)
p = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status='PACKED'")
col1.metric("âœ… Packed", f"{p['cnt']:,}" if p else "0")
pe = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status='PENDING'")
col2.metric("â³ Pending", f"{pe['cnt']:,}" if pe else "0")
c = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status='CANCEL'")
col3.metric("âŒ Cancel", f"{c['cnt']:,}" if c else "0")
o = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan")
col4.metric("ðŸ“¦ Orders", f"{o['cnt']:,}" if o else "0")

# Scan mode
scan_mode = st.radio("Mode", ["ðŸ“¦ PACK", "ðŸš€ INSTANT", "âŒ CANCEL"], horizontal=True, key="scan_ops_mode")
kategori = "BESAR" if st.checkbox("ðŸ“¦ Barang Besar", key="scan_ops_besar") else "REGULER"
tipe_kiriman = "INSTANT" if scan_mode == "ðŸš€ INSTANT" else "REGULER"

# Scan input
col_s1, col_s2 = st.columns([4, 1])
with col_s1:
    resi_input = st.text_input("Scan barcode / ketik resi", placeholder="Scan resi...", key="scan_ops_resi", label_visibility="collapsed")
with col_s2:
    scan_btn = st.button("ðŸ“· Scan" if scan_mode == "ðŸ“¦ PACK" else ("ðŸš€ Instant" if scan_mode == "ðŸš€ INSTANT" else "âŒ Cancel"), type="primary", width="stretch")

selected_toko = st.session_state.get("selected_store", "Mitra Mulia Abadi")
keterangan_barang = ""

if resi_input or scan_btn:
    cleaned = resi_input.strip() if resi_input else ""
    if cleaned:
        cleaned = Validator.sanitize_resi(cleaned)
        if not cleaned:
            st.error("Format resi tidak valid!")
        else:
            # Duplicate check
            dup = db.fetch_one("SELECT id, status FROM scan_aktif WHERE resi = ?", (cleaned,))
            if dup:
                st.warning(f"ðŸš« Sudah di-scan: {dup['status']}")
            else:
                now = datetime.now()
                waktu, tanggal = now.strftime("%H:%M:%S"), now.strftime("%d-%m-%Y")
                if scan_mode == "âŒ CANCEL":
                    db.execute("INSERT INTO scan_aktif (waktu,tanggal,resi,ekspedisi,toko,status,kategori,tipe_kiriman) VALUES (?,?,?,?,?,?,?,?)",
                               (waktu, tanggal, cleaned, "CANCEL", selected_toko, "CANCEL", "REGULER", "REGULER"))
                    st.error(f"âŒ CANCEL: {cleaned}")
                else:
                    match = db.fetch_one("SELECT no_resi, no_pesanan, marketplace, nama_produk, sku_terdeteksi, kurir, nama_toko FROM penjualan WHERE no_resi = ? OR no_pesanan = ? LIMIT 1", (cleaned, cleaned))
                    if match:
                        real_resi = match["no_resi"] or cleaned
                        scan_toko = match["nama_toko"] or selected_toko
                        db.execute("INSERT INTO scan_aktif (waktu,tanggal,resi,ekspedisi,toko,status,kategori,keterangan_barang,tipe_kiriman,marketplace) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                   (waktu, tanggal, real_resi, match["kurir"] or "Unknown", scan_toko, "PACKED", kategori, keterangan_barang, tipe_kiriman, match["marketplace"] or ""))
                        db.execute("UPDATE penjualan SET status_pesanan='PACKED' WHERE no_resi=? OR no_pesanan=?", (real_resi, match["no_pesanan"]))
                        post_packed_to_accounting(db, real_resi, tanggal)
                        st.success(f"âœ… PACKED: {real_resi} | {match['marketplace']} | {match['nama_produk'][:40]}")
                    else:
                        db.execute("INSERT INTO scan_aktif (waktu,tanggal,resi,ekspedisi,toko,status,kategori,tipe_kiriman) VALUES (?,?,?,?,?,?,?,?)",
                                   (waktu, tanggal, cleaned, "Unknown", selected_toko, "PENDING", kategori, tipe_kiriman))
                        st.warning(f"â³ PENDING: {cleaned} - tidak ada di data penjualan")
                st.session_state.scan_ops_resi = ""

# Recent scans
st.divider()
st.subheader("ðŸ“‹ Scan Terbaru")
scans = db.fetch_all("SELECT s.waktu, s.tanggal, s.resi, s.status, p.marketplace, p.nama_produk FROM scan_aktif s LEFT JOIN penjualan p ON s.resi=p.no_resi ORDER BY s.id DESC LIMIT 10")
if scans:
    st.dataframe(pd.DataFrame([dict(r) for r in scans]), width="stretch", hide_index=True)
