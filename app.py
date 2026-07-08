"""
iScan Pro - Streamlit Edition
Aplikasi scanning resi pengiriman oleh MMA (Mitra Mulia Abadi)
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import os
import sys
import time
import re
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Import custom modules
from config import Config, Theme
from constants import (
    APP_NAME, APP_VERSION, ScanStatus, DEFAULT_EXPEDITIONS,
)
from validators import Validator, validate_resi_or_raise
from exceptions import DatabaseError, ValidationError


# ==================== PAGE CONFIG ====================
st.set_page_config(
    page_title=f"{APP_NAME}",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ==================== DATABASE ====================
class Database:
    """Thread-safe SQLite database wrapper."""

    def __init__(self):
        self.db_path = Config.DB_PATH
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def execute(self, query: str, params=None):
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()
            return cursor
        except sqlite3.Error as e:
            conn.rollback()
            raise DatabaseError(f"Database error: {e}")
        finally:
            conn.close()

    def fetch_all(self, query: str, params=None) -> list:
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Database error: {e}")
        finally:
            conn.close()

    def fetch_one(self, query: str, params=None):
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchone()
        except sqlite3.Error as e:
            raise DatabaseError(f"Database error: {e}")
        finally:
            conn.close()

    def _init_db(self):
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS toko (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT UNIQUE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ekspedisi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT UNIQUE,
                    prefix TEXT,
                    keterangan TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS list_arsip (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    judul TEXT,
                    nama_file TEXT,
                    tanggal TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_aktif (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    waktu TEXT,
                    tanggal TEXT,
                    resi TEXT UNIQUE,
                    ekspedisi TEXT,
                    toko TEXT,
                    status TEXT DEFAULT 'KIRIM',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user TEXT,
                    action TEXT,
                    details TEXT,
                    resi TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sku (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kode_sku TEXT UNIQUE NOT NULL,
                    nama_barang TEXT NOT NULL,
                    kategori TEXT DEFAULT '',
                    stok INTEGER DEFAULT 0,
                    satuan TEXT DEFAULT 'pcs',
                    harga_beli REAL DEFAULT 0,
                    harga_jual REAL DEFAULT 0,
                    supplier TEXT DEFAULT '',
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pembelian (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    no_faktur TEXT NOT NULL,
                    tanggal TEXT NOT NULL,
                    supplier TEXT NOT NULL,
                    kode_sku TEXT NOT NULL,
                    nama_barang TEXT NOT NULL,
                    qty INTEGER NOT NULL DEFAULT 0,
                    satuan TEXT DEFAULT 'pcs',
                    harga_beli REAL DEFAULT 0,
                    total_harga REAL DEFAULT 0,
                    keterangan TEXT DEFAULT '',
                    metode_bayar TEXT DEFAULT 'Transfer',
                    status_bayar TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: add columns if they don't exist (for existing databases)
            try:
                cursor.execute("ALTER TABLE pembelian ADD COLUMN metode_bayar TEXT DEFAULT 'Transfer'")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                cursor.execute("ALTER TABLE pembelian ADD COLUMN status_bayar TEXT DEFAULT 'PENDING'")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Migration: update existing NULL status_bayar to PENDING
            try:
                cursor.execute("UPDATE pembelian SET status_bayar = 'PENDING' WHERE status_bayar IS NULL OR status_bayar = ''")
            except:
                pass

            # Migration: add kategori column to scan_aktif (REGULER / BESAR)
            try:
                cursor.execute("ALTER TABLE scan_aktif ADD COLUMN kategori TEXT DEFAULT 'REGULER'")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Migration: update existing NULL kategori to REGULER
            try:
                cursor.execute("UPDATE scan_aktif SET kategori = 'REGULER' WHERE kategori IS NULL OR kategori = ''")
            except:
                pass

            # Migration: add keterangan_barang column to scan_aktif
            try:
                cursor.execute("ALTER TABLE scan_aktif ADD COLUMN keterangan_barang TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Migration: add tipe_kiriman column to scan_aktif (REGULER / INSTANT)
            try:
                cursor.execute("ALTER TABLE scan_aktif ADD COLUMN tipe_kiriman TEXT DEFAULT 'REGULER'")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Migration: add marketplace column to scan_aktif
            try:
                cursor.execute("ALTER TABLE scan_aktif ADD COLUMN marketplace TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # Column already exists

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daftar_barang_besar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama_barang TEXT NOT NULL,
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS penjualan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    marketplace TEXT NOT NULL,
                    no_pesanan TEXT NOT NULL,
                    no_resi TEXT DEFAULT '',
                    tanggal_pesanan TEXT DEFAULT '',
                    tanggal_pengiriman TEXT DEFAULT '',
                    sku_terdeteksi TEXT DEFAULT '',
                    nama_produk TEXT DEFAULT '',
                    qty INTEGER DEFAULT 1,
                    harga_jual REAL DEFAULT 0,
                    total_harga REAL DEFAULT 0,
                    nama_pembeli TEXT DEFAULT '',
                    nama_toko TEXT DEFAULT '',
                    kurir TEXT DEFAULT '',
                    status_pesanan TEXT DEFAULT '',
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: add columns if not exists
            try:
                cursor.execute("ALTER TABLE penjualan ADD COLUMN nama_toko TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE penjualan ADD COLUMN kurir TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            # Insert defaults if empty
            cursor.execute("SELECT COUNT(*) FROM ekspedisi")
            if cursor.fetchone()[0] == 0:
                for nama, prefix, ket in DEFAULT_EXPEDITIONS:
                    cursor.execute(
                        "INSERT OR IGNORE INTO ekspedisi (nama, prefix, keterangan) VALUES (?, ?, ?)",
                        (nama, prefix, ket),
                    )

            cursor.execute("SELECT COUNT(*) FROM toko")
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO toko (nama) VALUES (?)", ("Mitra Mulia Abadi",))

            conn.commit()
        finally:
            conn.close()


# ==================== CACHE ====================
class ExpeditionCache:
    """Cache for expedition data."""

    def __init__(self, db: Database):
        self.db = db
        self.expeditions = []
        self.last_update = 0
        self.cache_duration = 300

    def get_expeditions(self) -> list:
        now = time.time()
        if not self.expeditions or (now - self.last_update) > self.cache_duration:
            rows = self.db.fetch_all("SELECT nama, prefix FROM ekspedisi WHERE prefix != ''")
            self.expeditions = [(r["nama"], r["prefix"]) for r in rows]
            self.last_update = now
        return self.expeditions

    def invalidate(self):
        self.expeditions = []
        self.last_update = 0


# ==================== SESSION STATE INIT ====================
def init_session():
    """Initialize session state."""
    if "db" not in st.session_state:
        st.session_state.db = Database()
    if "cache" not in st.session_state:
        st.session_state.cache = ExpeditionCache(st.session_state.db)
    if "scan_mode" not in st.session_state:
        st.session_state.scan_mode = "KIRIM"  # KIRIM or RETUR
    if "selected_store" not in st.session_state:
        stores = st.session_state.db.fetch_all("SELECT nama FROM toko ORDER BY nama")
        st.session_state.selected_store = stores[0]["nama"] if stores else "Mitra Mulia Abadi"
    if "last_scan" not in st.session_state:
        st.session_state.last_scan = None
    if "main_menu" not in st.session_state:
        st.session_state.main_menu = "Operasional"
    if "page" not in st.session_state:
        st.session_state.page = "Dashboard"


# ==================== HELPER FUNCTIONS ====================
def detect_expedition(resi: str, cache: ExpeditionCache) -> str:
    """Detect expedition from resi number prefix."""
    expeditions = cache.get_expeditions()
    r = resi.upper().strip()
    for nama, prefix_str in expeditions:
        if not prefix_str:
            continue
        prefixes = [p.strip() for p in prefix_str.split(",") if p.strip()]
        for prefix in prefixes:
            if r.startswith(prefix):
                return nama
    return "LAINNYA"


def get_active_scans(db: Database) -> list:
    """Get all active scan data as list of dicts."""
    rows = db.fetch_all(
        "SELECT id, waktu, tanggal, resi, ekspedisi, toko, status FROM scan_aktif ORDER BY id DESC"
    )
    return [dict(r) for r in rows]


def get_stats(db: Database):
    """Get scan statistics — diselaraskan dengan Scan Operasional (PACKED/PENDING/CANCEL)."""
    rows = db.fetch_all("SELECT status, COUNT(*) as cnt FROM scan_aktif GROUP BY status")
    stats = {"KIRIM": 0, "RETUR": 0, "PENDING": 0, "PACKED": 0, "CANCEL": 0}

    for r in rows:
        if r["status"] in stats:
            stats[r["status"]] = r["cnt"]
        elif r["status"] == "PENDING":
            stats["PENDING"] = r["cnt"]
        elif r["status"] == "CANCEL":
            stats["CANCEL"] = r["cnt"]

    stats["TOTAL_SCAN"] = sum(stats.values())

    # Total resi unik dari penjualan (yang ada no_resi)
    total_penjualan = db.fetch_one("SELECT COUNT(DISTINCT no_resi) as cnt FROM penjualan WHERE no_resi != '' AND no_resi IS NOT NULL")
    stats["TOTAL_SALES"] = total_penjualan["cnt"] if total_penjualan else 0

    # Belum discan = total penjualan - packed - cancel
    stats["BELUM_SCAN"] = max(0, stats["TOTAL_SALES"] - stats["PACKED"] - stats["CANCEL"])

    # ── Breakdown per kategori ──
    kategori_rows = db.fetch_all("SELECT kategori, COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED' GROUP BY kategori")
    stats["PACKED_REGULER"] = 0
    stats["PACKED_BESAR"] = 0
    for kr in kategori_rows:
        if kr["kategori"] == "BESAR":
            stats["PACKED_BESAR"] = kr["cnt"]
        else:
            stats["PACKED_REGULER"] += kr["cnt"]

    # ── Instant ──
    instant_row = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED' AND tipe_kiriman = 'INSTANT'")
    stats["INSTANT"] = instant_row["cnt"] if instant_row else 0

    return stats


def scan_resi(resi: str, mode: str, store: str, db: Database, cache: ExpeditionCache) -> dict:
    """Process a single resi scan.

    Returns:
        dict with 'success', 'message', 'data' keys
    """
    # Validate
    cleaned = Validator.sanitize_resi(resi)
    if not cleaned:
        return {"success": False, "message": f"Format resi tidak valid: '{resi}'"}

    # Check duplicate
    existing = db.fetch_one("SELECT id FROM scan_aktif WHERE resi = ?", (cleaned,))
    if existing:
        return {"success": False, "message": f"Resi '{cleaned}' sudah ada di scan history!"}

    # Detect expedition
    ekspedisi = detect_expedition(cleaned, cache)

    # Determine status
    status = ScanStatus.RETUR if mode == "RETUR" else ScanStatus.KIRIM

    # Current time
    now = datetime.now()
    waktu = now.strftime("%H:%M:%S")
    tanggal = now.strftime("%d-%m-%Y")

    # Insert
    try:
        db.execute(
            "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, status) VALUES (?, ?, ?, ?, ?, ?)",
            (waktu, tanggal, cleaned, ekspedisi, store, status),
        )
        return {
            "success": True,
            "message": f"✓ {cleaned} → {ekspedisi} ({status})",
            "data": {"waktu": waktu, "tanggal": tanggal, "resi": cleaned, "ekspedisi": ekspedisi, "toko": store, "status": status},
        }
    except Exception as e:
        return {"success": False, "message": f"Gagal insert: {str(e)}"}


def delete_scan_by_resi(resi: str, db: Database) -> bool:
    """Delete a scan entry by resi number, and revert penjualan status."""
    cleaned = Validator.sanitize_resi(resi)
    if not cleaned:
        return False
    # Revert penjualan status_pesanan ke semula (kosongkan)
    db.execute("UPDATE penjualan SET status_pesanan = '' WHERE no_resi = ?", (cleaned,))
    db.execute("DELETE FROM scan_aktif WHERE resi = ?", (cleaned,))
    return True


def delete_last_scan(db: Database) -> bool:
    """Delete the most recent scan entry, and revert penjualan status."""
    row = db.fetch_one("SELECT id, resi FROM scan_aktif ORDER BY id DESC LIMIT 1")
    if row:
        # Revert penjualan status_pesanan
        db.execute("UPDATE penjualan SET status_pesanan = '' WHERE no_resi = ?", (row["resi"],))
        db.execute("DELETE FROM scan_aktif WHERE id = ?", (row["id"],))
        return True
    return False


def toggle_pending_status(resi: str, db: Database):
    """Toggle a scan entry between PENDING and KIRIM status."""
    cleaned = Validator.sanitize_resi(resi)
    if not cleaned:
        return None
    row = db.fetch_one("SELECT id, status FROM scan_aktif WHERE resi = ?", (cleaned,))
    if not row:
        return None
    new_status = ScanStatus.KIRIM if row["status"] == ScanStatus.PENDING else ScanStatus.PENDING
    db.execute("UPDATE scan_aktif SET status = ? WHERE id = ?", (new_status, row["id"]))
    return new_status


def export_to_excel(db: Database, folder: str, judul: str = None) -> str:
    """Export all active scans to Excel and clear them."""
    rows = db.fetch_all(
        "SELECT waktu, tanggal, resi, ekspedisi, toko, status FROM scan_aktif ORDER BY id ASC"
    )

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["Waktu", "Tanggal", "Nomor Resi", "Ekspedisi", "Toko", "Status"])

    now = datetime.now()
    if judul is None:
        judul = f"Arsip_Scan_{now.strftime('%d-%m-%Y_%H%M%S')}"

    filename = f"{judul}.xlsx"
    filepath = os.path.join(folder, filename)

    # Create Excel with formatting
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Scan Data")
        ws = writer.sheets["Scan Data"]
        # Auto-adjust column widths
        for col_idx, col in enumerate(df.columns, 1):
            max_len = max(len(str(col)), df[col].astype(str).str.len().max() or 0)
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 4, 50)

    # Save to archive list
    db.execute(
        "INSERT INTO list_arsip (judul, nama_file, tanggal) VALUES (?, ?, ?)",
        (judul, filename, now.strftime("%d-%m-%Y %H:%M")),
    )

    # Clear active scans — revert penjualan status_pesanan terlebih dahulu
    db.execute(
        "UPDATE penjualan SET status_pesanan = '' WHERE no_resi IN (SELECT resi FROM scan_aktif)"
    )
    db.execute("DELETE FROM scan_aktif")

    return filepath


def export_handover_report(db: Database, folder: str, ekspedisi_filter: str = None) -> str:
    """Generate handover report for a specific expedition (status PACKED)."""
    if ekspedisi_filter:
        rows = db.fetch_all(
            "SELECT waktu, tanggal, resi, ekspedisi, toko, status FROM scan_aktif WHERE ekspedisi = ? AND status = 'PACKED' ORDER BY id ASC",
            (ekspedisi_filter,),
        )
    else:
        rows = db.fetch_all(
            "SELECT waktu, tanggal, resi, ekspedisi, toko, status FROM scan_aktif WHERE status = 'PACKED' ORDER BY ekspedisi, id ASC"
        )

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["Waktu", "Tanggal", "Nomor Resi", "Ekspedisi", "Toko", "Status"])

    now = datetime.now()
    exp_label = ekspedisi_filter.replace(" ", "_") if ekspedisi_filter else "Semua"
    judul = f"Handover_{exp_label}_{now.strftime('%d-%m-%Y_%H%M%S')}"
    filename = f"{judul}.xlsx"
    filepath = os.path.join(folder, filename)

    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Handover")
        ws = writer.sheets["Handover"]
        for col_idx, col in enumerate(df.columns, 1):
            max_len = max(len(str(col)), df[col].astype(str).str.len().max() or 0)
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 4, 50)

    return filepath


# ==================== UI COMPONENTS ====================
def render_stats_cards(stats: dict):
    """Render statistics cards — diselaraskan dengan Scan Operasional."""
    cols = st.columns(5)
    with cols[0]:
        st.metric("📦 Pesanan dgn Resi", f"{stats.get('TOTAL_SALES', 0):,}")
    with cols[1]:
        st.metric("✅ Packed", f"{stats.get('PACKED', 0):,}")
    with cols[2]:
        st.metric("⏳ Pending Scan", f"{stats.get('PENDING', 0):,}")
    with cols[3]:
        st.metric("❌ Cancel", f"{stats.get('CANCEL', 0):,}")
    with cols[4]:
        st.metric("📋 Belum Scan", f"{stats.get('BELUM_SCAN', 0):,}")


def render_scan_input():
    """Render the scan input section."""
    db = st.session_state.db
    cache = st.session_state.cache

    # Mode & Store selectors in one row
    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        mode = st.radio(
            "Mode Scan",
            ["KIRIM", "RETUR"],
            horizontal=True,
            index=0 if st.session_state.scan_mode == "KIRIM" else 1,
            key="scan_mode_radio",
        )
        st.session_state.scan_mode = mode

    with col2:
        stores = [r["nama"] for r in db.fetch_all("SELECT nama FROM toko ORDER BY nama")]
        if not stores:
            stores = ["Mitra Mulia Abadi"]
        selected = st.selectbox(
            "Toko",
            stores,
            index=stores.index(st.session_state.selected_store) if st.session_state.selected_store in stores else 0,
            key="store_select",
        )
        st.session_state.selected_store = selected

    with col3:
        st.write("")  # spacer
        st.write("")
        if st.button("🔄 Refresh Data", width="stretch"):
            st.rerun()

    # Scan input
    st.markdown("---")
    scan_col1, scan_col2 = st.columns([4, 1])

    with scan_col1:
        resi_input = st.text_input(
            "Scan barcode atau ketik nomor resi",
            placeholder="Masukkan nomor resi lalu tekan Enter...",
            key="resi_input",
            label_visibility="collapsed",
        )

    with scan_col2:
        scan_btn = st.button("📷 Scan", width="stretch", type="primary")

    # Process scan
    if resi_input or scan_btn:
        resi_to_scan = resi_input.strip() if resi_input else ""
        if not resi_to_scan and scan_btn:
            st.warning("Masukkan nomor resi terlebih dahulu.")
        elif resi_to_scan:
            result = scan_resi(
                resi_to_scan,
                st.session_state.scan_mode,
                st.session_state.selected_store,
                db,
                cache,
            )
            if result["success"]:
                st.session_state.last_scan = result["data"]
                st.success(result["message"])
                st.rerun()
            else:
                st.error(result["message"])


def render_scan_history():
    """Render the scan history table with actions."""
    db = st.session_state.db

    scans = get_active_scans(db)
    if not scans:
        st.info("📭 Belum ada data scan. Mulai scan resi di halaman Dashboard.")
        return

    df = pd.DataFrame(scans)
    df = df.rename(columns={
        "waktu": "Waktu",
        "tanggal": "Tanggal",
        "resi": "Nomor Resi",
        "ekspedisi": "Ekspedisi",
        "toko": "Toko",
        "status": "Status",
    })

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.multiselect(
            "Filter Status",
            ["KIRIM", "RETUR", "PENDING"],
            default=["KIRIM", "RETUR", "PENDING"],
            key="status_filter",
        )
    with col2:
        all_exp = sorted(df["Ekspedisi"].unique().tolist())
        exp_filter = st.multiselect("Filter Ekspedisi", all_exp, default=[], key="exp_filter")
    with col3:
        search = st.text_input("🔍 Cari Resi", placeholder="Ketik nomor resi...", key="search_resi")

    # Apply filters
    if status_filter:
        df = df[df["Status"].isin(status_filter)]
    if exp_filter:
        df = df[df["Ekspedisi"].isin(exp_filter)]
    if search:
        df = df[df["Nomor Resi"].str.contains(search, case=False, na=False)]

    st.markdown(f"**{len(df)} items** ditampilkan")

    # Color-code status
    def color_status(val):
        if val == "KIRIM":
            return "background-color: #d4edda; color: #155724"
        elif val == "RETUR":
            return "background-color: #f8d7da; color: #721c24"
        elif val == "PENDING":
            return "background-color: #fff3cd; color: #856404"
        return ""

    styled_df = df.style.map(color_status, subset=["Status"])
    st.dataframe(styled_df, width="stretch", height=400, hide_index=True)

    # Action buttons
    st.markdown("---")
    col_a1, col_a2, col_a3, col_a4 = st.columns(4)

    with col_a1:
        delete_resi = st.text_input("Hapus Resi", placeholder="Nomor resi...", key="delete_resi_input")
        if st.button("🗑️ Hapus Resi", width="stretch"):
            if delete_resi.strip():
                if delete_scan_by_resi(delete_resi.strip(), db):
                    st.success(f"Resi '{delete_resi.strip()}' dihapus!")
                    st.rerun()
                else:
                    st.error("Resi tidak ditemukan.")

    with col_a2:
        if st.button("↩️ Undo (Hapus Terakhir)", width="stretch"):
            if delete_last_scan(db):
                st.success("Scan terakhir dihapus!")
                st.rerun()
            else:
                st.warning("Tidak ada data untuk di-undo.")

    with col_a3:
        pending_resi = st.text_input("Toggle Pending", placeholder="Nomor resi...", key="pending_resi_input")
        if st.button("⏳ Toggle Pending", width="stretch"):
            if pending_resi.strip():
                result = toggle_pending_status(pending_resi.strip(), db)
                if result:
                    st.success(f"Status diubah menjadi '{result}'!")
                    st.rerun()
                else:
                    st.error("Resi tidak ditemukan.")

    with col_a4:
        if st.button("🆕 New Session", width="stretch", type="primary"):
            count = len(scans)
            if count > 0:
                if st.warning(f"⚠️ Ada {count} data scan aktif. Simpan dulu ke Archive sebelum New Session."):
                    pass


def render_archive():
    """Render the archive/excel files browser."""
    db = st.session_state.db

    st.subheader("📁 Gudang Arsip Excel")

    # Export current scans
    scans = get_active_scans(db)
    st.markdown(f"**Data scan aktif: {len(scans)} items**")

    col1, col2 = st.columns([2, 1])
    with col1:
        judul = st.text_input(
            "Judul Arsip",
            value=f"Arsip_Scan_{datetime.now().strftime('%d-%m-%Y_%H%M%S')}",
            key="archive_judul",
        )
    with col2:
        st.write("")
        if st.button("💾 Save to Archive (Excel)", width="stretch", type="primary"):
            if not scans:
                st.warning("Tidak ada data untuk di-arsipkan.")
            else:
                filepath = export_to_excel(db, Config.ARSIP_FOLDER, judul)
                if filepath:
                    st.success(f"✅ Arsip tersimpan: {os.path.basename(filepath)}")
                    st.rerun()
                else:
                    st.error("Gagal menyimpan arsip.")

    st.markdown("---")

    # List existing archives
    arsip_list = db.fetch_all("SELECT id, judul, nama_file, tanggal FROM list_arsip ORDER BY id DESC")

    if not arsip_list:
        # Also check folder directly
        if os.path.exists(Config.ARSIP_FOLDER):
            files = [f for f in os.listdir(Config.ARSIP_FOLDER) if f.endswith(".xlsx")]
            if files:
                st.info(f"📂 {len(files)} file Excel ditemukan di folder arsip (belum tercatat di database).")
                for f in sorted(files, reverse=True):
                    filepath = os.path.join(Config.ARSIP_FOLDER, f)
                    size_kb = os.path.getsize(filepath) / 1024
                    mod_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                    col_f1, col_f2 = st.columns([3, 1])
                    with col_f1:
                        st.markdown(f"📄 **{f}** — {size_kb:.1f} KB — {mod_time.strftime('%d-%m-%Y %H:%M')}")
                    with col_f2:
                        with open(filepath, "rb") as fp:
                            st.download_button(
                                "⬇️ Download",
                                fp,
                                file_name=f,
                                key=f"dl_{f}",
                                width="stretch",
                            )
            else:
                st.info("📭 Belum ada arsip. Simpan data scan ke Excel terlebih dahulu.")
        else:
            st.info("📭 Folder arsip belum tersedia.")
    else:
        for arsip in arsip_list:
            filepath = os.path.join(Config.ARSIP_FOLDER, arsip["nama_file"])
            col_a1, col_a2, col_a3 = st.columns([3, 1, 1])
            with col_a1:
                st.markdown(f"📄 **{arsip['judul']}** — _{arsip['tanggal']}_")
                if os.path.exists(filepath):
                    size_kb = os.path.getsize(filepath) / 1024
                    st.caption(f"File: {arsip['nama_file']} ({size_kb:.1f} KB)")
                else:
                    st.caption(f"⚠️ File '{arsip['nama_file']}' tidak ditemukan di disk.")
            with col_a2:
                if os.path.exists(filepath):
                    with open(filepath, "rb") as fp:
                        st.download_button(
                            "⬇️ Download",
                            fp,
                            file_name=arsip["nama_file"],
                            key=f"dl_arsip_{arsip['id']}",
                            width="stretch",
                        )
            with col_a3:
                if st.button("🗑️", key=f"del_arsip_{arsip['id']}", width="stretch"):
                    db.execute("DELETE FROM list_arsip WHERE id = ?", (arsip["id"],))
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    st.success("Arsip dihapus.")
                    st.rerun()
            st.markdown("---")


def render_ekspedisi():
    """Render expedition management page — data dari Scan Operasional."""
    db = st.session_state.db

    st.subheader("🚚 Manajemen Ekspedisi")
    st.caption("Data ekspedisi/kurir diambil dari hasil Scan Operasional & data penjualan.")

    # ── Auto-sync ekspedisi dari scan_aktif & penjualan ──
    kurir_penj = db.fetch_all("SELECT DISTINCT kurir FROM penjualan WHERE kurir != '' AND kurir IS NOT NULL ORDER BY kurir")
    kurir_scan = db.fetch_all("SELECT DISTINCT ekspedisi FROM scan_aktif WHERE ekspedisi != '' AND ekspedisi != 'Unknown' AND ekspedisi IS NOT NULL ORDER BY ekspedisi")
    all_kurir = set()
    for k in kurir_penj:
        all_kurir.add(k["kurir"])
    for k in kurir_scan:
        all_kurir.add(k["ekspedisi"])

    if not all_kurir:
        st.info("📭 Belum ada data ekspedisi. Mulai scan di SCAN Operasional.")
        return

    # ── Summary Cards ──
    st.markdown("### 📊 Ringkasan per Ekspedisi")
    exp_stats = db.fetch_all(
        "SELECT ekspedisi, "
        "COUNT(*) as total, "
        "SUM(CASE WHEN status = 'PACKED' AND tipe_kiriman = 'REGULER' THEN 1 ELSE 0 END) as packed_reg, "
        "SUM(CASE WHEN status = 'PACKED' AND tipe_kiriman = 'INSTANT' THEN 1 ELSE 0 END) as packed_inst, "
        "SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending, "
        "SUM(CASE WHEN status = 'CANCEL' THEN 1 ELSE 0 END) as cancel "
        "FROM scan_aktif WHERE ekspedisi != '' AND ekspedisi != 'Unknown' "
        "GROUP BY ekspedisi ORDER BY total DESC"
    )

    if exp_stats:
        df_exp = pd.DataFrame([dict(r) for r in exp_stats])
        df_exp = df_exp.rename(columns={
            "ekspedisi": "Ekspedisi", "total": "Total Scan",
            "packed_reg": "📦 Reguler", "packed_inst": "🚀 Instant",
            "pending": "⏳ Pending", "cancel": "❌ Cancel",
        })
        st.dataframe(df_exp, width="stretch", hide_index=True)

    # ── Detail per Ekspedisi ──
    st.markdown("---")
    st.subheader("🔍 Detail per Ekspedisi")
    kurir_sorted = sorted(all_kurir)

    selected_kurir = st.selectbox("Pilih Ekspedisi / Kurir", ["Semua"] + kurir_sorted, key="exp_detail_kurir")

    if selected_kurir != "Semua":
        scans = db.fetch_all(
            "SELECT s.waktu, s.tanggal, s.resi, s.toko, s.status, s.tipe_kiriman, s.kategori, "
            "p.marketplace, p.no_pesanan, p.nama_produk "
            "FROM scan_aktif s LEFT JOIN penjualan p ON s.resi = p.no_resi "
            "WHERE s.ekspedisi = ? ORDER BY s.id DESC LIMIT 100",
            (selected_kurir,),
        )
        if scans:
            df_detail = pd.DataFrame([dict(r) for r in scans])
            df_detail = df_detail.rename(columns={
                "waktu": "Waktu", "tanggal": "Tanggal", "resi": "No Resi",
                "toko": "Toko", "status": "Status", "tipe_kiriman": "Tipe",
                "kategori": "Kategori", "marketplace": "MP",
                "no_pesanan": "No Pesanan", "nama_produk": "Produk",
            })
            display = ["Waktu", "No Resi", "Tipe", "Kategori", "MP", "No Pesanan", "Produk", "Toko", "Status"]
            available = [c for c in display if c in df_detail.columns]
            st.dataframe(df_detail[available], width="stretch", height=400, hide_index=True)

            total_kurir = len(scans)
            packed_k = sum(1 for s in scans if s["status"] == "PACKED")
            inst_k = sum(1 for s in scans if s["status"] == "PACKED" and s["tipe_kiriman"] == "INSTANT")
            st.caption(f"Total: {total_kurir} scan | Packed: {packed_k} | 🚀 Instant: {inst_k}")
        else:
            st.info(f"Belum ada scan untuk {selected_kurir}.")

    # ── Ekspedisi dari penjualan (belum di-scan) ──
    st.markdown("---")
    st.subheader("📋 Ekspedisi dari Data Penjualan (belum di-scan)")
    exp_penj = db.fetch_all(
        "SELECT p.kurir, COUNT(DISTINCT p.no_resi) as jml_resi, COUNT(DISTINCT p.no_pesanan) as jml_orders "
        "FROM penjualan p "
        "WHERE p.kurir != '' AND p.no_resi != '' "
        "AND p.no_resi NOT IN (SELECT resi FROM scan_aktif WHERE status IN ('PACKED', 'CANCEL')) "
        "GROUP BY p.kurir ORDER BY jml_resi DESC"
    )
    if exp_penj:
        df_penj = pd.DataFrame([dict(r) for r in exp_penj])
        df_penj = df_penj.rename(columns={
            "kurir": "Kurir", "jml_resi": "Resi Belum Scan", "jml_orders": "Orders",
        })
        st.dataframe(df_penj, width="stretch", hide_index=True)
    else:
        st.caption("Semua resi sudah di-scan atau belum ada data.")


def render_toko():
    """Render store management page."""
    db = st.session_state.db

    st.subheader("🏪 Manajemen Toko")

    # Add new store
    with st.expander("➕ Tambah Toko Baru", expanded=False):
        nama_toko = st.text_input("Nama Toko", key="new_toko_nama")
        if st.button("💾 Simpan Toko", type="primary"):
            if not nama_toko.strip():
                st.error("Nama toko harus diisi!")
            else:
                try:
                    db.execute("INSERT INTO toko (nama) VALUES (?)", (nama_toko.strip(),))
                    st.success(f"Toko '{nama_toko}' ditambahkan!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal menambah toko: {str(e)}")

    st.markdown("---")

    # List stores
    stores = db.fetch_all("SELECT id, nama FROM toko ORDER BY nama")
    st.markdown("### Daftar Toko")

    for store in stores:
        nama_toko = store["nama"]
        # Count scans per status
        packed_cnt = db.fetch_one(
            "SELECT COUNT(*) as cnt FROM scan_aktif WHERE toko = ? AND status = 'PACKED' AND tipe_kiriman = 'REGULER'",
            (nama_toko,),
        )
        instant_cnt = db.fetch_one(
            "SELECT COUNT(*) as cnt FROM scan_aktif WHERE toko = ? AND status = 'PACKED' AND tipe_kiriman = 'INSTANT'",
            (nama_toko,),
        )
        pending_cnt = db.fetch_one(
            "SELECT COUNT(*) as cnt FROM scan_aktif WHERE toko = ? AND status = 'PENDING'",
            (nama_toko,),
        )
        cancel_cnt = db.fetch_one(
            "SELECT COUNT(*) as cnt FROM scan_aktif WHERE toko = ? AND status = 'CANCEL'",
            (nama_toko,),
        )
        # Total orders from penjualan for this store
        penj_cnt = db.fetch_one(
            "SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan WHERE nama_toko = ?",
            (nama_toko,),
        )

        total_scan = (packed_cnt["cnt"] if packed_cnt else 0) + (instant_cnt["cnt"] if instant_cnt else 0) + (pending_cnt["cnt"] if pending_cnt else 0) + (cancel_cnt["cnt"] if cancel_cnt else 0)

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown(f"🏪 **{nama_toko}**")
            p = packed_cnt["cnt"] if packed_cnt else 0
            i = instant_cnt["cnt"] if instant_cnt else 0
            pe = pending_cnt["cnt"] if pending_cnt else 0
            c = cancel_cnt["cnt"] if cancel_cnt else 0
            pj = penj_cnt["cnt"] if penj_cnt else 0
            st.caption(f"📦 Packed: {p} | 🚀 Instant: {i} | ⏳ Pending: {pe} | ❌ Cancel: {c} | 🛒 Orders: {pj}")
        with col2:
            if st.button("✏️ Edit", key=f"edit_toko_{store['id']}"):
                st.session_state.editing_toko = store
                st.rerun()
        with col3:
            if store["nama"] != "Mitra Mulia Abadi":
                if st.button("🗑️", key=f"del_toko_{store['id']}"):
                    if total_scan > 0:
                        st.warning(f"Toko '{nama_toko}' memiliki {total_scan} data scan. Hapus data scan terlebih dahulu.")
                    else:
                        db.execute("DELETE FROM toko WHERE id = ?", (store["id"],))
                        st.success(f"Toko '{nama_toko}' dihapus.")
                        st.rerun()

    # Edit modal
    if "editing_toko" in st.session_state and st.session_state.editing_toko:
        store = st.session_state.editing_toko
        st.markdown("---")
        st.markdown(f"### ✏️ Edit Toko: {store['nama']}")
        edit_nama = st.text_input("Nama Toko", value=store["nama"], key="edit_toko_nama")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Update Toko", type="primary", width="stretch"):
                if not edit_nama.strip():
                    st.error("Nama toko tidak boleh kosong!")
                else:
                    try:
                        db.execute("UPDATE toko SET nama=? WHERE id=?", (edit_nama.strip(), store["id"]))
                        if st.session_state.selected_store == store["nama"]:
                            st.session_state.selected_store = edit_nama.strip()
                        del st.session_state.editing_toko
                        st.success("Toko diupdate!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal update: {str(e)}")
        with col2:
            if st.button("✕ Batal", width="stretch"):
                del st.session_state.editing_toko
                st.rerun()


# ==================== SKU HELPER FUNCTIONS ====================
def _auto_detect_column(excel_cols: list, candidates: list) -> int:
    """Auto-detect the best matching column index from a list of candidate names.

    Args:
        excel_cols: List of Excel column names (first item is empty string).
        candidates: List of candidate keywords to match against column names.

    Returns:
        Index of the best-matching column, or 0 (empty) if no match.
    """
    for col_name in excel_cols[1:]:  # skip empty first
        col_lower = str(col_name).lower().strip().replace(" ", "_").replace("-", "_")
        for candidate in candidates:
            cand_lower = candidate.lower().strip().replace(" ", "_").replace("-", "_")
            if col_lower == cand_lower:
                return excel_cols.index(col_name)
    # Fallback: partial match
    for i, col_name in enumerate(excel_cols):
        if i == 0:
            continue
        col_lower = str(col_name).lower().strip().replace(" ", "_").replace("-", "_")
        for candidate in candidates:
            cand_lower = candidate.lower().strip().replace(" ", "_").replace("-", "_")
            if cand_lower in col_lower or col_lower in cand_lower:
                return i
    return 0


def _parse_number_str(raw: str) -> str:
    """Convert Indonesian/international number string to float-compatible string.

    Handles:
    - Indonesian: "11.205" (thousands) → "11205"
    - Indonesian: "1.234,56" → "1234.56"
    - International: "1,234.56" → "1234.56"
    - Plain: "11205" → "11205"
    """
    s = raw.replace("Rp", "").replace("rp", "").replace(" ", "").strip()
    if not s:
        return "0"

    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # Format: 1.234,56 → Indonesian (dot=thousands, comma=decimal)
        # Check if comma is last separator (Indonesian)
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        if last_comma > last_dot:
            # Indonesian: remove dots, replace comma with dot
            s = s.replace(".", "").replace(",", ".")
        else:
            # International: remove commas, keep dot
            s = s.replace(",", "")
    elif has_comma:
        # Only comma: could be "11205,5" (Indonesian decimal) or "1,234" (international thousands)
        after_comma = s[s.rfind(",") + 1:]
        if len(after_comma) <= 2 and after_comma.isdigit():
            # Indonesian decimal: "11205,5" → "11205.5"
            s = s.replace(",", ".")
        else:
            # International thousands: "1,234" → "1234"
            s = s.replace(",", "")
    elif has_dot:
        # Only dots: could be "11.205" (thousands) or "11.5" (decimal)
        last_dot = s.rfind(".")
        after_dot = s[last_dot + 1:]
        if len(after_dot) == 3 and after_dot.isdigit() and len(s.replace(".", "")) > 3:
            # Looks like thousands: "11.205" → "11205"
            s = s.replace(".", "")
        elif len(after_dot) <= 2 and after_dot.isdigit():
            # Decimal: "11.5" → keep as is
            pass
        else:
            # Ambiguous but likely thousands (e.g., "1.234") → remove dots
            s = s.replace(".", "")

    return s


def _safe_float(val) -> float:
    """Safely convert a value to float, handling Indonesian number format."""
    if val is None:
        return 0.0
    try:
        cleaned = _parse_number_str(str(val))
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val) -> int:
    """Safely convert a value to int, handling Indonesian number format."""
    if val is None:
        return 0
    try:
        cleaned = _parse_number_str(str(val))
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def _safe_str(val, default="") -> str:
    """Safely convert a value to string, returning default on failure."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return str(val).strip()


def bulk_upsert_sku(
    db, df: pd.DataFrame,
    col_kode: str, col_nama: str, col_kat: str, col_stok: str, col_satuan: str,
    col_supplier: str, col_hbeli: str, col_hjual: str, col_ket: str,
    stok_mode: str, update_kosong: bool,
) -> dict:
    """Perform bulk upsert of SKU data from a DataFrame.

    Upsert logic:
    - Match by kode_sku (case-insensitive, uppercase).
    - If exists → UPDATE (merge fields, aggregate stock if mode is 'add').
    - If not exists → INSERT.
    - If stok_mode is 'add' → ADD incoming stock to existing stock.
    - If update_kosong is True → only update fields that have non-empty values in Excel.

    Returns:
        dict with 'inserted', 'updated', 'errors', 'total', 'error_details', 'aggregation_summary'
    """
    is_add_mode = "Tambahkan" in stok_mode
    result = {
        "inserted": 0,
        "updated": 0,
        "errors": 0,
        "total": 0,
        "error_details": [],
        "aggregation_summary": [],
    }

    for idx, row in df.iterrows():
        result["total"] += 1
        try:
            kode = _safe_str(row.get(col_kode)).upper()
            nama = _safe_str(row.get(col_nama))

            if not kode or not nama:
                result["errors"] += 1
                result["error_details"].append(f"Baris {idx + 2}: Kode SKU atau Nama Barang kosong, dilewati.")
                continue

            kat = _safe_str(row.get(col_kat)) if col_kat else ""
            stok_incoming = _safe_int(row.get(col_stok)) if col_stok else 0
            satuan = _safe_str(row.get(col_satuan), "pcs") if col_satuan else "pcs"
            supplier = _safe_str(row.get(col_supplier)) if col_supplier else ""
            hbeli = _safe_float(row.get(col_hbeli)) if col_hbeli else 0.0
            hjual = _safe_float(row.get(col_hjual)) if col_hjual else 0.0
            ket = _safe_str(row.get(col_ket)) if col_ket else ""

            # Check if SKU already exists
            existing = db.fetch_one("SELECT * FROM sku WHERE kode_sku = ?", (kode,))

            if existing:
                # ── UPSERT: Update existing ──
                # Determine new values (merge logic)
                new_nama = nama if not update_kosong or nama else existing["nama_barang"]
                new_kat = kat if not update_kosong or kat else existing["kategori"]
                new_satuan = satuan if not update_kosong or satuan else existing["satuan"]
                new_supplier = supplier if not update_kosong or supplier else existing["supplier"]
                new_hbeli = hbeli if not update_kosong or hbeli > 0 else existing["harga_beli"]
                new_hjual = hjual if not update_kosong or hjual > 0 else existing["harga_jual"]
                new_ket = ket if not update_kosong or ket else existing["keterangan"]

                # Stock handling
                stok_sebelum = existing["stok"] or 0
                if is_add_mode:
                    new_stok = stok_sebelum + stok_incoming
                    selisih = stok_incoming
                else:
                    new_stok = stok_incoming if (not update_kosong or col_stok) else stok_sebelum
                    selisih = new_stok - stok_sebelum

                db.execute(
                    """UPDATE sku SET nama_barang=?, kategori=?, stok=?, satuan=?, harga_beli=?,
                       harga_jual=?, supplier=?, keterangan=?, updated_at=CURRENT_TIMESTAMP
                       WHERE kode_sku=?""",
                    (new_nama, new_kat, new_stok, new_satuan, new_hbeli, new_hjual,
                     new_supplier, new_ket, kode),
                )
                result["updated"] += 1

                if is_add_mode and stok_incoming > 0:
                    result["aggregation_summary"].append({
                        "kode": kode,
                        "nama": new_nama,
                        "stok_sebelum": stok_sebelum,
                        "stok_sesudah": new_stok,
                        "selisih": selisih,
                    })
            else:
                # ── INSERT: New SKU ──
                db.execute(
                    """INSERT INTO sku (kode_sku, nama_barang, kategori, stok, satuan,
                       harga_beli, harga_jual, supplier, keterangan)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (kode, nama, kat, stok_incoming, satuan, hbeli, hjual, supplier, ket),
                )
                result["inserted"] += 1

                if stok_incoming > 0:
                    result["aggregation_summary"].append({
                        "kode": kode,
                        "nama": nama,
                        "stok_sebelum": 0,
                        "stok_sesudah": stok_incoming,
                        "selisih": stok_incoming,
                    })

        except Exception as e:
            result["errors"] += 1
            result["error_details"].append(f"Baris {idx + 2} (SKU: {kode if 'kode' in dir() else '?'}): {str(e)}")

    return result


def render_sku():
    """Render SKU (Stock Keeping Unit) management page for Pembelian."""
    db = st.session_state.db

    st.subheader("🏷️ Manajemen SKU Barang")

    # ── Stats Ringkasan ──
    total_sku = db.fetch_one("SELECT COUNT(*) as cnt FROM sku")
    total_stok = db.fetch_one("SELECT COALESCE(SUM(stok), 0) as total FROM sku")
    total_value = db.fetch_one("SELECT COALESCE(SUM(stok * harga_beli), 0) as total FROM sku")

    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1:
        st.metric("📦 Total SKU", total_sku["cnt"] if total_sku else 0)
    with col_s2:
        st.metric("📊 Total Stok", f"{total_stok['total']:,}" if total_stok else "0")
    with col_s3:
        val = total_value["total"] if total_value else 0
        st.metric("💰 Nilai Inventaris", f"Rp {val:,.0f}")
    with col_s4:
        low_stock = db.fetch_one("SELECT COUNT(*) as cnt FROM sku WHERE stok <= 10 AND stok > 0")
        st.metric("⚠️ Stok Menipis (≤10)", low_stock["cnt"] if low_stock else 0)

    st.markdown("---")

    # ── Upload Massal SKU dari Excel ──
    with st.expander("📥 Upload Massal SKU (Excel — Ipos / ERP MMA)", expanded=False):
        st.markdown("""
        Upload file Excel berisi data SKU untuk diimport secara massal.
        **Upsert:** Jika `Kode SKU` sudah ada → data diupdate & stok ditambahkan. Jika belum ada → insert baru.
        """)

        uploaded_file = st.file_uploader(
            "Pilih file Excel (.xlsx / .xls)",
            type=["xlsx", "xls"],
            key="sku_mass_upload",
        )

        if uploaded_file is not None:
            try:
                df_raw = pd.read_excel(uploaded_file, engine="openpyxl")
                if df_raw.empty:
                    st.error("File Excel kosong.")
                else:
                    st.success(f"✅ File berhasil dibaca: **{len(df_raw)} baris**, {len(df_raw.columns)} kolom.")
                    st.caption(f"Kolom terdeteksi: {', '.join(df_raw.columns.astype(str).tolist())}")

                    # ── Column Mapping ──
                    st.markdown("### 🔗 Mapping Kolom")
                    st.caption("Cocokkan kolom Excel ke field SKU. Kolom dengan tanda * wajib diisi.")

                    excel_cols = [""] + df_raw.columns.tolist()

                    col_m1, col_m2, col_m3 = st.columns(3)
                    with col_m1:
                        map_kode = st.selectbox("Kode SKU *", excel_cols, key="map_kode",
                                                index=_auto_detect_column(excel_cols, ["kode_sku", "sku", "kode", "sku_code", "product_code"]))
                        map_nama = st.selectbox("Nama Barang *", excel_cols, key="map_nama",
                                                index=_auto_detect_column(excel_cols, ["nama_barang", "nama", "product_name", "name", "barang", "item"]))
                        map_kat = st.selectbox("Kategori", excel_cols, key="map_kat",
                                               index=_auto_detect_column(excel_cols, ["kategori", "category", "kat", "jenis", "group"]))
                    with col_m2:
                        map_stok = st.selectbox("Stok", excel_cols, key="map_stok",
                                                index=_auto_detect_column(excel_cols, ["stok", "stock", "qty", "quantity", "jumlah", "sisa", "saldo"]))
                        map_satuan = st.selectbox("Satuan", excel_cols, key="map_satuan",
                                                  index=_auto_detect_column(excel_cols, ["satuan", "unit", "uom", "sat"]))
                        map_supplier = st.selectbox("Supplier", excel_cols, key="map_supplier",
                                                    index=_auto_detect_column(excel_cols, ["supplier", "vendor", "supp", "pemasok"]))
                    with col_m3:
                        map_hbeli = st.selectbox("Harga Beli", excel_cols, key="map_hbeli",
                                                 index=_auto_detect_column(excel_cols, ["harga_beli", "hbeli", "cost", "hpp", "purchase_price", "buying_price"]))
                        map_hjual = st.selectbox("Harga Jual", excel_cols, key="map_hjual",
                                                 index=_auto_detect_column(excel_cols, ["harga_jual", "hjual", "price", "selling_price", "harga", "h_jual"]))
                        map_ket = st.selectbox("Keterangan", excel_cols, key="map_ket",
                                               index=_auto_detect_column(excel_cols, ["keterangan", "ket", "notes", "remark", "desc", "description", "keterangan_brg"]))

                    # ── Options ──
                    st.markdown("### ⚙️ Opsi Import")
                    col_o1, col_o2 = st.columns(2)
                    with col_o1:
                        stok_mode = st.radio(
                            "Mode Stok",
                            ["➕ Tambahkan ke stok existing (agregasi)", "🔄 Ganti stok (overwrite)"],
                            key="stok_mode_upload",
                            help="Pilih apakah stok dari Excel ditambahkan ke stok yang sudah ada, atau menggantinya sepenuhnya."
                        )
                    with col_o2:
                        update_kosong = st.checkbox(
                            "Hanya update field yang terisi di Excel (field kosong diabaikan)",
                            value=False,
                            key="update_kosong",
                            help="Jika dicentang, field yang kosong di Excel tidak akan menimpa data yang sudah ada di database."
                        )

                    # ── Preview ──
                    st.markdown("### 👁️ Preview Data")
                    st.caption(f"Menampilkan preview berdasarkan mapping kolom yang dipilih.")
                    preview_cols = [c for c in [map_kode, map_nama, map_kat, map_stok, map_satuan, map_supplier, map_hbeli, map_hjual, map_ket] if c]
                    if preview_cols:
                        st.dataframe(df_raw[preview_cols].head(20), width="stretch", hide_index=True)
                        if len(df_raw) > 20:
                            st.caption(f"... dan {len(df_raw) - 20} baris lainnya.")

                    # ── Execute Import ──
                    st.markdown("---")
                    if st.button("🚀 Proses Import SKU", type="primary", disabled=(not map_kode or not map_nama)):
                        if not map_kode or not map_nama:
                            st.error("Kode SKU dan Nama Barang wajib di-mapping!")
                        else:
                            result = bulk_upsert_sku(
                                db, df_raw,
                                map_kode, map_nama, map_kat, map_stok, map_satuan,
                                map_supplier, map_hbeli, map_hjual, map_ket,
                                stok_mode, update_kosong,
                            )

                            # Show results
                            st.markdown("---")
                            st.markdown("### 📊 Hasil Import")
                            col_r1, col_r2, col_r3, col_r4 = st.columns(4)
                            with col_r1:
                                st.metric("✅ Baru (Insert)", result["inserted"])
                            with col_r2:
                                st.metric("🔄 Diupdate (Upsert)", result["updated"])
                            with col_r3:
                                st.metric("⚠️ Error / Skip", result["errors"])
                            with col_r4:
                                st.metric("📦 Total Diproses", result["total"])

                            if result["error_details"]:
                                with st.expander(f"⚠️ Lihat {len(result['error_details'])} error detail", expanded=False):
                                    for err in result["error_details"]:
                                        st.caption(f"• {err}")

                            if result["aggregation_summary"]:
                                with st.expander("📊 Ringkasan Agregasi Stok", expanded=True):
                                    for item in result["aggregation_summary"]:
                                        st.markdown(
                                            f"• **{item['kode']}** — {item['nama']}: "
                                            f"stok {item['stok_sebelum']} → **{item['stok_sesudah']}** "
                                            f"({'+' if item['selisih'] >= 0 else ''}{item['selisih']})"
                                        )

                            # Clear file uploader by rerun after a short delay
                            st.success("Import selesai! Refresh halaman untuk melihat data terbaru.")
                            if st.button("🔄 Refresh Data", width="stretch"):
                                st.rerun()

            except Exception as e:
                st.error(f"Gagal membaca file Excel: {str(e)}")

    # ── Tambah SKU Baru ──
    with st.expander("➕ Tambah SKU Baru", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            kode = st.text_input("Kode SKU *", placeholder="SKU-001", key="new_sku_kode")
            nama = st.text_input("Nama Barang *", placeholder="Nama produk...", key="new_sku_nama")
            kategori = st.text_input("Kategori", placeholder="Elektronik, Pakaian, dll.", key="new_sku_kategori")
        with col2:
            stok = st.number_input("Stok Awal", min_value=0, value=0, step=1, key="new_sku_stok")
            satuan = st.selectbox("Satuan", ["pcs", "box", "kg", "liter", "pack", "lusin", "rim", "meter"], key="new_sku_satuan")
            supplier = st.text_input("Supplier", placeholder="Nama supplier...", key="new_sku_supplier")
        with col3:
            harga_beli = st.number_input("Harga Beli (Rp)", min_value=0, value=0, step=1000, key="new_sku_hbeli")
            harga_jual = st.number_input("Harga Jual (Rp)", min_value=0, value=0, step=1000, key="new_sku_hjual")
            keterangan = st.text_input("Keterangan", placeholder="Catatan...", key="new_sku_ket")

        if st.button("💾 Simpan SKU", type="primary"):
            if not kode.strip() or not nama.strip():
                st.error("Kode SKU dan Nama Barang harus diisi!")
            else:
                try:
                    db.execute(
                        """INSERT INTO sku (kode_sku, nama_barang, kategori, stok, satuan, harga_beli, harga_jual, supplier, keterangan)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (kode.strip().upper(), nama.strip(), kategori.strip(), stok, satuan,
                         harga_beli, harga_jual, supplier.strip(), keterangan.strip()),
                    )
                    st.success(f"SKU '{kode.strip().upper()}' berhasil ditambahkan!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal menambah SKU: {str(e)}")

    st.markdown("---")

    # ── Daftar SKU ──
    st.markdown("### 📋 Daftar SKU")

    # Filters
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        search_sku = st.text_input("🔍 Cari SKU / Nama", placeholder="Ketik kode atau nama...", key="search_sku_list")
    with col_f2:
        all_kategori = db.fetch_all("SELECT DISTINCT kategori FROM sku WHERE kategori != '' ORDER BY kategori")
        kat_options = ["Semua"] + [r["kategori"] for r in all_kategori]
        kat_filter = st.selectbox("Filter Kategori", kat_options, key="sku_kat_filter")
    with col_f3:
        stock_filter = st.selectbox("Filter Stok", ["Semua", "Stok Menipis (≤10)", "Stok Habis (0)", "Tersedia (>0)"], key="sku_stock_filter")

    # Build query
    query = "SELECT * FROM sku WHERE 1=1"
    params = []

    if search_sku:
        query += " AND (kode_sku LIKE ? OR nama_barang LIKE ?)"
        params.extend([f"%{search_sku}%", f"%{search_sku}%"])
    if kat_filter != "Semua":
        query += " AND kategori = ?"
        params.append(kat_filter)
    if stock_filter == "Stok Menipis (≤10)":
        query += " AND stok <= 10 AND stok > 0"
    elif stock_filter == "Stok Habis (0)":
        query += " AND stok = 0"
    elif stock_filter == "Tersedia (>0)":
        query += " AND stok > 0"

    query += " ORDER BY kode_sku ASC"
    sku_list = db.fetch_all(query, params)

    if not sku_list:
        st.info("📭 Belum ada SKU. Tambahkan SKU baru melalui form di atas.")
    else:
        # Build dataframe
        df_sku = pd.DataFrame([dict(r) for r in sku_list])
        df_sku = df_sku.rename(columns={
            "kode_sku": "Kode SKU", "nama_barang": "Nama Barang", "kategori": "Kategori",
            "stok": "Stok", "satuan": "Satuan", "harga_beli": "Harga Beli",
            "harga_jual": "Harga Jual", "supplier": "Supplier", "keterangan": "Keterangan",
        })
        # Format currency columns
        df_sku["Harga Beli"] = df_sku["Harga Beli"].apply(lambda x: f"Rp {x:,.0f}")
        df_sku["Harga Jual"] = df_sku["Harga Jual"].apply(lambda x: f"Rp {x:,.0f}")

        display_cols = ["Kode SKU", "Nama Barang", "Kategori", "Stok", "Satuan", "Harga Beli", "Harga Jual", "Supplier"]

        # Color-code low stock
        def color_stock(val):
            try:
                v = int(val)
            except (ValueError, TypeError):
                return ""
            if v == 0:
                return "background-color: #f8d7da; color: #721c24; font-weight: bold"
            elif v <= 10:
                return "background-color: #fff3cd; color: #856404; font-weight: bold"
            return ""

        styled = df_sku[display_cols].style.map(color_stock, subset=["Stok"])
        st.dataframe(styled, width="stretch", height=450, hide_index=True)
        st.caption(f"Total: {len(sku_list)} SKU ditampilkan")

    st.markdown("---")

    # ── Edit / Hapus / Tambah Stok per SKU ──
    st.markdown("### ⚙️ Edit / Update Stok SKU")
    sku_options = {f"{r['kode_sku']} — {r['nama_barang']}": r for r in sku_list} if sku_list else {}

    if sku_options:
        col_a1, col_a2 = st.columns([2, 1])
        with col_a1:
            selected_sku_label = st.selectbox(
                "Pilih SKU untuk diedit / update stok",
                list(sku_options.keys()),
                key="edit_sku_select",
            )
            selected_sku = sku_options[selected_sku_label] if selected_sku_label else None
        with col_a2:
            st.write("")
            st.write("")
            if st.button("🗑️ Hapus SKU Terpilih", width="stretch"):
                if selected_sku:
                    db.execute("DELETE FROM sku WHERE id = ?", (selected_sku["id"],))
                    st.success(f"SKU '{selected_sku['kode_sku']}' dihapus.")
                    st.rerun()

        if selected_sku:
            with st.expander(f"✏️ Edit: {selected_sku['kode_sku']} — {selected_sku['nama_barang']}", expanded=True):
                col_e1, col_e2, col_e3 = st.columns(3)
                with col_e1:
                    edit_kode = st.text_input("Kode SKU", value=selected_sku["kode_sku"], key=f"edit_sku_kode_{selected_sku['id']}")
                    edit_nama = st.text_input("Nama Barang", value=selected_sku["nama_barang"], key=f"edit_sku_nama_{selected_sku['id']}")
                    edit_kategori = st.text_input("Kategori", value=selected_sku["kategori"] or "", key=f"edit_sku_kategori_{selected_sku['id']}")
                with col_e2:
                    edit_stok = st.number_input("Stok Saat Ini", min_value=0, value=selected_sku["stok"] or 0, step=1, key=f"edit_sku_stok_{selected_sku['id']}")
                    edit_satuan = st.selectbox("Satuan", ["pcs", "box", "kg", "liter", "pack", "lusin", "rim", "meter"],
                                                index=["pcs", "box", "kg", "liter", "pack", "lusin", "rim", "meter"].index(selected_sku["satuan"]) if selected_sku["satuan"] in ["pcs", "box", "kg", "liter", "pack", "lusin", "rim", "meter"] else 0,
                                                key=f"edit_sku_satuan_{selected_sku['id']}")
                    edit_supplier = st.text_input("Supplier", value=selected_sku["supplier"] or "", key=f"edit_sku_supplier_{selected_sku['id']}")
                with col_e3:
                    edit_hbeli = st.number_input("Harga Beli (Rp)", min_value=0, value=int(selected_sku["harga_beli"] or 0), step=1000, key=f"edit_sku_hbeli_{selected_sku['id']}")
                    edit_hjual = st.number_input("Harga Jual (Rp)", min_value=0, value=int(selected_sku["harga_jual"] or 0), step=1000, key=f"edit_sku_hjual_{selected_sku['id']}")
                    edit_ket = st.text_input("Keterangan", value=selected_sku["keterangan"] or "", key=f"edit_sku_ket_{selected_sku['id']}")

                # Quick stock adjustment
                st.markdown("**🔧 Quick Stock Adjustment:**")
                col_q1, col_q2, col_q3, col_q4 = st.columns(4)
                with col_q1:
                    tambah_stok = st.number_input("Tambah Stok (+)", min_value=0, value=0, step=1, key=f"quick_add_stok_{selected_sku['id']}")
                with col_q2:
                    kurangi_stok = st.number_input("Kurangi Stok (−)", min_value=0, value=0, step=1, key=f"quick_sub_stok_{selected_sku['id']}")
                with col_q3:
                    if st.button("➕ Terapkan Tambah Stok", width="stretch"):
                        new_stok = selected_sku["stok"] + tambah_stok
                        db.execute("UPDATE sku SET stok = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_stok, selected_sku["id"]))
                        st.success(f"Stok bertambah +{tambah_stok}. Stok sekarang: {new_stok}")
                        st.rerun()
                with col_q4:
                    if st.button("➖ Terapkan Kurangi Stok", width="stretch"):
                        new_stok = max(0, selected_sku["stok"] - kurangi_stok)
                        db.execute("UPDATE sku SET stok = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_stok, selected_sku["id"]))
                        st.success(f"Stok berkurang −{kurangi_stok}. Stok sekarang: {new_stok}")
                        st.rerun()

                st.markdown("---")
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("💾 Simpan Perubahan SKU", type="primary", width="stretch"):
                        if not edit_kode.strip() or not edit_nama.strip():
                            st.error("Kode SKU dan Nama Barang harus diisi!")
                        else:
                            try:
                                db.execute(
                                    """UPDATE sku SET kode_sku=?, nama_barang=?, kategori=?, stok=?, satuan=?,
                                       harga_beli=?, harga_jual=?, supplier=?, keterangan=?, updated_at=CURRENT_TIMESTAMP
                                       WHERE id=?""",
                                    (edit_kode.strip().upper(), edit_nama.strip(), edit_kategori.strip(), edit_stok,
                                     edit_satuan, edit_hbeli, edit_hjual, edit_supplier.strip(), edit_ket.strip(),
                                     selected_sku["id"]),
                                )
                                st.success(f"SKU '{edit_kode.strip().upper()}' berhasil diupdate!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Gagal update: {str(e)}")
                with col_btn2:
                    if st.button("✕ Batal Edit", width="stretch"):
                        st.rerun()
    else:
        st.info("Tambahkan SKU terlebih dahulu untuk melihat opsi edit.")


# ==================== PEMBELIAN FUNCTIONS ====================
def _generate_faktur(db) -> str:
    """Generate nomor faktur otomatis: PO-YYYYMMDD-XXX."""
    today = datetime.now().strftime("%Y%m%d")
    count = db.fetch_one(
        "SELECT COUNT(*) as cnt FROM pembelian WHERE no_faktur LIKE ?",
        (f"PO-{today}-%",),
    )
    seq = (count["cnt"] if count else 0) + 1
    return f"PO-{today}-{seq:03d}"


def render_purchase_input():
    """Render form input pembelian ke supplier (multi-item cart)."""
    db = st.session_state.db

    st.subheader("🛒 Input Pembelian ke Supplier")

    # ── Init cart session state ──
    if "purchase_cart" not in st.session_state:
        st.session_state.purchase_cart = []
    if "purchase_supplier" not in st.session_state:
        st.session_state.purchase_supplier = ""
    if "purchase_faktur" not in st.session_state:
        st.session_state.purchase_faktur = _generate_faktur(db)

    cart = st.session_state.purchase_cart

    # ── Header: Supplier & No Faktur ──
    col_h1, col_h2, col_h3 = st.columns([2, 2, 1])
    with col_h1:
        # Get distinct suppliers from SKU + pembelian history
        sku_suppliers = db.fetch_all("SELECT DISTINCT supplier FROM sku WHERE supplier != '' ORDER BY supplier")
        hist_suppliers = db.fetch_all("SELECT DISTINCT supplier FROM pembelian WHERE supplier != '' ORDER BY supplier")
        all_supplier_names = sorted(set(
            [s["supplier"] for s in sku_suppliers] + [s["supplier"] for s in hist_suppliers]
        ))
        if not all_supplier_names:
            all_supplier_names = ["Supplier Umum"]

        supplier_options = all_supplier_names + ["✚ Tambah Supplier Baru..."]
        current_supplier = st.session_state.purchase_supplier
        if current_supplier and current_supplier not in supplier_options:
            # If current supplier is a newly added one, include it
            supplier_options = [current_supplier] + [o for o in supplier_options if o != current_supplier]

        idx = supplier_options.index(current_supplier) if current_supplier in supplier_options else 0
        supplier_choice = st.selectbox("Supplier *", supplier_options, index=idx, key="purchase_supplier_select")

        if supplier_choice == "✚ Tambah Supplier Baru...":
            supplier = st.text_input(
                "Nama Supplier Baru",
                placeholder="Ketik nama supplier baru...",
                key="purchase_new_supplier",
            )
            if supplier:
                st.session_state.purchase_supplier = supplier.strip()
            else:
                st.session_state.purchase_supplier = ""
        else:
            st.session_state.purchase_supplier = supplier_choice
            supplier = supplier_choice

    with col_h2:
        faktur = st.text_input("No Faktur *", value=st.session_state.purchase_faktur, key="purchase_faktur_input")
        st.session_state.purchase_faktur = faktur
    with col_h3:
        st.write("")
        st.write("")
        if st.button("🔄 New Faktur", width="stretch"):
            st.session_state.purchase_faktur = _generate_faktur(db)
            st.session_state.purchase_cart = []
            st.session_state.purchase_supplier = ""
            st.rerun()

    st.markdown("---")

    # ── Add Item Form ──
    st.markdown("### ➕ Tambah Item")

    # Load ALL SKU data — supplier only for auto-fill, NOT for filtering
    all_sku = db.fetch_all(
        "SELECT kode_sku, nama_barang, satuan, harga_beli, stok, supplier FROM sku ORDER BY kode_sku"
    )

    if not all_sku:
        st.warning("⚠️ Belum ada data SKU. Tambahkan SKU terlebih dahulu di menu 🏷️ Manajemen SKU.")
    else:
        # Search input: cari by Kode SKU ATAU Nama Barang
        search_term = st.text_input(
            "🔍 Cari SKU (Kode atau Nama Barang) — kosongkan untuk lihat semua",
            placeholder="Ketik kode SKU atau nama barang...",
            key="purchase_search_sku",
        )

        # Filter by search term only (supplier does NOT restrict SKU visibility)
        search_lower = search_term.strip().lower() if search_term else ""
        filtered_sku = []

        for s in all_sku:
            if search_lower:
                kode_lower = s["kode_sku"].lower()
                nama_lower = s["nama_barang"].lower()
                if search_lower in kode_lower or search_lower in nama_lower:
                    filtered_sku.append(s)
            else:
                filtered_sku.append(s)

        # Limit to prevent UI lag
        max_display = 200
        total_filtered = len(filtered_sku)
        truncated = total_filtered > max_display
        if truncated:
            filtered_sku = filtered_sku[:max_display]

        sku_options_map = {}
        if filtered_sku:
            sku_options_map = {
                f"{s['kode_sku']} — {s['nama_barang']} | Stok: {s['stok']} | {s['supplier'] or 'Tanpa Supplier'}": s
                for s in filtered_sku
            }
            sku_labels = list(sku_options_map.keys())
        else:
            sku_labels = ["-- Tidak ada SKU ditemukan --"]

        if truncated:
            st.caption(f"⚠️ Menampilkan {max_display} dari {total_filtered} hasil. Gunakan pencarian lebih spesifik.")

        col_i1, col_i2, col_i3, col_i4 = st.columns([3, 1, 1, 1])
        with col_i1:
            selected_sku_label = st.selectbox("Pilih SKU", sku_labels, key="purchase_add_sku")
        with col_i2:
            qty = st.number_input("Qty", min_value=1, value=1, step=1, key=f"purchase_add_qty_{selected_sku_label}")
        with col_i3:
            if selected_sku_label in sku_options_map:
                auto_harga = sku_options_map[selected_sku_label]["harga_beli"] or 0
            else:
                auto_harga = 0
            harga_manual = st.number_input(
                "Harga Beli/Unit", min_value=0, value=int(auto_harga), step=1000,
                key=f"purchase_add_harga_{selected_sku_label}"
            )
            # ── Price change indicator ──
            if selected_sku_label in sku_options_map and auto_harga > 0 and harga_manual != auto_harga:
                selisih = harga_manual - auto_harga
                if selisih > 0:
                    st.caption(f"📈 Naik Rp {selisih:,.0f} dari harga sebelumnya (Rp {auto_harga:,.0f})")
                else:
                    st.caption(f"📉 Turun Rp {abs(selisih):,.0f} dari harga sebelumnya (Rp {auto_harga:,.0f})")
        with col_i4:
            st.write("")
            st.write("")
            if st.button("➕ Tambah", width="stretch", type="primary", key=f"purchase_btn_add_{selected_sku_label}"):
                if selected_sku_label not in sku_options_map:
                    st.error("Pilih SKU yang valid!")
                else:
                    sku_data = sku_options_map[selected_sku_label]
                    # Check if already in cart (same SKU + same price → merge qty)
                    existing_idx = None
                    for i, item in enumerate(cart):
                        if item["kode_sku"] == sku_data["kode_sku"] and item["harga_beli"] == harga_manual:
                            existing_idx = i
                            break

                    if existing_idx is not None:
                        cart[existing_idx]["qty"] += qty
                        cart[existing_idx]["total_harga"] = cart[existing_idx]["qty"] * cart[existing_idx]["harga_beli"]
                        st.success(f"Qty {sku_data['kode_sku']} ditambahkan → {cart[existing_idx]['qty']}")
                    else:
                        cart.append({
                            "kode_sku": sku_data["kode_sku"],
                            "nama_barang": sku_data["nama_barang"],
                            "satuan": sku_data["satuan"],
                            "qty": qty,
                            "harga_beli": harga_manual,
                            "total_harga": qty * harga_manual,
                        })
                        st.success(f"{sku_data['kode_sku']} ditambahkan ke keranjang!")

    # ── Cart Table ──
    st.markdown("---")
    st.markdown("### 🛒 Keranjang Belanja")

    if not cart:
        st.info("Keranjang kosong. Tambahkan item di atas.")
    else:
        df_cart = pd.DataFrame(cart)
        df_cart["No"] = range(1, len(cart) + 1)
        df_cart["Harga Beli"] = df_cart["harga_beli"].apply(lambda x: f"Rp {x:,.0f}")
        df_cart["Total Harga"] = df_cart["total_harga"].apply(lambda x: f"Rp {x:,.0f}")
        df_display = df_cart[["No", "kode_sku", "nama_barang", "qty", "satuan", "Harga Beli", "Total Harga"]]
        df_display = df_display.rename(columns={
            "kode_sku": "Kode SKU", "nama_barang": "Nama Barang",
            "qty": "Qty", "satuan": "Satuan",
        })

        st.dataframe(df_display, width="stretch", hide_index=True)

        grand_total = sum(item["total_harga"] for item in cart)
        st.markdown(f"**💵 Total Pembelian: Rp {grand_total:,.0f}** | **📦 {len(cart)} item**")

        # ── Cart Actions ──
        col_c1, col_c2, col_c3 = st.columns([2, 1, 1])
        with col_c1:
            # Remove item
            remove_idx = st.selectbox(
                "Hapus item dari keranjang",
                [f"{i+1}. {item['kode_sku']} — {item['nama_barang']} (Qty: {item['qty']})" for i, item in enumerate(cart)],
                key="purchase_remove_item",
            )
        with col_c2:
            if st.button("🗑️ Hapus Item", width="stretch"):
                idx = int(remove_idx.split(".")[0]) - 1
                removed = cart.pop(idx)
                st.success(f"{removed['kode_sku']} dihapus dari keranjang.")
                st.rerun()
        with col_c3:
            if st.button("🔄 Reset Keranjang", width="stretch"):
                st.session_state.purchase_cart = []
                st.rerun()

        # ── Save Transaction ──
        st.markdown("---")
        col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
        with col_s1:
            ket_global = st.text_input("Keterangan (opsional)", placeholder="Catatan untuk seluruh transaksi...", key="purchase_global_ket")
        with col_s2:
            metode_bayar = st.selectbox(
                "Metode Bayar",
                ["Transfer", "Cash", "Kontrabon"],
                key="purchase_metode_bayar",
                help="Transfer = bayar via bank, Cash = tunai, Kontrabon = bayar nanti (hutang)"
            )
            # Semua PO baru berstatus PENDING — menunggu konfirmasi Finance
            status_bayar = "PENDING"
            st.caption("📌 Status: PENDING (menunggu konfirmasi Finance)")
        with col_s3:
            st.write("")
            st.write("")
            if st.button("💾 Simpan Pembelian & Update Stok", type="primary", width="stretch"):
                if not faktur.strip():
                    st.error("No Faktur wajib diisi!")
                elif not supplier:
                    st.error("Supplier wajib dipilih!")
                else:
                    today_str = datetime.now().strftime("%d-%m-%Y")
                    saved_count = 0
                    errors = []
                    price_changes = []  # Track price changes for reporting

                    for item in cart:
                        try:
                            db.execute(
                                """INSERT INTO pembelian (no_faktur, tanggal, supplier, kode_sku, nama_barang,
                                   qty, satuan, harga_beli, total_harga, keterangan, metode_bayar, status_bayar)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (faktur.strip(), today_str, supplier,
                                 item["kode_sku"], item["nama_barang"],
                                 item["qty"], item["satuan"], item["harga_beli"],
                                 item["total_harga"], ket_global.strip(),
                                 metode_bayar, status_bayar),
                            )

                            # ── Auto-update SKU: stok + harga_beli + supplier ──
                            sku_current = db.fetch_one(
                                "SELECT harga_beli, supplier FROM sku WHERE kode_sku = ?",
                                (item["kode_sku"],),
                            )
                            old_harga = sku_current["harga_beli"] if sku_current else 0
                            old_supplier = sku_current["supplier"] if sku_current else ""

                            # Build update query dynamically
                            update_fields = ["stok = stok + ?"]
                            update_params = [item["qty"]]

                            # Update harga_beli if different
                            if item["harga_beli"] != old_harga:
                                update_fields.append("harga_beli = ?")
                                update_params.append(item["harga_beli"])
                                price_changes.append({
                                    "kode": item["kode_sku"],
                                    "nama": item["nama_barang"],
                                    "lama": old_harga,
                                    "baru": item["harga_beli"],
                                    "selisih": item["harga_beli"] - old_harga,
                                })

                            # Update supplier if SKU has no supplier yet
                            if not old_supplier and supplier:
                                update_fields.append("supplier = ?")
                                update_params.append(supplier)

                            update_fields.append("updated_at = CURRENT_TIMESTAMP")
                            update_params.append(item["kode_sku"])

                            db.execute(
                                f"UPDATE sku SET {', '.join(update_fields)} WHERE kode_sku = ?",
                                update_params,
                            )

                            saved_count += 1
                        except Exception as e:
                            errors.append(f"{item['kode_sku']}: {str(e)}")

                    # ── Show price change warnings ──
                    if price_changes:
                        with st.expander(f"⚠️ **{len(price_changes)} perubahan Harga Beli terdeteksi** — Klik untuk detail", expanded=True):
                            for pc in price_changes:
                                arah = "📈 NAIK" if pc["selisih"] > 0 else "📉 TURUN"
                                st.markdown(
                                    f"• **{pc['kode']}** — {pc['nama']} | "
                                    f"Harga Lama: Rp {pc['lama']:,.0f} → Harga Baru: Rp {pc['baru']:,.0f} "
                                    f"({arah} Rp {abs(pc['selisih']):,.0f})"
                                )

                    if errors:
                        st.warning(f"⚠️ {saved_count} item tersimpan, {len(errors)} error.")
                        with st.expander("Detail Error"):
                            for e in errors:
                                st.caption(f"• {e}")
                    else:
                        change_msg = f" | {len(price_changes)} harga beli diupdate" if price_changes else ""
                        st.success(f"✅ Pembelian berhasil! {saved_count} item disimpan & stok diupdate.{change_msg}")
                        # Reset cart
                        st.session_state.purchase_cart = []
                        st.session_state.purchase_faktur = _generate_faktur(db)
                        st.session_state.purchase_supplier = ""
                        st.rerun()


def render_purchase_history():
    """Render riwayat transaksi pembelian."""
    db = st.session_state.db

    st.subheader("📋 Riwayat Pembelian")

    # ── Stats ──
    total_trx = db.fetch_one("SELECT COUNT(DISTINCT no_faktur) as cnt FROM pembelian")
    total_items = db.fetch_one("SELECT COUNT(*) as cnt FROM pembelian")
    total_value = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM pembelian")
    pending_value = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as total FROM pembelian WHERE status_bayar = 'PENDING'"
    )
    kontrabon_value = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as total FROM pembelian WHERE status_bayar = 'KONTRA BON'"
    )

    col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
    with col_s1:
        st.metric("📋 Total Transaksi", total_trx["cnt"] if total_trx else 0)
    with col_s2:
        st.metric("📦 Total Item Dibeli", total_items["cnt"] if total_items else 0)
    with col_s3:
        val = total_value["total"] if total_value else 0
        st.metric("💰 Total Nilai", f"Rp {val:,.0f}")
    with col_s4:
        pd_val = pending_value["total"] if pending_value else 0
        st.metric("📌 Pending", f"Rp {pd_val:,.0f}" if pd_val > 0 else "Rp 0")
    with col_s5:
        kb_val = kontrabon_value["total"] if kontrabon_value else 0
        st.metric("⚠️ Kontrabon", f"Rp {kb_val:,.0f}" if kb_val > 0 else "Rp 0")

    st.markdown("---")

    # ── Filters ──
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    with col_f1:
        search_faktur = st.text_input("🔍 No Faktur", placeholder="PO-...", key="hist_search_faktur")
    with col_f2:
        all_suppliers = db.fetch_all("SELECT DISTINCT supplier FROM pembelian ORDER BY supplier")
        supp_list = ["Semua"] + [s["supplier"] for s in all_suppliers]
        supp_filter = st.selectbox("Supplier", supp_list, key="hist_supp_filter")
    with col_f3:
        status_filter = st.selectbox(
            "Status Bayar",
            ["Semua", "PENDING", "LUNAS", "KONTRA BON"],
            key="hist_status_filter",
        )
    with col_f4:
        sort_order = st.selectbox("Urutkan", ["Terbaru", "Terlama", "Nilai Tertinggi", "Nilai Terendah"], key="hist_sort")

    # ── Query ──
    query = "SELECT * FROM pembelian WHERE 1=1"
    params = []

    if search_faktur:
        query += " AND no_faktur LIKE ?"
        params.append(f"%{search_faktur}%")
    if supp_filter != "Semua":
        query += " AND supplier = ?"
        params.append(supp_filter)
    if status_filter != "Semua":
        query += " AND status_bayar = ?"
        params.append(status_filter)

    if sort_order == "Terbaru":
        query += " ORDER BY created_at DESC, id DESC"
    elif sort_order == "Terlama":
        query += " ORDER BY created_at ASC, id ASC"
    elif sort_order == "Nilai Tertinggi":
        query += " ORDER BY total_harga DESC"
    else:
        query += " ORDER BY total_harga ASC"

    rows = db.fetch_all(query, params)

    if not rows:
        st.info("📭 Belum ada riwayat pembelian.")
    else:
        df_hist = pd.DataFrame([dict(r) for r in rows])
        df_hist = df_hist.rename(columns={
            "no_faktur": "No Faktur", "tanggal": "Tanggal", "supplier": "Supplier",
            "kode_sku": "Kode SKU", "nama_barang": "Nama Barang",
            "qty": "Qty", "satuan": "Satuan", "harga_beli": "Harga Beli",
            "total_harga": "Total Harga", "keterangan": "Keterangan",
            "metode_bayar": "Metode Bayar", "status_bayar": "Status Bayar",
        })
        df_hist["Harga Beli"] = df_hist["Harga Beli"].apply(lambda x: f"Rp {x:,.0f}")
        df_hist["Total Harga"] = df_hist["Total Harga"].apply(lambda x: f"Rp {x:,.0f}")

        # Color-code status_bayar
        def color_status_bayar(val):
            if val == "KONTRA BON":
                return "background-color: #fff3cd; color: #856404; font-weight: bold"
            elif val == "LUNAS":
                return "background-color: #d4edda; color: #155724"
            elif val == "PENDING":
                return "background-color: #cce5ff; color: #004085; font-weight: bold"
            return ""

        display_cols = ["No Faktur", "Tanggal", "Supplier", "Kode SKU", "Nama Barang", "Qty", "Satuan", "Harga Beli", "Total Harga", "Metode Bayar", "Status Bayar"]

        styled_hist = df_hist[display_cols].style.map(color_status_bayar, subset=["Status Bayar"])
        st.dataframe(styled_hist, width="stretch", height=450, hide_index=True)

        # Summary per faktur
        st.markdown("---")
        st.markdown("### 📊 Ringkasan per Faktur")
        faktur_summary = db.fetch_all(
            "SELECT no_faktur, tanggal, supplier, metode_bayar, status_bayar, COUNT(*) as items, SUM(total_harga) as total "
            "FROM pembelian GROUP BY no_faktur ORDER BY created_at DESC",
            params[:len(params)] if params else [],
        )
        if faktur_summary:
            df_faktur = pd.DataFrame([dict(r) for r in faktur_summary])
            df_faktur = df_faktur.rename(columns={
                "no_faktur": "No Faktur", "tanggal": "Tanggal", "supplier": "Supplier",
                "metode_bayar": "Metode Bayar", "status_bayar": "Status Bayar",
                "items": "Jumlah Item", "total": "Total",
            })
            df_faktur["Total"] = df_faktur["Total"].apply(lambda x: f"Rp {x:,.0f}")
            st.dataframe(df_faktur, width="stretch", hide_index=True)
            st.caption(f"Total: {len(faktur_summary)} faktur")

        # ── Delete ──
        st.markdown("---")
        with st.expander("🗑️ Hapus Transaksi", expanded=False):
            faktur_to_delete = st.selectbox(
                "Pilih No Faktur untuk dihapus",
                ["-- Pilih --"] + [f"{r['no_faktur']} ({r['tanggal']}, {r['supplier']})" for r in faktur_summary] if faktur_summary else ["-- Tidak ada --"],
                key="hist_delete_faktur",
            )
            if st.button("🗑️ Hapus Faktur & Rollback Stok", type="primary"):
                if faktur_to_delete != "-- Pilih --" and faktur_to_delete != "-- Tidak ada --":
                    no_faktur = faktur_to_delete.split(" (")[0]
                    # Rollback stok
                    items_to_rollback = db.fetch_all("SELECT kode_sku, qty FROM pembelian WHERE no_faktur = ?", (no_faktur,))
                    for item in items_to_rollback:
                        db.execute(
                            "UPDATE sku SET stok = MAX(0, stok - ?), updated_at = CURRENT_TIMESTAMP WHERE kode_sku = ?",
                            (item["qty"], item["kode_sku"]),
                        )
                    # Delete
                    db.execute("DELETE FROM pembelian WHERE no_faktur = ?", (no_faktur,))
                    st.success(f"Faktur '{no_faktur}' dihapus & stok di-rollback.")
                    st.rerun()

        # ── Revisi Pembelian ──
        st.markdown("---")
        with st.expander("✏️ Revisi Pembelian", expanded=False):
            st.markdown("Pilih faktur untuk direvisi. Stok akan di-rollback lalu dihitung ulang dengan data baru.")

            revisi_faktur_label = st.selectbox(
                "Pilih No Faktur untuk direvisi",
                ["-- Pilih --"] + [f"{r['no_faktur']} ({r['tanggal']}, {r['supplier']}, {r['items']} item, Rp {r['total']:,.0f})" for r in faktur_summary] if faktur_summary else ["-- Tidak ada --"],
                key="hist_revisi_faktur",
            )

            if revisi_faktur_label != "-- Pilih --" and revisi_faktur_label != "-- Tidak ada --":
                no_faktur_revisi = revisi_faktur_label.split(" (")[0]

                # Load existing items
                existing_items = db.fetch_all(
                    "SELECT * FROM pembelian WHERE no_faktur = ? ORDER BY id",
                    (no_faktur_revisi,),
                )
                current_supplier = existing_items[0]["supplier"] if existing_items else ""
                current_tanggal = existing_items[0]["tanggal"] if existing_items else ""
                current_ket = existing_items[0]["keterangan"] if existing_items else ""
                current_metode = existing_items[0]["metode_bayar"] if existing_items and existing_items[0]["metode_bayar"] else "Transfer"
                current_status = existing_items[0]["status_bayar"] if existing_items and existing_items[0]["status_bayar"] else "LUNAS"

                if "revisi_cart" not in st.session_state or st.session_state.get("revisi_faktur_key") != no_faktur_revisi:
                    # Init revision cart from existing data
                    st.session_state.revisi_cart = [
                        {
                            "kode_sku": r["kode_sku"],
                            "nama_barang": r["nama_barang"],
                            "satuan": r["satuan"],
                            "qty": r["qty"],
                            "harga_beli": r["harga_beli"],
                            "total_harga": r["total_harga"],
                        }
                        for r in existing_items
                    ]
                    st.session_state.revisi_faktur_key = no_faktur_revisi
                    st.session_state.revisi_supplier = current_supplier
                    st.session_state.revisi_metode = current_metode
                    st.session_state.revisi_status = current_status

                revisi_cart = st.session_state.revisi_cart

                # ── Header info ──
                st.markdown(f"**No Faktur:** `{no_faktur_revisi}` | **Supplier:** {current_supplier} | **Tanggal:** {current_tanggal}")

                # ── Edit Supplier ──
                all_supplier_names = sorted(set(
                    [s["supplier"] for s in db.fetch_all("SELECT DISTINCT supplier FROM sku WHERE supplier != ''")]
                    + [s["supplier"] for s in db.fetch_all("SELECT DISTINCT supplier FROM pembelian WHERE supplier != ''")]
                ))
                if not all_supplier_names:
                    all_supplier_names = ["Supplier Umum"]
                supplier_options = all_supplier_names + ["✚ Supplier Baru..."]

                idx_supp = supplier_options.index(st.session_state.revisi_supplier) if st.session_state.revisi_supplier in supplier_options else 0
                revisi_supp_choice = st.selectbox("Supplier", supplier_options, index=idx_supp, key="revisi_supplier_select")
                if revisi_supp_choice == "✚ Supplier Baru...":
                    revisi_supplier = st.text_input("Nama Supplier Baru", key="revisi_new_supplier")
                else:
                    revisi_supplier = revisi_supp_choice
                st.session_state.revisi_supplier = revisi_supplier

                revisi_ket = st.text_input("Keterangan", value=current_ket, key="revisi_ket")

                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    metode_options = ["Transfer", "Cash", "Kontrabon"]
                    idx_metode = metode_options.index(st.session_state.get("revisi_metode", "Transfer")) if st.session_state.get("revisi_metode") in metode_options else 0
                    revisi_metode = st.selectbox("Metode Bayar", metode_options, index=idx_metode, key="revisi_metode_select")
                    st.session_state.revisi_metode = revisi_metode
                with col_p2:
                    # Preserve existing status_bayar — hanya Finance yang bisa mengubah
                    revisi_status = st.session_state.get("revisi_status", current_status)
                    if revisi_status == "PENDING":
                        st.warning("📌 Status: **PENDING** (menunggu konfirmasi Finance)")
                    elif revisi_status == "LUNAS":
                        st.success("✅ Status: **LUNAS** (sudah dikonfirmasi Finance)")
                    elif revisi_status == "KONTRA BON":
                        st.info("📋 Status: **KONTRA BON** (hutang)")
                    else:
                        st.caption(f"Status: {revisi_status}")
                    st.caption("⚠️ Status bayar tidak berubah saat revisi. Gunakan menu 💳 Finance untuk konfirmasi.")

                st.markdown("---")

                # ── Edit existing items ──
                st.markdown("### 📋 Item Existing")
                items_to_delete = []
                for i, item in enumerate(revisi_cart):
                    col_r1, col_r2, col_r3, col_r4, col_r5 = st.columns([2, 1, 1.5, 1, 0.5])
                    with col_r1:
                        st.markdown(f"**{item['kode_sku']}** — {item['nama_barang']} ({item['satuan']})")
                    with col_r2:
                        new_qty = st.number_input(
                            "Qty", min_value=1, value=item["qty"], step=1,
                            key=f"revisi_qty_{i}_{no_faktur_revisi}",
                        )
                    with col_r3:
                        new_harga = st.number_input(
                            "Harga/Unit", min_value=0, value=int(item["harga_beli"]), step=1000,
                            key=f"revisi_harga_{i}_{no_faktur_revisi}",
                        )
                    with col_r4:
                        total_item = new_qty * new_harga
                        st.markdown(f"Rp {total_item:,.0f}")
                    with col_r5:
                        if st.button("✕", key=f"revisi_del_{i}_{no_faktur_revisi}"):
                            items_to_delete.append(i)

                    # Update in-memory cart
                    revisi_cart[i]["qty"] = new_qty
                    revisi_cart[i]["harga_beli"] = new_harga
                    revisi_cart[i]["total_harga"] = total_item

                # Remove deleted items
                if items_to_delete:
                    for idx in sorted(items_to_delete, reverse=True):
                        removed = revisi_cart.pop(idx)
                        st.toast(f"{removed['kode_sku']} dihapus dari revisi.")
                    st.rerun()

                st.markdown("---")

                # ── Add new item ──
                st.markdown("### ➕ Tambah Item Baru")
                all_sku = db.fetch_all(
                    "SELECT kode_sku, nama_barang, satuan, harga_beli, stok, supplier FROM sku ORDER BY kode_sku"
                )
                search_add = st.text_input("🔍 Cari SKU", placeholder="Ketik kode atau nama...", key="revisi_search_add")
                search_lower = search_add.strip().lower() if search_add else ""
                filtered_add = [s for s in all_sku if not search_lower or search_lower in s["kode_sku"].lower() or search_lower in s["nama_barang"].lower()]

                add_options = {}
                if filtered_add:
                    add_options = {
                        f"{s['kode_sku']} — {s['nama_barang']} | Stok: {s['stok']}": s
                        for s in filtered_add[:100]
                    }

                col_a1, col_a2, col_a3, col_a4 = st.columns([3, 1, 1, 1])
                with col_a1:
                    add_sku_label = st.selectbox(
                        "Pilih SKU", list(add_options.keys()) if add_options else ["-- Tidak ada --"],
                        key="revisi_add_sku",
                    )
                with col_a2:
                    add_qty = st.number_input("Qty", min_value=1, value=1, step=1, key=f"revisi_add_qty_{add_sku_label}")
                with col_a3:
                    auto_h = add_options[add_sku_label]["harga_beli"] if add_sku_label in add_options else 0
                    add_harga = st.number_input("Harga/Unit", min_value=0, value=int(auto_h or 0), step=1000, key=f"revisi_add_harga_{add_sku_label}")
                with col_a4:
                    st.write("")
                    if st.button("➕ Tambah", width="stretch", key=f"revisi_btn_add_{add_sku_label}"):
                        if add_sku_label in add_options:
                            sku = add_options[add_sku_label]
                            revisi_cart.append({
                                "kode_sku": sku["kode_sku"],
                                "nama_barang": sku["nama_barang"],
                                "satuan": sku["satuan"],
                                "qty": add_qty,
                                "harga_beli": add_harga,
                                "total_harga": add_qty * add_harga,
                            })
                            st.success(f"{sku['kode_sku']} ditambahkan!")
                            st.rerun()

                # ── Summary ──
                st.markdown("---")
                grand_revisi = sum(item["total_harga"] for item in revisi_cart)
                st.markdown(f"**📦 {len(revisi_cart)} item | 💵 Total: Rp {grand_revisi:,.0f}**")

                # ── Save Revision ──
                col_sv1, col_sv2 = st.columns(2)
                with col_sv1:
                    if st.button("💾 Simpan Revisi & Update Stok", type="primary", width="stretch"):
                        if not revisi_cart:
                            st.error("Tidak ada item untuk disimpan.")
                        elif not revisi_supplier:
                            st.error("Supplier wajib diisi!")
                        else:
                            try:
                                # Step 1: Rollback old stock
                                for old_item in existing_items:
                                    db.execute(
                                        "UPDATE sku SET stok = MAX(0, stok - ?), updated_at = CURRENT_TIMESTAMP WHERE kode_sku = ?",
                                        (old_item["qty"], old_item["kode_sku"]),
                                    )
                                # Step 2: Delete old entries
                                db.execute("DELETE FROM pembelian WHERE no_faktur = ?", (no_faktur_revisi,))

                                # Step 3: Insert new entries & update stock + harga
                                price_changes = []
                                for item in revisi_cart:
                                    db.execute(
                                        """INSERT INTO pembelian (no_faktur, tanggal, supplier, kode_sku, nama_barang,
                                           qty, satuan, harga_beli, total_harga, keterangan, metode_bayar, status_bayar)
                                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                        (no_faktur_revisi, current_tanggal, revisi_supplier,
                                         item["kode_sku"], item["nama_barang"],
                                         item["qty"], item["satuan"], item["harga_beli"],
                                         item["total_harga"], revisi_ket.strip(),
                                         revisi_metode, revisi_status),
                                    )

                                    # Update SKU: stock + harga_beli + supplier
                                    sku_cur = db.fetch_one("SELECT harga_beli, supplier FROM sku WHERE kode_sku = ?", (item["kode_sku"],))
                                    old_h = sku_cur["harga_beli"] if sku_cur else 0
                                    old_s = sku_cur["supplier"] if sku_cur else ""

                                    upd_fields = ["stok = stok + ?"]
                                    upd_params = [item["qty"]]

                                    if item["harga_beli"] != old_h:
                                        upd_fields.append("harga_beli = ?")
                                        upd_params.append(item["harga_beli"])
                                        price_changes.append({
                                            "kode": item["kode_sku"], "nama": item["nama_barang"],
                                            "lama": old_h, "baru": item["harga_beli"],
                                            "selisih": item["harga_beli"] - old_h,
                                        })

                                    if not old_s and revisi_supplier:
                                        upd_fields.append("supplier = ?")
                                        upd_params.append(revisi_supplier)

                                    upd_fields.append("updated_at = CURRENT_TIMESTAMP")
                                    upd_params.append(item["kode_sku"])

                                    db.execute(
                                        f"UPDATE sku SET {', '.join(upd_fields)} WHERE kode_sku = ?",
                                        upd_params,
                                    )

                                # Show price changes
                                if price_changes:
                                    st.warning(f"⚠️ {len(price_changes)} harga beli diupdate:")
                                    for pc in price_changes:
                                        arah = "📈" if pc["selisih"] > 0 else "📉"
                                        st.caption(f"{arah} {pc['kode']}: Rp {pc['lama']:,.0f} → Rp {pc['baru']:,.0f}")

                                st.success(f"✅ Revisi faktur '{no_faktur_revisi}' berhasil! {len(revisi_cart)} item disimpan.")
                                # Clean up session
                                st.session_state.revisi_cart = []
                                st.session_state.revisi_faktur_key = ""
                                st.session_state.revisi_supplier = ""
                                st.rerun()
                            except Exception as e:
                                st.error(f"Gagal menyimpan revisi: {str(e)}")
                with col_sv2:
                    if st.button("✕ Batal Revisi", width="stretch"):
                        st.session_state.revisi_cart = []
                        st.session_state.revisi_faktur_key = ""
                        st.session_state.revisi_supplier = ""
                        st.rerun()


def render_purchase_finance():
    """Render halaman Finance — konfirmasi pembayaran PO yang PENDING."""
    db = st.session_state.db

    st.subheader("💳 Finance — Konfirmasi Pembayaran PO")

    # ── Stats ──
    pending_count = db.fetch_one("SELECT COUNT(DISTINCT no_faktur) as cnt FROM pembelian WHERE status_bayar = 'PENDING'")
    pending_value = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM pembelian WHERE status_bayar = 'PENDING'")
    kontrabon_value = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM pembelian WHERE status_bayar = 'KONTRA BON'")

    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.metric("📌 PO Pending", f"{pending_count['cnt']}" if pending_count else "0")
    with col_s2:
        val_pd = pending_value["total"] if pending_value else 0
        st.metric("💰 Nilai Pending", f"Rp {val_pd:,.0f}")
    with col_s3:
        val_kb = kontrabon_value["total"] if kontrabon_value else 0
        st.metric("⚠️ Total Kontrabon", f"Rp {val_kb:,.0f}")

    st.markdown("---")

    # ── Daftar PO Pending ──
    pending_fakturs = db.fetch_all(
        "SELECT no_faktur, tanggal, supplier, metode_bayar, COUNT(*) as items, SUM(total_harga) as total "
        "FROM pembelian WHERE status_bayar = 'PENDING' "
        "GROUP BY no_faktur ORDER BY created_at DESC"
    )

    if not pending_fakturs:
        st.success("✅ Tidak ada PO yang pending. Semua sudah dikonfirmasi.")
    else:
        st.markdown(f"### 📋 {len(pending_fakturs)} PO Menunggu Konfirmasi")

        # ── Tabel PO Pending ──
        df_pending = pd.DataFrame([dict(r) for r in pending_fakturs])
        df_pending = df_pending.rename(columns={
            "no_faktur": "No Faktur", "tanggal": "Tanggal", "supplier": "Supplier",
            "metode_bayar": "Metode Bayar", "items": "Item", "total": "Total",
        })
        df_pending["Total"] = df_pending["Total"].apply(lambda x: f"Rp {x:,.0f}")
        df_pending["Pilih"] = False
        st.dataframe(df_pending[["No Faktur", "Tanggal", "Supplier", "Metode Bayar", "Item", "Total"]], width="stretch", hide_index=True)

        st.markdown("---")

        # ── Konfirmasi per PO ──
        st.markdown("### ✅ Konfirmasi Pembayaran")

        faktur_options = [f"{r['no_faktur']} | {r['tanggal']} | {r['supplier']} | {r['metode_bayar']} | {r['items']} item | Rp {r['total']:,.0f}" for r in pending_fakturs]
        selected_faktur_label = st.selectbox(
            "Pilih PO untuk dikonfirmasi",
            faktur_options,
            key="finance_select_po",
        )
        selected_no_faktur = selected_faktur_label.split(" | ")[0]

        # Show detail items
        detail_items = db.fetch_all(
            "SELECT kode_sku, nama_barang, qty, satuan, harga_beli, total_harga FROM pembelian WHERE no_faktur = ?",
            (selected_no_faktur,),
        )
        if detail_items:
            st.markdown("**Detail Item:**")
            df_detail = pd.DataFrame([dict(r) for r in detail_items])
            df_detail["Harga Beli"] = df_detail["harga_beli"].apply(lambda x: f"Rp {x:,.0f}")
            df_detail["Total"] = df_detail["total_harga"].apply(lambda x: f"Rp {x:,.0f}")
            df_detail = df_detail.rename(columns={
                "kode_sku": "SKU", "nama_barang": "Nama Barang", "qty": "Qty",
                "satuan": "Satuan",
            })
            st.dataframe(df_detail[["SKU", "Nama Barang", "Qty", "Satuan", "Harga Beli", "Total"]], width="stretch", hide_index=True)

        st.markdown("---")
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            if st.button("✅ Konfirmasi LUNAS", type="primary", width="stretch"):
                db.execute("UPDATE pembelian SET status_bayar = 'LUNAS' WHERE no_faktur = ?", (selected_no_faktur,))
                st.success(f"PO '{selected_no_faktur}' dikonfirmasi LUNAS! ✅")
                st.rerun()
        with col_c2:
            if st.button("📋 Konfirmasi KONTRA BON", width="stretch"):
                db.execute("UPDATE pembelian SET status_bayar = 'KONTRA BON' WHERE no_faktur = ?", (selected_no_faktur,))
                st.success(f"PO '{selected_no_faktur}' dikonfirmasi sebagai KONTRA BON! 📋")
                st.rerun()
        with col_c3:
            if st.button("🔙 Kembalikan ke PENDING", width="stretch"):
                db.execute("UPDATE pembelian SET status_bayar = 'PENDING' WHERE no_faktur = ?", (selected_no_faktur,))
                st.info(f"PO '{selected_no_faktur}' dikembalikan ke PENDING.")
                st.rerun()

    st.markdown("---")

    # ── Riwayat Konfirmasi ──
    with st.expander("📋 Riwayat PO Sudah Dikonfirmasi (LUNAS / KONTRA BON)", expanded=False):
        confirmed = db.fetch_all(
            "SELECT no_faktur, tanggal, supplier, metode_bayar, status_bayar, COUNT(*) as items, SUM(total_harga) as total "
            "FROM pembelian WHERE status_bayar IN ('LUNAS', 'KONTRA BON') "
            "GROUP BY no_faktur ORDER BY created_at DESC LIMIT 50"
        )
        if confirmed:
            df_conf = pd.DataFrame([dict(r) for r in confirmed])
            df_conf = df_conf.rename(columns={
                "no_faktur": "No Faktur", "tanggal": "Tanggal", "supplier": "Supplier",
                "metode_bayar": "Metode Bayar", "status_bayar": "Status Bayar",
                "items": "Item", "total": "Total",
            })
            df_conf["Total"] = df_conf["Total"].apply(lambda x: f"Rp {x:,.0f}")

            def color_confirm(val):
                if val == "LUNAS":
                    return "background-color: #d4edda; color: #155724"
                elif val == "KONTRA BON":
                    return "background-color: #fff3cd; color: #856404"
                return ""

            styled_conf = df_conf.style.map(color_confirm, subset=["Status Bayar"])
            st.dataframe(styled_conf, width="stretch", hide_index=True)
        else:
            st.info("Belum ada PO yang dikonfirmasi.")


def render_purchase_archive():
    """Render arsip/export laporan pembelian."""
    db = st.session_state.db

    st.subheader("📁 Arsip Laporan Pembelian")

    # ── Export options ──
    st.markdown("### 📤 Export Laporan Pembelian")

    col_e1, col_e2 = st.columns(2)
    with col_e1:
        exp_supplier = st.selectbox(
            "Filter Supplier",
            ["Semua"] + [s["supplier"] for s in db.fetch_all("SELECT DISTINCT supplier FROM pembelian ORDER BY supplier")],
            key="archive_exp_supplier",
        )
    with col_e2:
        exp_period = st.selectbox(
            "Periode",
            ["Semua", "Hari Ini", "7 Hari Terakhir", "30 Hari Terakhir", "Bulan Ini"],
            key="archive_exp_period",
        )

    if st.button("📊 Generate Laporan Pembelian", type="primary"):
        query = "SELECT * FROM pembelian WHERE 1=1"
        params = []

        if exp_supplier != "Semua":
            query += " AND supplier = ?"
            params.append(exp_supplier)

        today = datetime.now()
        if exp_period == "Hari Ini":
            query += " AND tanggal = ?"
            params.append(today.strftime("%d-%m-%Y"))
        elif exp_period == "7 Hari Terakhir":
            start = today - timedelta(days=7)
            # Simple string comparison for dd-mm-yyyy format
            query += " AND date(substr(tanggal, 7, 4) || '-' || substr(tanggal, 4, 2) || '-' || substr(tanggal, 1, 2)) >= ?"
            params.append(start.strftime("%Y-%m-%d"))
        elif exp_period == "30 Hari Terakhir":
            start = today - timedelta(days=30)
            query += " AND date(substr(tanggal, 7, 4) || '-' || substr(tanggal, 4, 2) || '-' || substr(tanggal, 1, 2)) >= ?"
            params.append(start.strftime("%Y-%m-%d"))
        elif exp_period == "Bulan Ini":
            query += " AND substr(tanggal, 4, 2) = ?"
            params.append(today.strftime("%m"))

        query += " ORDER BY created_at DESC"
        rows = db.fetch_all(query, params)

        if not rows:
            st.warning("Tidak ada data untuk filter yang dipilih.")
        else:
            df_exp = pd.DataFrame([dict(r) for r in rows])
            now = datetime.now()
            filename = f"Laporan_Pembelian_{now.strftime('%d-%m-%Y_%H%M%S')}.xlsx"
            filepath = os.path.join(Config.SALES_FOLDER, filename)

            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                # Detail sheet
                df_exp.to_excel(writer, index=False, sheet_name="Detail Pembelian")

                # Summary sheet
                summary_rows = db.fetch_all(
                    "SELECT no_faktur, tanggal, supplier, COUNT(*) as items, SUM(total_harga) as total "
                    "FROM pembelian GROUP BY no_faktur ORDER BY created_at DESC",
                )
                if summary_rows:
                    df_sum = pd.DataFrame([dict(r) for r in summary_rows])
                    df_sum.to_excel(writer, index=False, sheet_name="Ringkasan")

                # Per SKU sheet
                sku_rows = db.fetch_all(
                    "SELECT kode_sku, nama_barang, SUM(qty) as total_qty, satuan, "
                    "AVG(harga_beli) as avg_harga, SUM(total_harga) as total "
                    "FROM pembelian GROUP BY kode_sku ORDER BY total DESC",
                )
                if sku_rows:
                    df_sku = pd.DataFrame([dict(r) for r in sku_rows])
                    df_sku.to_excel(writer, index=False, sheet_name="Per SKU")

                # Auto-adjust columns
                for sheet_name in writer.sheets:
                    ws = writer.sheets[sheet_name]
                    for col_idx, col in enumerate(ws.iter_cols(max_row=1, values_only=True), 1):
                        if col[0]:
                            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(len(str(col[0])) + 6, 40)

            with open(filepath, "rb") as fp:
                st.download_button(
                    "⬇️ Download Laporan Pembelian",
                    fp,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            st.success(f"✅ Laporan tersimpan: {filename}")

    # ── List existing exports ──
    st.markdown("---")
    st.markdown("### 📂 File Laporan Sebelumnya")
    if os.path.exists(Config.SALES_FOLDER):
        files = sorted(
            [f for f in os.listdir(Config.SALES_FOLDER) if f.startswith("Laporan_Pembelian_") and f.endswith(".xlsx")],
            reverse=True,
        )
        if files:
            for f in files[:10]:
                filepath = os.path.join(Config.SALES_FOLDER, f)
                size_kb = os.path.getsize(filepath) / 1024
                mod_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                col_f1, col_f2 = st.columns([3, 1])
                with col_f1:
                    st.markdown(f"📄 **{f}** — {size_kb:.1f} KB — {mod_time.strftime('%d-%m-%Y %H:%M')}")
                with col_f2:
                    with open(filepath, "rb") as fp:
                        st.download_button("⬇️ Download", fp, file_name=f, key=f"dl_purchase_{f}", width="stretch")
        else:
            st.info("Belum ada file laporan.")
    else:
        st.info("Folder laporan belum tersedia.")


# ==================== SALES / PENJUALAN FUNCTIONS ====================
def _auto_detect_sales_column(excel_cols: list, candidates: list) -> int:
    """Auto-detect sales column mapping from Excel headers."""
    for col_name in excel_cols[1:]:
        col_lower = str(col_name).lower().strip().replace(" ", "_").replace("-", "_")
        for candidate in candidates:
            cand_lower = candidate.lower().strip().replace(" ", "_").replace("-", "_")
            if col_lower == cand_lower:
                return excel_cols.index(col_name)
    for i, col_name in enumerate(excel_cols):
        if i == 0:
            continue
        col_lower = str(col_name).lower().strip().replace(" ", "_").replace("-", "_")
        for candidate in candidates:
            cand_lower = candidate.lower().strip().replace(" ", "_").replace("-", "_")
            if cand_lower in col_lower or col_lower in cand_lower:
                return i
    return 0


def _render_marketplace_tab(db, marketplace, mp_key):
    """Render upload form untuk satu marketplace spesifik."""
    st.markdown(f"### 📤 Upload File {marketplace}")

    uploaded_file = st.file_uploader(
        f"Upload File Excel Pesanan {marketplace} (.xlsx / .xls)",
        type=["xlsx", "xls"],
        key=f"sales_file_{mp_key}",
    )

    if uploaded_file is not None:
        try:
            df_raw = pd.read_excel(uploaded_file, engine="openpyxl")
            if df_raw.empty:
                st.error("File Excel kosong.")
            else:
                st.success(f"✅ File berhasil dibaca: **{len(df_raw)} baris**, {len(df_raw.columns)} kolom.")
                st.caption(f"Kolom terdeteksi: {', '.join(df_raw.columns.astype(str).tolist())}")

                # ── Marketplace-specific detection keywords ──
                if marketplace == "TikTok":
                    order_keys = ["no_pesanan", "order_id", "id_pesanan", "nomor_pesanan", "order_no", "no_order"]
                    resi_keys = ["no_resi", "resi", "tracking", "tracking_number", "awb", "nomor_resi", "no_awb"]
                    sku_keys = ["sku", "kode_sku", "product_code", "seller_sku", "kode_produk", "product_id"]
                    produk_keys = ["nama_produk", "product_name", "produk", "item_name", "nama_barang", "product_title"]
                    qty_keys = ["qty", "quantity", "jumlah", "kuantitas", "qty_pesanan", "order_qty"]
                    harga_keys = ["harga", "harga_jual", "price", "selling_price", "harga_satuan", "unit_price", "original_price"]
                    pembeli_keys = ["nama_pembeli", "buyer", "customer", "pembeli", "buyer_name", "buyer_username"]
                    toko_keys = ["toko", "nama_toko", "store", "shop", "nama_shop", "shop_name", "seller_name"]
                    kurir_keys = ["kurir", "courier", "pengiriman", "shipping", "ekspedisi", "logistik", "jasa_kirim", "shipping_carrier"]
                    tgl_order_keys = ["tanggal_pesanan", "order_date", "tgl_pesan", "waktu_pesanan", "created", "order_time", "create_time"]
                    tgl_kirim_keys = ["tanggal_pengiriman", "ship_date", "tgl_kirim", "waktu_kirim", "shipping_time", "delivery_date"]
                    status_keys = ["status", "status_pesanan", "order_status", "state", "order_state"]
                    ket_keys = ["keterangan", "ket", "notes", "remark", "catatan", "note"]
                elif marketplace == "Lazada":
                    order_keys = ["no_pesanan", "order_id", "id_pesanan", "order_number", "order_no", "nomor_pesanan"]
                    resi_keys = ["no_resi", "resi", "tracking", "tracking_number", "awb", "tracking_code"]
                    sku_keys = ["sku", "kode_sku", "seller_sku", "product_code", "kode_produk", "item_sku"]
                    produk_keys = ["nama_produk", "product_name", "produk", "item_name", "nama_barang", "title"]
                    qty_keys = ["qty", "quantity", "jumlah", "kuantitas", "qty_pesanan", "item_qty"]
                    harga_keys = ["harga", "harga_jual", "price", "selling_price", "unit_price", "item_price", "paid_price"]
                    pembeli_keys = ["nama_pembeli", "buyer", "customer", "pembeli", "buyer_name", "customer_name"]
                    toko_keys = ["toko", "nama_toko", "store", "shop", "nama_shop", "shop_name", "seller_name"]
                    kurir_keys = ["kurir", "courier", "pengiriman", "shipping", "ekspedisi", "logistik", "jasa_kirim", "shipping_provider"]
                    tgl_order_keys = ["tanggal_pesanan", "order_date", "tgl_pesan", "waktu_pesanan", "created", "order_created"]
                    tgl_kirim_keys = ["tanggal_pengiriman", "ship_date", "tgl_kirim", "waktu_kirim", "shipped_date"]
                    status_keys = ["status", "status_pesanan", "order_status", "state", "statuses"]
                    ket_keys = ["keterangan", "ket", "notes", "remark", "catatan", "note", "description"]
                else:  # Shopee
                    order_keys = ["no_pesanan", "order_id", "id_pesanan", "order_no", "nomor_pesanan", "order_number"]
                    resi_keys = ["no_resi", "resi", "tracking", "tracking_number", "awb", "nomor_resi", "no_resi_pengiriman"]
                    sku_keys = ["sku", "kode_sku", "product_code", "seller_sku", "kode_produk", "variation_sku"]
                    produk_keys = ["nama_produk", "product_name", "produk", "item_name", "nama_barang", "variation_name"]
                    qty_keys = ["qty", "quantity", "jumlah", "kuantitas", "qty_pesanan", "order_quantity"]
                    harga_keys = ["harga", "harga_jual", "price", "selling_price", "harga_satuan", "deal_price", "original_price"]
                    pembeli_keys = ["nama_pembeli", "buyer", "customer", "pembeli", "buyer_name", "buyer_username"]
                    toko_keys = ["toko", "nama_toko", "store", "shop", "nama_shop", "shop_name", "seller_name"]
                    kurir_keys = ["kurir", "courier", "pengiriman", "shipping", "ekspedisi", "logistik", "jasa_kirim", "shipping_carrier"]
                    tgl_order_keys = ["tanggal_pesanan", "order_date", "tgl_pesan", "waktu_pesanan", "created", "order_creation_date"]
                    tgl_kirim_keys = ["tanggal_pengiriman", "ship_date", "tgl_kirim", "waktu_kirim", "ship_by_date"]
                    status_keys = ["status", "status_pesanan", "order_status", "state", "order_status_final"]
                    ket_keys = ["keterangan", "ket", "notes", "remark", "catatan", "note", "description"]

                # ── Column Mapping ──
                st.markdown("#### 🔗 Mapping Kolom")
                excel_cols = [""] + df_raw.columns.tolist()

                col_m1, col_m2, col_m3 = st.columns(3)
                with col_m1:
                    map_order = st.selectbox("No Pesanan *", excel_cols, key=f"map_order_{mp_key}",
                                             index=_auto_detect_sales_column(excel_cols, order_keys))
                    map_resi = st.selectbox("No Resi", excel_cols, key=f"map_resi_{mp_key}",
                                            index=_auto_detect_sales_column(excel_cols, resi_keys))
                    map_tgl_order = st.selectbox("Tanggal Pesanan", excel_cols, key=f"map_tgl_order_{mp_key}",
                                                 index=_auto_detect_sales_column(excel_cols, tgl_order_keys))
                    map_tgl_kirim = st.selectbox("Tanggal Pengiriman", excel_cols, key=f"map_tgl_kirim_{mp_key}",
                                                 index=_auto_detect_sales_column(excel_cols, tgl_kirim_keys))
                with col_m2:
                    map_sku = st.selectbox("SKU Produk", excel_cols, key=f"map_sku_{mp_key}",
                                           index=_auto_detect_sales_column(excel_cols, sku_keys))
                    map_produk = st.selectbox("Nama Produk", excel_cols, key=f"map_produk_{mp_key}",
                                              index=_auto_detect_sales_column(excel_cols, produk_keys))
                    map_qty = st.selectbox("Qty", excel_cols, key=f"map_qty_{mp_key}",
                                           index=_auto_detect_sales_column(excel_cols, qty_keys))
                    map_harga = st.selectbox("Harga Jual", excel_cols, key=f"map_harga_{mp_key}",
                                             index=_auto_detect_sales_column(excel_cols, harga_keys))
                with col_m3:
                    map_pembeli = st.selectbox("Nama Pembeli", excel_cols, key=f"map_pembeli_{mp_key}",
                                               index=_auto_detect_sales_column(excel_cols, pembeli_keys))
                    map_toko = st.selectbox("Nama Toko", excel_cols, key=f"map_toko_{mp_key}",
                                            index=_auto_detect_sales_column(excel_cols, toko_keys))
                    map_kurir = st.selectbox("Kurir / Pengiriman", excel_cols, key=f"map_kurir_{mp_key}",
                                             index=_auto_detect_sales_column(excel_cols, kurir_keys))
                    map_status = st.selectbox("Status Pesanan", excel_cols, key=f"map_status_{mp_key}",
                                              index=_auto_detect_sales_column(excel_cols, status_keys))
                    map_ket = st.selectbox("Keterangan", excel_cols, key=f"map_ket_{mp_key}",
                                           index=_auto_detect_sales_column(excel_cols, ket_keys))

                # ── Toko Select (Dropdown dari Database) ──
                toko_list = db.fetch_all("SELECT nama FROM toko ORDER BY nama")
                toko_options = [t["nama"] for t in toko_list] if toko_list else []
                toko_options_with_custom = toko_options + ["➕ Toko Baru (Ketik Manual)..."]
                
                col_t1, col_t2 = st.columns([2, 1])
                with col_t1:
                    selected_toko_option = st.selectbox(
                        "🏪 Nama Toko",
                        toko_options_with_custom,
                        key=f"sales_toko_select_{mp_key}",
                    )
                with col_t2:
                    st.write("")
                    if selected_toko_option == "➕ Toko Baru (Ketik Manual)...":
                        st.caption("⬇️ Ketik nama toko baru di bawah")
                    elif selected_toko_option:
                        st.caption("✅ Dari daftar toko")
                
                if selected_toko_option == "➕ Toko Baru (Ketik Manual)...":
                    toko_manual = st.text_input(
                        "✏️ Nama Toko Baru",
                        placeholder="Ketik nama toko baru...",
                        key=f"sales_toko_manual_{mp_key}",
                    )
                else:
                    toko_manual = selected_toko_option

                # ── Preview ──
                if map_order:
                    st.markdown("#### 👁️ Preview Data")
                    preview_cols = [c for c in [map_order, map_resi, map_tgl_order, map_kurir, map_produk, map_sku, map_qty, map_harga, map_pembeli, map_toko, map_status] if c]
                    if preview_cols:
                        st.dataframe(df_raw[preview_cols].head(20), width="stretch", hide_index=True)
                        if len(df_raw) > 20:
                            st.caption(f"... dan {len(df_raw) - 20} baris lainnya.")

                    # ── SKU Matching Preview ──
                    st.markdown("#### 🔗 Preview Pencocokan SKU")
                    all_sku = {s["kode_sku"].upper(): s for s in db.fetch_all("SELECT kode_sku, nama_barang, harga_jual FROM sku")}
                    match_count = 0
                    no_match_count = 0
                    match_preview = []

                    for idx, row in df_raw.head(30).iterrows():
                        raw_sku = _safe_str(row.get(map_sku)) if map_sku else ""
                        raw_produk = _safe_str(row.get(map_produk)) if map_produk else ""
                        matched = raw_sku.upper() if raw_sku and raw_sku.upper() in all_sku else ""
                        if not matched and raw_produk:
                            for kode, s in all_sku.items():
                                if raw_produk.lower() in s["nama_barang"].lower() or s["nama_barang"].lower() in raw_produk.lower():
                                    matched = kode
                                    break
                        if matched:
                            match_count += 1
                        else:
                            no_match_count += 1
                        if idx < 15:
                            match_preview.append({
                                "No Pesanan": _safe_str(row.get(map_order)),
                                "Produk": raw_produk[:40] if raw_produk else "-",
                                "SKU Input": raw_sku,
                                "SKU Terdeteksi": matched or "❌ TIDAK COCOK",
                            })

                    if match_preview:
                        df_match = pd.DataFrame(match_preview)
                        st.dataframe(df_match, width="stretch", hide_index=True)
                        st.caption(f"Preview 15 baris pertama. Total: {match_count} cocok, {no_match_count} tidak cocok.")

                    # ── Import ──
                    st.markdown("---")
                    if st.button(f"🚀 Import {marketplace} & Cocokkan SKU", type="primary", key=f"btn_import_{mp_key}"):
                        if not map_order:
                            st.error("Kolom No Pesanan wajib di-mapping!")
                        else:
                            imported = 0
                            upserted = 0
                            matched_sku = 0
                            errors = 0
                            error_details = []

                            for idx, row in df_raw.iterrows():
                                try:
                                    no_pesanan = _safe_str(row.get(map_order))
                                    if not no_pesanan:
                                        errors += 1
                                        continue

                                    # Extract ALL fields first
                                    raw_sku = _safe_str(row.get(map_sku)) if map_sku else ""
                                    nama_produk = _safe_str(row.get(map_produk)) if map_produk else ""
                                    no_resi = _safe_str(row.get(map_resi)) if map_resi else ""
                                    tgl_order = _safe_str(row.get(map_tgl_order)) if map_tgl_order else ""
                                    tgl_kirim = _safe_str(row.get(map_tgl_kirim)) if map_tgl_kirim else ""
                                    qty = _safe_int(row.get(map_qty)) if map_qty else 1
                                    if qty < 1:
                                        qty = 1
                                    harga = _safe_float(row.get(map_harga)) if map_harga else 0
                                    pembeli = _safe_str(row.get(map_pembeli)) if map_pembeli else ""
                                    toko_row = _safe_str(row.get(map_toko)) if map_toko else ""
                                    kurir = _safe_str(row.get(map_kurir)) if map_kurir else ""
                                    status = _safe_str(row.get(map_status)) if map_status else ""
                                    ket = _safe_str(row.get(map_ket)) if map_ket else ""
                                    nama_toko_final = toko_manual.strip() if toko_manual.strip() else toko_row

                                    # SKU matching
                                    sku_detected = ""
                                    if raw_sku and raw_sku.upper() in all_sku:
                                        sku_detected = raw_sku.upper()
                                        matched_sku += 1
                                    elif nama_produk:
                                        for kode, s in all_sku.items():
                                            if nama_produk.lower() in s["nama_barang"].lower() or s["nama_barang"].lower() in nama_produk.lower():
                                                sku_detected = kode
                                                matched_sku += 1
                                                break

                                    total = harga * qty

                                    # Auto-save toko
                                    if nama_toko_final and nama_toko_final != "Mitra Mulia Abadi":
                                        existing_toko = db.fetch_one("SELECT id FROM toko WHERE nama = ?", (nama_toko_final,))
                                        if not existing_toko:
                                            try:
                                                db.execute("INSERT INTO toko (nama) VALUES (?)", (nama_toko_final,))
                                            except:
                                                pass

                                    # ── Upsert: UPDATE if exists, INSERT if new ──
                                    existing = db.fetch_one(
                                        "SELECT id, no_resi, status_pesanan FROM penjualan WHERE no_pesanan = ? AND marketplace = ? AND nama_produk = ?",
                                        (no_pesanan, marketplace, nama_produk),
                                    )

                                    if existing:
                                        # UPSERT: update only if new data is non-empty (fill in blanks)
                                        old_resi = existing["no_resi"] or ""
                                        old_status = existing["status_pesanan"] or ""

                                        new_resi = no_resi if no_resi else old_resi
                                        new_status = status if status else old_status

                                        db.execute(
                                            """UPDATE penjualan SET no_resi = ?, tanggal_pengiriman = ?,
                                               qty = ?, harga_jual = ?, total_harga = ?,
                                               kurir = ?, status_pesanan = ?, keterangan = ?,
                                               sku_terdeteksi = ?, nama_toko = ?
                                               WHERE id = ?""",
                                            (new_resi, tgl_kirim if tgl_kirim else None,
                                             qty, harga, total,
                                             kurir if kurir else None, new_status, ket if ket else None,
                                             sku_detected if sku_detected else None, nama_toko_final if nama_toko_final else None,
                                             existing["id"]),
                                        )
                                        upserted += 1
                                    else:
                                        # INSERT new
                                        db.execute(
                                            """INSERT INTO penjualan (marketplace, no_pesanan, no_resi, tanggal_pesanan,
                                               tanggal_pengiriman, sku_terdeteksi, nama_produk, qty, harga_jual,
                                               total_harga, nama_pembeli, nama_toko, kurir, status_pesanan, keterangan)
                                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                            (marketplace, no_pesanan, no_resi, tgl_order, tgl_kirim,
                                             sku_detected, nama_produk, qty, harga, total,
                                             pembeli, nama_toko_final, kurir, status, ket),
                                        )
                                        imported += 1
                                except Exception as e:
                                    errors += 1
                                    error_details.append(f"Baris {idx + 2}: {str(e)}")

                            st.markdown("### 📊 Hasil Import")
                            total_processed = imported + upserted
                            col_r1, col_r2, col_r3, col_r4, col_r5 = st.columns(5)
                            with col_r1:
                                st.metric("✅ Baru", imported)
                            with col_r2:
                                st.metric("🔄 Diupdate (Upsert)", upserted)
                            with col_r3:
                                st.metric("🔗 SKU Cocok", matched_sku)
                            with col_r4:
                                st.metric("⚠️ SKU Tidak Cocok", total_processed - matched_sku)
                            with col_r5:
                                st.metric("❌ Error/Skip", errors)

                            if error_details:
                                with st.expander(f"⚠️ {len(error_details)} error detail"):
                                    for e in error_details[:20]:
                                        st.caption(f"• {e}")

                            msg_parts = []
                            if imported > 0:
                                msg_parts.append(f"{imported} baru")
                            if upserted > 0:
                                msg_parts.append(f"{upserted} diupdate (contoh: Resi yang sebelumnya kosong diisi)")
                            st.success(f"Import selesai! {', '.join(msg_parts)} dari {marketplace}.")
                            if st.button("🔄 Refresh", width="stretch", key=f"btn_refresh_{mp_key}"):
                                st.rerun()

        except Exception as e:
            st.error(f"Gagal membaca file Excel: {str(e)}")


def render_sales_input():
    """Render upload pesanan dari marketplace — tab terpisah per marketplace."""
    db = st.session_state.db

    st.subheader("📦 Input Resi & No Pesanan (Marketplace)")

    st.markdown("""
    Upload file Excel dari marketplace. Setiap marketplace punya tab upload sendiri karena format kolom berbeda.
    """)

    tab1, tab2, tab3 = st.tabs(["🟠 Shopee", "⚫ TikTok", "🔵 Lazada"])

    with tab1:
        _render_marketplace_tab(db, "Shopee", "shopee")
    with tab2:
        _render_marketplace_tab(db, "TikTok", "tiktok")
    with tab3:
        _render_marketplace_tab(db, "Lazada", "lazada")

    # ── Stats ──
    st.markdown("---")
    st.markdown("### 📊 Data Penjualan Saat Ini")
    stats_sales = db.fetch_one("SELECT COUNT(*) as rows, COUNT(DISTINCT no_pesanan) as orders, COALESCE(SUM(total_harga), 0) as total FROM penjualan")
    sku_matched = db.fetch_one("SELECT COUNT(*) as cnt FROM penjualan WHERE sku_terdeteksi != ''")

    col_st1, col_st2, col_st3, col_st4, col_st5 = st.columns(5)
    with col_st1:
        st.metric("📦 Total Pesanan (unik)", f"{stats_sales['orders']:,}" if stats_sales else "0")
    with col_st2:
        st.metric("📋 Total Item (baris)", f"{stats_sales['rows']:,}" if stats_sales else "0")
    with col_st3:
        st.metric("💰 Total Nilai", f"Rp {stats_sales['total']:,.0f}" if stats_sales else "Rp 0")
    with col_st4:
        total_s = stats_sales["rows"] if stats_sales else 0
        matched_s = sku_matched["cnt"] if sku_matched else 0
        pct = f"{(matched_s / total_s * 100):.0f}%" if total_s > 0 else "0%"
        st.metric("🔗 SKU Cocok", f"{matched_s} ({pct})")
    with col_st5:
        st.write("")
        if st.button("🔄 Reset Form", width="stretch"):
            st.rerun()

    # ── Hapus Data (Reset) ──
    st.markdown("---")
    with st.expander("🗑️ Hapus / Reset Data Penjualan", expanded=False):
        st.warning("⚠️ Hati-hati! Data yang dihapus tidak bisa dikembalikan.")
        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1:
            del_mp = st.selectbox("Marketplace", ["Semua", "TikTok", "Shopee", "Lazada"], key="sales_del_mp")
        with col_d2:
            del_date = st.date_input("Dari Tanggal", value=None, key="sales_del_date")
            del_date_str = del_date.strftime("%d-%m-%Y") if del_date else ""
        with col_d3:
            st.write("")
            st.write("")
            if st.button("🗑️ Hapus Data", width="stretch", type="primary"):
                del_query = "DELETE FROM penjualan WHERE 1=1"
                del_params = []
                if del_mp != "Semua":
                    del_query += " AND marketplace = ?"
                    del_params.append(del_mp)
                if del_date_str:
                    del_query += " AND tanggal_pesanan = ?"
                    del_params.append(del_date_str)

                # Count before delete
                count_before = db.fetch_one(f"SELECT COUNT(*) as cnt FROM penjualan WHERE 1=1" +
                                            (f" AND marketplace = ?" if del_mp != "Semua" else "") +
                                            (f" AND tanggal_pesanan = ?" if del_date_str else ""),
                                            del_params if del_params else [])

                if count_before and count_before["cnt"] > 0:
                    db.execute(del_query, del_params if del_params else [])
                    st.success(f"✅ {count_before['cnt']} data dihapus.")
                    st.rerun()
                else:
                    st.info("Tidak ada data yang sesuai untuk dihapus.")


def render_sales_daily_report():
    """Render laporan penjualan harian dengan matching SKU."""
    db = st.session_state.db

    st.subheader("📊 Laporan Penjualan Harian")

    # ── Filters ──
    col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
    with col_f1:
        mp_filter = st.selectbox(
            "Marketplace",
            ["Semua", "TikTok", "Shopee", "Lazada"],
            key="sales_rpt_marketplace",
        )
    with col_f2:
        # Get distinct toko from penjualan
        all_toko = db.fetch_all("SELECT DISTINCT nama_toko FROM penjualan WHERE nama_toko != '' ORDER BY nama_toko")
        toko_list = ["Semua"] + [t["nama_toko"] for t in all_toko]
        toko_filter = st.selectbox("Toko", toko_list, key="sales_rpt_toko")
    with col_f3:
        today = datetime.now()
        rpt_date = st.date_input(
            "Tanggal",
            value=today.date(),
            key="sales_rpt_date",
        )
        rpt_date_str = rpt_date.strftime("%d-%m-%Y") if rpt_date else today.strftime("%d-%m-%Y")
    with col_f4:
        search_sales = st.text_input(
            "🔍 Cari No Resi / No Pesanan",
            placeholder="Ketik resi atau no pesanan...",
            key="sales_rpt_search",
        )
    with col_f5:
        group_by = st.selectbox(
            "Kelompokkan",
            ["Per SKU", "Per Marketplace", "Per Toko", "Per Produk"],
            key="sales_rpt_group",
        )

    # ── Build query ──
    query = "SELECT * FROM penjualan WHERE 1=1"
    params = []

    if mp_filter != "Semua":
        query += " AND marketplace = ?"
        params.append(mp_filter)

    if search_sales:
        query += " AND (no_pesanan LIKE ? OR no_resi LIKE ?)"
        params.extend([f"%{search_sales}%", f"%{search_sales}%"])

    if toko_filter != "Semua":
        query += " AND nama_toko = ?"
        params.append(toko_filter)

    if rpt_date_str:
        query += " AND tanggal_pesanan = ?"
        params.append(rpt_date_str)

    query += " ORDER BY created_at DESC"

    rows = db.fetch_all(query, params)

    # ── Build summary params (without search, for grouped queries) ──
    summary_params = []
    if mp_filter != "Semua":
        summary_params.append(mp_filter)
    if toko_filter != "Semua":
        summary_params.append(toko_filter)
    if rpt_date_str:
        summary_params.append(rpt_date_str)

    st.markdown("---")

    if not rows:
        st.info(f"📭 Tidak ada data penjualan untuk tanggal {rpt_date_str}.")
    else:
        distinct_orders_header = len(set(r["no_pesanan"] for r in rows))
        st.markdown(f"### 📋 {distinct_orders_header} Pesanan ({len(rows)} item) — {rpt_date_str}")

        df_rpt = pd.DataFrame([dict(r) for r in rows])
        df_rpt = df_rpt.rename(columns={
            "marketplace": "Marketplace", "no_pesanan": "No Pesanan", "no_resi": "No Resi",
            "tanggal_pesanan": "Tgl Pesan", "sku_terdeteksi": "SKU", "nama_produk": "Produk",
            "qty": "Qty", "harga_jual": "Harga", "total_harga": "Total",
            "nama_pembeli": "Pembeli", "nama_toko": "Toko", "kurir": "Kurir", "status_pesanan": "Status",
        })
        df_rpt["Harga"] = df_rpt["Harga"].apply(lambda x: f"Rp {x:,.0f}")
        df_rpt["Total"] = df_rpt["Total"].apply(lambda x: f"Rp {x:,.0f}")

        # Color SKU unmatched
        def color_sku(val):
            if not val or val.strip() == "":
                return "background-color: #f8d7da; color: #721c24"
            return ""

        display_cols = ["Marketplace", "No Pesanan", "No Resi", "Tgl Pesan", "Kurir", "SKU", "Produk", "Qty", "Harga", "Total", "Pembeli", "Toko", "Status"]
        styled = df_rpt[display_cols].style.map(color_sku, subset=["SKU"])
        st.dataframe(styled, width="stretch", height=450, hide_index=True)

        # ── Summary ──
        st.markdown("---")
        total_qty = sum(r["qty"] for r in rows)
        total_val = sum(r["total_harga"] for r in rows)
        matched = sum(1 for r in rows if r["sku_terdeteksi"])
        distinct_orders = len(set(r["no_pesanan"] for r in rows))
        col_sm1, col_sm2, col_sm3, col_sm4, col_sm5 = st.columns(5)
        with col_sm1:
            st.metric("📦 Pesanan (unik)", distinct_orders)
        with col_sm2:
            st.metric("📋 Item (baris)", len(rows))
        with col_sm3:
            st.metric("📊 Total Qty", total_qty)
        with col_sm4:
            st.metric("💰 Total", f"Rp {total_val:,.0f}")
        with col_sm5:
            pct = f"{(matched / len(rows) * 100):.0f}%" if rows else "0%"
            st.metric("🔗 SKU Cocok", f"{matched} ({pct})")

        # ── Grouped Summary ──
        st.markdown("---")
        if group_by == "Per SKU":
            st.markdown("### 📊 Ringkasan per SKU")
            sku_summary = db.fetch_all(
                "SELECT sku_terdeteksi, nama_produk, COUNT(*) as jml_pesanan, SUM(qty) as total_qty, "
                "SUM(total_harga) as total, marketplace "
                "FROM penjualan WHERE sku_terdeteksi != ''" +
                (" AND marketplace = ?" if mp_filter != "Semua" else "") + (" AND nama_toko = ?" if toko_filter != "Semua" else "") +
                (" AND tanggal_pesanan = ?" if rpt_date_str else "") +
                " GROUP BY sku_terdeteksi ORDER BY total DESC",
                (summary_params if summary_params else []),
            )
            if sku_summary:
                df_sku = pd.DataFrame([dict(r) for r in sku_summary])
                df_sku = df_sku.rename(columns={
                    "sku_terdeteksi": "SKU", "nama_produk": "Produk",
                    "jml_pesanan": "Jml Pesanan", "total_qty": "Total Qty",
                    "total": "Total", "marketplace": "Marketplace",
                })
                df_sku["Total"] = df_sku["Total"].apply(lambda x: f"Rp {x:,.0f}")
                st.dataframe(df_sku, width="stretch", hide_index=True)

        elif group_by == "Per Marketplace":
            st.markdown("### 📊 Ringkasan per Marketplace")
            mp_summary = db.fetch_all(
                "SELECT marketplace, COUNT(*) as jml_pesanan, SUM(qty) as total_qty, "
                "SUM(total_harga) as total, "
                "SUM(CASE WHEN sku_terdeteksi != '' THEN 1 ELSE 0 END) as sku_matched "
                "FROM penjualan WHERE 1=1" +
                (" AND marketplace = ?" if mp_filter != "Semua" else "") + (" AND nama_toko = ?" if toko_filter != "Semua" else "") +
                (" AND tanggal_pesanan = ?" if rpt_date_str else "") +
                " GROUP BY marketplace ORDER BY total DESC",
                (summary_params if summary_params else []),
            )
            if mp_summary:
                df_mp = pd.DataFrame([dict(r) for r in mp_summary])
                df_mp = df_mp.rename(columns={
                    "marketplace": "Marketplace", "jml_pesanan": "Jml Pesanan",
                    "total_qty": "Total Qty", "total": "Total", "sku_matched": "SKU Cocok",
                })
                df_mp["Total"] = df_mp["Total"].apply(lambda x: f"Rp {x:,.0f}")
                st.dataframe(df_mp, width="stretch", hide_index=True)

        elif group_by == "Per Toko":
            st.markdown("### 📊 Ringkasan per Toko")
            toko_summary = db.fetch_all(
                "SELECT nama_toko, COUNT(*) as jml_pesanan, SUM(qty) as total_qty, "
                "SUM(total_harga) as total, "
                "SUM(CASE WHEN sku_terdeteksi != '' THEN 1 ELSE 0 END) as sku_matched "
                "FROM penjualan WHERE 1=1" +
                (" AND marketplace = ?" if mp_filter != "Semua" else "") + (" AND nama_toko = ?" if toko_filter != "Semua" else "") +
                (" AND tanggal_pesanan = ?" if rpt_date_str else "") +
                " GROUP BY nama_toko ORDER BY total DESC",
                (summary_params if summary_params else []),
            )
            if toko_summary:
                df_toko = pd.DataFrame([dict(r) for r in toko_summary])
                df_toko = df_toko.rename(columns={
                    "nama_toko": "Toko", "jml_pesanan": "Jml Pesanan",
                    "total_qty": "Total Qty", "total": "Total", "sku_matched": "SKU Cocok",
                })
                df_toko["Total"] = df_toko["Total"].apply(lambda x: f"Rp {x:,.0f}")
                st.dataframe(df_toko, width="stretch", hide_index=True)

        else:  # Per Produk
            st.markdown("### 📊 Ringkasan per Produk")
            prod_summary = db.fetch_all(
                "SELECT nama_produk, COUNT(*) as jml_pesanan, SUM(qty) as total_qty, "
                "SUM(total_harga) as total, marketplace "
                "FROM penjualan WHERE 1=1" +
                (" AND marketplace = ?" if mp_filter != "Semua" else "") + (" AND nama_toko = ?" if toko_filter != "Semua" else "") +
                (" AND tanggal_pesanan = ?" if rpt_date_str else "") +
                " GROUP BY nama_produk ORDER BY total DESC LIMIT 30",
                (summary_params if summary_params else []),
            )
            if prod_summary:
                df_prod = pd.DataFrame([dict(r) for r in prod_summary])
                df_prod = df_prod.rename(columns={
                    "nama_produk": "Produk", "jml_pesanan": "Jml Pesanan",
                    "total_qty": "Total Qty", "total": "Total", "marketplace": "Marketplace",
                })
                df_prod["Total"] = df_prod["Total"].apply(lambda x: f"Rp {x:,.0f}")
                st.dataframe(df_prod, width="stretch", hide_index=True)

        # ── Export ──
        st.markdown("---")
        if st.button("📊 Export Laporan Penjualan (Excel)", type="primary"):
            filename = f"Laporan_Penjualan_{rpt_date_str}_{mp_filter if mp_filter != 'Semua' else 'Semua'}.xlsx"
            filepath = os.path.join(Config.SALES_FOLDER, filename)
            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df_rpt.to_excel(writer, index=False, sheet_name="Detail")
                if group_by == "Per SKU" and sku_summary:
                    pd.DataFrame([dict(r) for r in sku_summary]).to_excel(writer, index=False, sheet_name="Per SKU")
                elif group_by == "Per Marketplace" and mp_summary:
                    pd.DataFrame([dict(r) for r in mp_summary]).to_excel(writer, index=False, sheet_name="Per Marketplace")
                elif prod_summary:
                    pd.DataFrame([dict(r) for r in prod_summary]).to_excel(writer, index=False, sheet_name="Per Produk")
            with open(filepath, "rb") as fp:
                st.download_button(
                    "⬇️ Download Laporan",
                    fp,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            st.success(f"✅ Laporan tersimpan: {filename}")


def render_ai_supervisor():
    """AI Supervisor — analisa & rekomendasi kinerja operasional."""
    db = st.session_state.db
    today_str = datetime.now().strftime("%d-%m-%Y")
    today_date = datetime.now().strftime("%Y-%m-%d")

    st.subheader("🤖 AI Supervisor — Analisa Kinerja Operasional")
    st.caption("AI menganalisa seluruh pipeline: Pesanan Masuk → Packing → Handover → Selesai")

    # ═══════════════════════════════════════════
    # 📊 QUERY ALL METRICS
    # ═══════════════════════════════════════════

    # Total orders (unique no_pesanan)
    total_orders = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan")
    total_orders_cnt = total_orders["cnt"] if total_orders else 0

    total_items = db.fetch_one("SELECT COUNT(*) as cnt FROM penjualan")
    total_items_cnt = total_items["cnt"] if total_items else 0

    # Orders with resi (unique no_resi)
    with_resi = db.fetch_one("SELECT COUNT(DISTINCT no_resi) as cnt FROM penjualan WHERE no_resi != '' AND no_resi IS NOT NULL")
    with_resi_cnt = with_resi["cnt"] if with_resi else 0

    tanpa_resi = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan WHERE no_resi = '' OR no_resi IS NULL")
    tanpa_resi_cnt = tanpa_resi["cnt"] if tanpa_resi else 0

    # Scan stats
    packed_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED'")
    packed = packed_cnt["cnt"] if packed_cnt else 0

    pending_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PENDING'")
    pending = pending_cnt["cnt"] if pending_cnt else 0

    cancel_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'CANCEL'")
    cancel = cancel_cnt["cnt"] if cancel_cnt else 0

    instant_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED' AND tipe_kiriman = 'INSTANT'")
    instant = instant_cnt["cnt"] if instant_cnt else 0

    reguler_packed = packed - instant

    besar_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED' AND kategori = 'BESAR'")
    besar = besar_cnt["cnt"] if besar_cnt else 0

    # Handover ready (PACKED, not yet exported)
    handover_ready_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED'")
    handover_ready = handover_ready_cnt["cnt"] if handover_ready_cnt else 0

    # Today's stats
    today_scans = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE tanggal = ?", (today_str,))
    today_scan_cnt = today_scans["cnt"] if today_scans else 0

    today_packed = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE tanggal = ? AND status = 'PACKED'", (today_str,))
    today_packed_cnt = today_packed["cnt"] if today_packed else 0

    # Revenue
    revenue = db.fetch_one(
        "SELECT SUM(p.total_harga) as total FROM penjualan p "
        "JOIN scan_aktif s ON p.no_resi = s.resi WHERE s.status = 'PACKED'"
    )
    revenue_packed = revenue["total"] if revenue and revenue["total"] else 0

    total_revenue = db.fetch_one("SELECT SUM(total_harga) as total FROM penjualan")
    total_rev = total_revenue["total"] if total_revenue and total_revenue["total"] else 0

    # Per Marketplace
    mp_stats = db.fetch_all(
        "SELECT marketplace, COUNT(*) as total_orders, "
        "SUM(CASE WHEN no_resi != '' AND no_resi IS NOT NULL THEN 1 ELSE 0 END) as with_resi, "
        "SUM(total_harga) as revenue "
        "FROM penjualan GROUP BY marketplace ORDER BY total_orders DESC"
    )

    # Per Toko
    toko_perf = db.fetch_all(
        "SELECT p.nama_toko, COUNT(DISTINCT p.no_pesanan) as total_orders, "
        "COUNT(DISTINCT s.resi) as packed, "
        "SUM(CASE WHEN s.status = 'PACKED' THEN p.total_harga ELSE 0 END) as packed_revenue "
        "FROM penjualan p LEFT JOIN scan_aktif s ON p.no_resi = s.resi AND s.status = 'PACKED' "
        "WHERE p.nama_toko != '' "
        "GROUP BY p.nama_toko ORDER BY packed DESC"
    )

    # Per Ekspedisi (from scan_aktif)
    ekspedisi_perf = db.fetch_all(
        "SELECT ekspedisi, COUNT(*) as total, "
        "SUM(CASE WHEN status = 'PACKED' THEN 1 ELSE 0 END) as packed, "
        "SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending, "
        "SUM(CASE WHEN status = 'CANCEL' THEN 1 ELSE 0 END) as cancel "
        "FROM scan_aktif WHERE ekspedisi != 'CANCEL' GROUP BY ekspedisi ORDER BY total DESC"
    )

    # SKU match rate
    sku_match = db.fetch_one(
        "SELECT COUNT(*) as cnt FROM penjualan WHERE sku_terdeteksi != '' AND sku_terdeteksi IS NOT NULL"
    )
    sku_matched_cnt = sku_match["cnt"] if sku_match else 0
    sku_match_pct = (sku_matched_cnt / total_items_cnt * 100) if total_items_cnt > 0 else 0

    # ── Instant / Prioritas Orders ──
    instant_keywords = ['%instant%', '%same%day%', '%gosend%', '%grab%express%', '%prioritas%']
    instant_where = " OR ".join([f"LOWER(kurir) LIKE '{kw}'" for kw in instant_keywords])
    instant_orders = db.fetch_one(
        f"SELECT COUNT(*) as cnt FROM penjualan WHERE ({instant_where}) AND no_resi != '' AND no_resi IS NOT NULL"
    )
    instant_total = instant_orders["cnt"] if instant_orders else 0

    instant_not_packed = db.fetch_one(
        f"SELECT COUNT(*) as cnt FROM penjualan WHERE ({instant_where}) "
        f"AND no_resi != '' AND no_resi IS NOT NULL "
        f"AND (status_pesanan != 'PACKED' AND status_pesanan != 'CANCEL')"
    )
    instant_waiting = instant_not_packed["cnt"] if instant_not_packed else 0

    instant_packed = db.fetch_one(
        f"SELECT COUNT(*) as cnt FROM penjualan WHERE ({instant_where}) "
        f"AND status_pesanan = 'PACKED'"
    )
    instant_done = instant_packed["cnt"] if instant_packed else 0

    # ═══════════════════════════════════════════
    # 🧠 AI INSIGHT ENGINE
    # ═══════════════════════════════════════════
    insights = []
    alerts = []
    recommendations = []

    # Pipeline health
    if total_orders_cnt > 0:
        packing_rate = (packed / with_resi_cnt * 100) if with_resi_cnt > 0 else 0
        success_rate = (packed / total_orders_cnt * 100) if total_orders_cnt > 0 else 0

        if packing_rate >= 90:
            insights.append(("✅", "Efisiensi packing sangat baik", f"{packing_rate:.0f}% resi sudah dipacking — tim operasional bekerja optimal.", "good"))
        elif packing_rate >= 60:
            insights.append(("⚡", "Packing berjalan normal", f"{packing_rate:.0f}% sudah dipacking, masih ada {with_resi_cnt - packed} resi dalam antrian.", "normal"))
        elif packing_rate > 0:
            insights.append(("⚠️", "Packing perlu dipercepat", f"Hanya {packing_rate:.0f}% yang sudah dipacking. {with_resi_cnt - packed} resi belum tersentuh.", "warn"))
        else:
            insights.append(("🔴", "Belum ada aktivitas packing", "Tim belum mulai packing. Segera mulai scan resi di SCAN Operasional.", "critical"))

        # Cancel rate
        if total_orders_cnt > 0:
            cancel_rate = (cancel / total_orders_cnt * 100)
            if cancel_rate > 10:
                alerts.append(("🔴", "Cancel Rate Tinggi", f"{cancel_rate:.0f}% pesanan dibatalkan — perlu investigasi penyebab cancel."))
            elif cancel_rate > 5:
                alerts.append(("⚠️", "Cancel Rate Meningkat", f"{cancel_rate:.0f}% cancel — pantau terus dan evaluasi stok/proses."))

        # Orders without resi
        if tanpa_resi_cnt > 0:
            tanpa_pct = (tanpa_resi_cnt / total_orders_cnt * 100)
            if tanpa_pct > 30:
                alerts.append(("🔴", "Banyak Pesanan Tanpa Resi", f"{tanpa_resi_cnt} pesanan ({tanpa_pct:.0f}%) belum punya no resi. Segera update di Input Resi & Pesanan!"))
            elif tanpa_pct > 10:
                alerts.append(("⚠️", "Pesanan Perlu Resi", f"{tanpa_resi_cnt} pesanan ({tanpa_pct:.0f}%) belum punya no resi. Update sebelum packing."))

        # Pending scans
        if pending > 0:
            if pending > 20:
                alerts.append(("🔴", "Banyak Scan Pending", f"{pending} resi di-scan tapi tidak ada di data penjualan. Cek ulang data impor."))
            else:
                alerts.append(("⚠️", "Scan Pending Terdeteksi", f"{pending} resi pending — pastikan data penjualan sudah lengkap."))

        # SKU matching
        if sku_match_pct < 70:
            alerts.append(("⚠️", "SKU Matching Rendah", f"Hanya {sku_match_pct:.0f}% produk cocok SKU. Perbaiki mapping SKU di Excel import."))

        # Daily productivity
        if today_scan_cnt > 0:
            insights.append(("📊", f"Aktivitas Hari Ini", f"{today_packed_cnt} resi dipacking hari ini dari {today_scan_cnt} total scan. Tetap konsisten!", "good" if today_packed_cnt > 50 else "normal"))
        else:
            if total_orders_cnt > 0:
                insights.append(("⏰", "Belum Ada Scan Hari Ini", "Operator belum mulai packing hari ini. Pastikan tim mulai bekerja.", "warn"))

        # ── Instant / Prioritas ──
        if instant_total > 0:
            instant_unpacked_pct = (instant_waiting / instant_total * 100) if instant_total > 0 else 0
            if instant_waiting > 0:
                alerts.insert(0, ("🚀", "PRIORITAS! Pesanan Instant Menunggu", 
                    f"{instant_waiting} dari {instant_total} pesanan instant/same-day BELUM dipacking! Dahulukan sebelum reguler."))
                insights.append(("🚀", "Pesanan Instant Perlu Prioritas", 
                    f"{instant_waiting} pesanan instant ({instant_unpacked_pct:.0f}%) masih menunggu — SLA pengiriman lebih ketat.", "warn"))
            else:
                instant_done_pct = (instant_done / instant_total * 100) if instant_total > 0 else 0
                insights.append(("✅", "Semua Instant Terpacking", 
                    f"{instant_done}/{instant_total} pesanan instant sudah selesai dipacking. Good job!", "good"))

    # ═══════════════════════════════════════════
    # 📋 RECOMMENDATIONS
    # ═══════════════════════════════════════════
    if instant_waiting > 0:
        recommendations.insert(0, ("🚀", "DAHULUKAN INSTANT!", 
            f"🚨 {instant_waiting} pesanan instant/same-day belum dipacking. SLA ketat — kerjakan SEKARANG sebelum reguler!"))
    if tanpa_resi_cnt > 0:
        recommendations.append(("📋", "Update No Resi", f"Prioritaskan update {tanpa_resi_cnt} pesanan tanpa resi di menu Input Resi & Pesanan."))
    if pending > 0:
        recommendations.append(("🔍", "Verifikasi Pending", f"Cek {pending} scan pending — pastikan data penjualan sesuai dengan resi fisik."))
    if handover_ready > 0:
        recommendations.append(("📤", "Siapkan Handover", f"{handover_ready} resi siap handover. Export laporan handover untuk kurir."))
    if cancel > 10:
        recommendations.append(("🛑", "Evaluasi Cancel", f"Cancel rate tinggi ({cancel} resi). Review proses quality control dan stok barang."))
    if packed > 0 and with_resi_cnt > 0 and (with_resi_cnt - packed) > 0:
        recommendations.append(("🎯", "Target Packing", f"Selesaikan {with_resi_cnt - packed} resi tersisa untuk capai 100% packing rate."))
    if sku_match_pct < 85:
        recommendations.append(("🏷️", "Perbaiki SKU", f"Tingkatkan SKU matching ({sku_match_pct:.0f}%) — update file Excel dengan kode SKU yang benar."))

    # ═══════════════════════════════════════════
    # 🎨 RENDER DASHBOARD
    # ═══════════════════════════════════════════

    # ── Health Score ──
    if total_orders_cnt > 0:
        # Bonus/penalty untuk instant: +5 kalau semua instant sudah packed, -10 kalau masih banyak nunggu
        instant_bonus = 5 if (instant_total > 0 and instant_waiting == 0) else (-10 if instant_waiting > 5 else 0)
        health_score = min(100, max(0, int(
            (packed / max(total_orders_cnt, 1) * 40) +
            (sku_match_pct * 0.3) +
            (max(0, 100 - tanpa_resi_cnt / max(total_orders_cnt, 1) * 100) * 0.2) +
            (max(0, 100 - cancel / max(total_orders_cnt, 1) * 100) * 0.1) +
            instant_bonus
        )))
    else:
        health_score = 0

    if health_score >= 80:
        health_color = "#30D158"
        health_emoji = "💚"
        health_label = "Sehat"
    elif health_score >= 50:
        health_color = "#FF9F0A"
        health_emoji = "💛"
        health_label = "Perlu Perhatian"
    else:
        health_color = "#FF453A"
        health_emoji = "❤️"
        health_label = "Kritis"

    # Health Score Card
    st.markdown(f"""
    <div style="background: {health_color}22; border: 2px solid {health_color}; border-radius: 16px; padding: 20px; margin-bottom: 20px; text-align: center;">
        <h2 style="margin: 0; color: {health_color};">{health_emoji} Skor Kesehatan Operasional: {health_score}/100</h2>
        <p style="margin: 5px 0 0 0; color: #AEAEB2; font-size: 14px;">Status: <strong style="color: {health_color};">{health_label}</strong> — diperbarui {datetime.now().strftime('%H:%M')}</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Pipeline Flow ──
    st.markdown("### 🔄 Pipeline Operasional")
    col_p1, col_p2, col_p3, col_p4, col_p5, col_p6 = st.columns(6)
    with col_p1:
        st.metric("📥 Pesanan", total_orders_cnt, help="Total pesanan masuk")
    with col_p2:
        st.metric("🏷️ Ada Resi", with_resi_cnt, f"{tanpa_resi_cnt} tanpa", help="Pesanan yang sudah punya no resi")
    with col_p3:
        st.metric("✅ Packed", packed, f"{'+'+str(instant) if instant else ''} instant" if instant else "", help="Resi sudah dipacking")
    with col_p4:
        st.metric("⏳ Pending", pending, help="Scan tidak dikenal")
    with col_p5:
        st.metric("❌ Cancel", cancel, help="Pesanan dibatalkan")
    with col_p6:
        st.metric("📤 Siap Handover", handover_ready, help="Siap diserahkan ke kurir")

    # Progress bar untuk packing progress
    if with_resi_cnt > 0:
        progress_pct = min(1.0, packed / with_resi_cnt)
        st.progress(progress_pct, text=f"Progress Packing: {packed}/{with_resi_cnt} resi ({progress_pct*100:.0f}%)")

    # ── Instant Priority Callout ──
    if instant_waiting > 0:
        instant_pct = (instant_waiting / instant_total * 100) if instant_total > 0 else 0
        st.markdown(f"""
        <div style="background: #FF453A22; border: 2px solid #FF453A; border-radius: 12px; padding: 14px; margin: 12px 0;">
            <strong style="color: #FF453A; font-size: 16px;">🚀 INSTANT PRIORITY!</strong><br>
            <span style="color: #FF9F0A;">{instant_waiting} dari {instant_total} pesanan <strong>instant/same-day</strong> ({instant_pct:.0f}%) belum dipacking — 
            <u>dahulukan sebelum reguler!</u></span> &nbsp;
            <span style="color: #30D158;">✅ {instant_done} sudah selesai.</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Alerts Section ──
    if alerts:
        st.markdown("### 🚨 Alert & Peringatan")
        for icon, title, desc in alerts:
            bg = "#FF453A22" if "🔴" in icon else "#FF9F0A22"
            border = "#FF453A" if "🔴" in icon else "#FF9F0A"
            st.markdown(f"""
            <div style="background: {bg}; border-left: 4px solid {border}; border-radius: 8px; padding: 12px; margin-bottom: 8px;">
                <strong>{icon} {title}</strong><br>
                <small style="color: #AEAEB2;">{desc}</small>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.success("✅ Tidak ada alert — semua berjalan normal!")

    # ── AI Insights ──
    st.markdown("---")
    st.markdown("### 🧠 Insight AI")
    col_i1, col_i2 = st.columns(2)
    for i, (icon, title, desc, level) in enumerate(insights):
        target = col_i1 if i % 2 == 0 else col_i2
        with target:
            color = {"good": "#30D158", "normal": "#0A84FF", "warn": "#FF9F0A", "critical": "#FF453A"}.get(level, "#0A84FF")
            st.markdown(f"""
            <div style="background: {color}15; border: 1px solid {color}44; border-radius: 12px; padding: 14px; margin-bottom: 8px;">
                <strong style="color: {color};">{icon} {title}</strong><br>
                <small style="color: #AEAEB2;">{desc}</small>
            </div>
            """, unsafe_allow_html=True)

    # ── Recommendations ──
    if recommendations:
        st.markdown("---")
        st.markdown("### 📋 Rekomendasi AI")
        for icon, title, desc in recommendations:
            st.markdown(f"""
            <div style="background: #0A84FF15; border: 1px solid #0A84FF44; border-radius: 12px; padding: 12px; margin-bottom: 6px; display: flex; align-items: flex-start; gap: 10px;">
                <span style="font-size: 20px;">{icon}</span>
                <div>
                    <strong>{title}</strong><br>
                    <small style="color: #AEAEB2;">{desc}</small>
                </div>
            </div>
            """, unsafe_allow_html=True)

    # ── Performance Tables ──
    st.markdown("---")
    col_t1, col_t2 = st.columns(2)

    with col_t1:
        st.markdown("#### 🏪 Performa per Toko")
        if toko_perf:
            df_toko = pd.DataFrame([dict(r) for r in toko_perf])
            df_toko = df_toko.rename(columns={
                "nama_toko": "Toko", "total_orders": "Pesanan",
                "packed": "Packed", "packed_revenue": "Revenue"
            })
            df_toko["% Packed"] = df_toko.apply(
                lambda r: f"{r['Packed']/r['Pesanan']*100:.0f}%" if r["Pesanan"] > 0 else "0%", axis=1
            )
            df_toko["Revenue"] = df_toko["Revenue"].apply(lambda x: f"Rp {x:,.0f}" if x else "Rp 0")
            st.dataframe(df_toko[["Toko", "Pesanan", "Packed", "% Packed", "Revenue"]], width="stretch", height=250, hide_index=True)
        else:
            st.info("Belum ada data toko.")

    with col_t2:
        st.markdown("#### 🚚 Performa per Ekspedisi")
        if ekspedisi_perf:
            df_eks = pd.DataFrame([dict(r) for r in ekspedisi_perf])
            df_eks = df_eks.rename(columns={
                "ekspedisi": "Ekspedisi", "total": "Total Scan",
                "packed": "Packed", "pending": "Pending", "cancel": "Cancel"
            })
            st.dataframe(df_eks[["Ekspedisi", "Total Scan", "Packed", "Pending", "Cancel"]], width="stretch", height=250, hide_index=True)
        else:
            st.info("Belum ada data ekspedisi.")

    # ── Marketplace Breakdown ──
    if mp_stats:
        st.markdown("---")
        st.markdown("#### 🛒 Breakdown per Marketplace")
        df_mp = pd.DataFrame([dict(r) for r in mp_stats])
        df_mp = df_mp.rename(columns={
            "marketplace": "Marketplace", "total_orders": "Pesanan",
            "with_resi": "Punya Resi", "revenue": "Revenue"
        })
        df_mp["Revenue"] = df_mp["Revenue"].apply(lambda x: f"Rp {x:,.0f}" if x else "Rp 0")
        col_mp1, col_mp2, col_mp3 = st.columns(3)
        for i, (_, row) in enumerate(df_mp.iterrows()):
            target = [col_mp1, col_mp2, col_mp3][i % 3]
            with target:
                resi_pct = f"{(row['Punya Resi']/row['Pesanan']*100):.0f}%" if row["Pesanan"] > 0 else "0%"
                st.metric(f"{row['Marketplace']}", f"{row['Pesanan']} orders", f"📦 {row['Punya Resi']} resi ({resi_pct}) | {row['Revenue']}")

    # ── Refresh & Timestamp ──
    st.markdown("---")

    # ═══════════════════════════════════════════
    # 🔊 VOICE ALERT SYSTEM (Text-to-Speech)
    # ═══════════════════════════════════════════
    st.markdown("### 🔊 Voice Alert (Text-to-Speech)")

    # Init session state
    if "voice_enabled" not in st.session_state:
        st.session_state.voice_enabled = False
    if "voice_interval" not in st.session_state:
        st.session_state.voice_interval = 60
    if "voice_snooze_until" not in st.session_state:
        st.session_state.voice_snooze_until = None

    col_v1, col_v2, col_v3, col_v4 = st.columns([1, 1, 1, 1])
    with col_v1:
        voice_enabled = st.toggle("🔊 Aktifkan Suara", value=st.session_state.voice_enabled, key="voice_toggle",
                                   help="AI akan bersuara melalui speaker saat ada alert penting")
    with col_v2:
        voice_interval = st.slider("⏱ Interval Cek (detik)", 15, 300, st.session_state.voice_interval, 15, key="voice_interval_slider",
                                    help="Seberapa sering AI mengecek dan bersuara")
    with col_v3:
        snooze_minutes = st.number_input("😴 Snooze (menit)", 1, 60, 5, key="voice_snooze_minutes",
                                          help="Berapa lama menunda suara alert")
    with col_v4:
        st.write("")
        snooze_clicked = st.button("😴 Snooze Sekarang", width="stretch", key="voice_snooze_btn",
                                    help="Tunda semua suara alert untuk sementara")

    if snooze_clicked:
        st.session_state.voice_snooze_until = datetime.now().timestamp() + (snooze_minutes * 60)
        st.success(f"🔇 Alert suara ditunda selama {snooze_minutes} menit.")
        st.rerun()

    # Test suara button
    test_col1, test_col2 = st.columns([1, 3])
    with test_col1:
        test_clicked = st.button("🔊 Test Suara", width="stretch", key="voice_test_btn",
                                  help="Coba putar suara test")
    with test_col2:
        st.caption("💡 Pastikan speaker menyala & volume cukup. Chrome/Edge disarankan. Cek icon 🔊 di tab browser tidak di-mute.")

    if test_clicked:
        import streamlit.components.v1 as components
        components.html("""
        <html><body style="margin:0;padding:0;">
        <script>
        function speakMsg(msg) {
            var u = new SpeechSynthesisUtterance(msg);
            u.lang = 'id-ID'; u.rate = 1.0; u.pitch = 1.1; u.volume = 1.0;
            // Pilih suara Indonesia terbaik (perempuan, natural)
            var voices = speechSynthesis.getVoices();
            if (voices.length === 0) {
                // Voices belum load — tunggu dan retry
                speechSynthesis.onvoiceschanged = function() {
                    speechSynthesis.onvoiceschanged = null;
                    speakMsg(msg);
                };
                return;
            }
            var idVoices = voices.filter(function(v) { return v.lang.startsWith('id'); });
            if (idVoices.length > 0) {
                var best = idVoices.find(function(v) {
                    var n = v.name.toLowerCase();
                    return n.includes('female') || n.includes('wanita') || n.includes('gadis');
                });
                u.voice = best || idVoices[0];
            }
            speechSynthesis.cancel();
            speechSynthesis.speak(u);
            document.body.innerHTML = '<div style="color:green;font-size:14px;padding:6px;font-family:sans-serif;">✅ Suara test diputar! Jika tidak terdengar, cek volume speaker & icon mute di tab browser.</div>';
        }
        try { speakMsg("Halo! iScan Pro A I Supervisor siap membantu. Sistem berjalan normal."); }
        catch(e) { document.body.innerHTML = '<div style="color:red;font-size:14px;padding:6px;font-family:sans-serif;">❌ Gagal: '+e.message+'</div>'; }
        </script>
        </body></html>
        """, height=50)
        st.success("🔊 Memutar suara test...")

    st.session_state.voice_enabled = voice_enabled
    st.session_state.voice_interval = voice_interval

    # Check snooze status
    snooze_active = False
    if st.session_state.voice_snooze_until:
        if datetime.now().timestamp() < st.session_state.voice_snooze_until:
            remaining = int(st.session_state.voice_snooze_until - datetime.now().timestamp())
            snooze_active = True
            st.info(f"🔇 Snooze aktif — suara dinonaktifkan selama {remaining // 60}m {remaining % 60}d lagi.")
        else:
            st.session_state.voice_snooze_until = None

    # ── Build voice message ──
    voice_msg = ""
    if instant_waiting > 0:
        voice_msg = (f"Perhatian! {instant_waiting} pesanan instant atau same-day belum dipacking. "
                     f"Dahulukan segera sebelum reguler. ")
    elif alerts:
        first_alert = alerts[0]
        voice_msg = f"{first_alert[1]}. {first_alert[2].split(chr(8212))[0].strip().rstrip('.')}. "  # chr(8212) = —
        if recommendations:
            voice_msg += f"Rekomendasi: {recommendations[0][1]}."
    elif total_orders_cnt == 0:
        voice_msg = "Belum ada data pesanan. Silakan import data terlebih dahulu."

    # ── Inject TTS via iframe (harus pake components.html biar script execute) ──
    if voice_enabled and not snooze_active and voice_msg:
        ss_key = "last_voice_msg_hash"
        msg_hash = hash(voice_msg)
        last_hash = st.session_state.get(ss_key, 0)

        if msg_hash != last_hash:
            st.session_state[ss_key] = msg_hash
            escaped = voice_msg.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'")
            import streamlit.components.v1 as components
            components.html(f"""
            <html><body style="margin:0;padding:0;">
            <script>
            function speakMsg(msg) {{
                var u = new SpeechSynthesisUtterance(msg);
                u.lang = 'id-ID'; u.rate = 1.0; u.pitch = 1.1; u.volume = 1.0;
                var voices = speechSynthesis.getVoices();
                if (voices.length === 0) {{
                    speechSynthesis.onvoiceschanged = function() {{
                        speechSynthesis.onvoiceschanged = null;
                        speakMsg(msg);
                    }};
                    return;
                }}
                var idVoices = voices.filter(function(v) {{ return v.lang.startsWith('id'); }});
                if (idVoices.length > 0) {{
                    var best = idVoices.find(function(v) {{
                        var n = v.name.toLowerCase();
                        return n.includes('female') || n.includes('wanita') || n.includes('gadis');
                    }});
                    u.voice = best || idVoices[0];
                }}
                speechSynthesis.cancel();
                speechSynthesis.speak(u);
                document.body.innerHTML = '<div style="color:green;font-size:12px;padding:4px;">🔊 Suara diputar</div>';
            }}
            try {{ speakMsg('{escaped}'); }}
            catch(e) {{ document.body.innerHTML = '<div style="color:red;font-size:12px;padding:4px;">❌ '+e.message+'</div>'; }}
            </script>
            </body></html>
            """, height=30)
            st.caption(f"🔊 Voice diputar | _{voice_msg[:80]}..._")
        else:
            st.caption(f"🔊 Alert sudah diucapkan — klik 'Analisa Ulang' untuk refresh.")

    elif voice_enabled and snooze_active:
        st.caption("🔇 Suara ditunda (snooze).")
    elif voice_enabled and not voice_msg:
        st.caption("✅ Tidak ada alert — semua aman.")

    # ═══════════════════════════════════════════
    # 🔄 AUTO-REFRESH (via JavaScript timer)
    # ═══════════════════════════════════════════
    if voice_enabled and not snooze_active:
        # Inject auto-refresh timer — reload halaman setiap voice_interval detik
        import streamlit.components.v1 as components
        components.html(f"""
        <html><body style="margin:0;padding:0;">
        <script>
        // Reset voice hash di sessionStorage biar alert baru bisa diputar
        var refreshKey = 'ai_auto_refresh_active';
        if (!sessionStorage.getItem(refreshKey)) {{
            sessionStorage.setItem(refreshKey, '1');
            // Timer auto-refresh
            setInterval(function() {{
                // Clear hash biar suara diputar ulang kalau ada alert baru
                sessionStorage.removeItem('ai_voice_hash');
                window.parent.location.reload();
            }}, {voice_interval * 1000});
        }}
        </script>
        </body></html>
        """, height=0)
        st.caption(f"🔄 Auto-refresh aktif — halaman refresh setiap {voice_interval} detik.")

    # ── Manual Refresh ──
    st.markdown("---")
    col_r1, col_r2 = st.columns([1, 3])
    with col_r1:
        if st.button("🔄 Analisa Ulang", width="stretch", type="primary"):
            # Clear voice hash di session_state biar suara bisa diputar ulang
            st.session_state.pop("last_voice_msg_hash", None)
            st.rerun()
    with col_r2:
        st.caption(f"🤖 AI Supervisor terakhir diperbarui: {datetime.now().strftime('%d %B %Y, %H:%M:%S')} | Data real-time dari database operasional.")


def _render_handover_tab(db, tipe_kiriman: str):
    """Render satu tab Handover (REGULER atau INSTANT)."""
    tipe_label = "🚀 Instant" if tipe_kiriman == "INSTANT" else "📦 Reguler"

    # Filter Kategori
    kat_filter = st.selectbox(
        "Filter Kategori",
        ["Semua", "REGULER", "BESAR"],
        key=f"handover_kat_{tipe_kiriman}",
    )

    kat_where = f" AND s.tipe_kiriman = '{tipe_kiriman}'"
    if kat_filter != "Semua":
        kat_where += f" AND s.kategori = '{kat_filter}'"

    kurir_list = db.fetch_all(
        f"SELECT DISTINCT p.kurir FROM scan_aktif s "
        "JOIN penjualan p ON s.resi = p.no_resi "
        f"WHERE s.status = 'PACKED' AND p.kurir != '' {kat_where} "
        "ORDER BY p.kurir"
    )

    if not kurir_list:
        st.info(f"📭 Belum ada resi {tipe_label}. Scan resi di SCAN Operasional.")
        return

    kurir_options = ["Semua Kurir"] + [k["kurir"] for k in kurir_list]
    selected_kurir = st.selectbox("Pilih Kurir", kurir_options, key=f"handover_kurir_{tipe_kiriman}")

    kurir_where = "" if selected_kurir == "Semua Kurir" else f" AND p.kurir = '{selected_kurir}'"

    items = db.fetch_all(
        f"SELECT s.id as scan_id, s.waktu, s.tanggal, s.resi, s.kategori, s.keterangan_barang, s.tipe_kiriman, "
        "p.marketplace, p.no_pesanan, "
        "GROUP_CONCAT(p.nama_produk, ', ') as nama_produk, "
        "p.kurir, p.nama_toko, GROUP_CONCAT(p.sku_terdeteksi, ', ') as sku_terdeteksi "
        "FROM scan_aktif s JOIN penjualan p ON s.resi = p.no_resi "
        f"WHERE s.status = 'PACKED' {kat_where} {kurir_where} "
        "GROUP BY s.resi ORDER BY p.kurir, s.id"
    )

    if not items:
        st.info(f"Tidak ada resi {tipe_label} untuk kurir '{selected_kurir}'.")
        return

    df_items = pd.DataFrame([dict(r) for r in items])
    df_items["No"] = range(1, len(items) + 1)
    df_items = df_items.rename(columns={
        "waktu": "Waktu", "tanggal": "Tanggal", "resi": "No Resi",
        "marketplace": "MP", "no_pesanan": "No Pesanan",
        "nama_produk": "Produk", "kurir": "Kurir",
        "nama_toko": "Toko", "sku_terdeteksi": "SKU",
        "kategori": "Kategori", "keterangan_barang": "Keterangan",
        "tipe_kiriman": "Tipe",
    })

    display_cols = ["No", "Waktu", "No Resi", "Kategori", "Keterangan", "MP", "No Pesanan", "Produk", "SKU", "Kurir", "Toko"]
    available_cols = [c for c in display_cols if c in df_items.columns]
    st.dataframe(df_items[available_cols], width="stretch", height=400, hide_index=True)

    st.markdown(f"📋 **{len(items)} resi** {tipe_label} siap diserahkan ke **{selected_kurir}**")

    # ── Konfirmasi Instant: sudah diambil kurir ──
    if tipe_kiriman == "INSTANT":
        st.markdown("---")
        st.subheader("✅ Konfirmasi Pengambilan Kurir")
        st.caption("Setelah kurir mengambil paket Instant, konfirmasi di sini. Resi akan dihapus dari daftar.")

        konfirm_col1, konfirm_col2 = st.columns([3, 1])
        with konfirm_col1:
            konfirm_resi = st.text_input(
                "No Resi yang sudah diambil kurir",
                placeholder="Ketik no resi...",
                key=f"konfirm_instant_{tipe_kiriman}",
                label_visibility="collapsed",
            )
        with konfirm_col2:
            if st.button("✅ Konfirmasi Diambil", width="stretch", type="primary", key=f"konfirm_btn_{tipe_kiriman}"):
                if konfirm_resi.strip():
                    c_clean = Validator.sanitize_resi(konfirm_resi.strip())
                    if c_clean:
                        # Hapus dari scan_aktif (sudah diambil kurir)
                        db.execute("DELETE FROM scan_aktif WHERE resi = ? AND tipe_kiriman = 'INSTANT'", (c_clean,))
                        # Update penjualan: tetap PACKED (sudah terkirim)
                        db.execute("UPDATE penjualan SET status_pesanan = 'TERKIRIM' WHERE no_resi = ?", (c_clean,))
                        st.success(f"✅ `{c_clean}` dikonfirmasi — sudah diambil kurir & status penjualan: TERKIRIM.")
                        st.rerun()
                else:
                    st.warning("Masukkan No Resi.")

    # ── Summary per kurir ──
    if selected_kurir == "Semua Kurir":
        st.markdown("---")
        st.subheader("📊 Ringkasan per Kurir")
        summary = db.fetch_all(
            f"SELECT p.kurir, COUNT(DISTINCT s.resi) as jml FROM scan_aktif s "
            "JOIN penjualan p ON s.resi = p.no_resi "
            f"WHERE s.status = 'PACKED' {kat_where} GROUP BY p.kurir ORDER BY jml DESC"
        )
        if summary:
            df_sum = pd.DataFrame([dict(r) for r in summary])
            df_sum = df_sum.rename(columns={"kurir": "Kurir", "jml": "Jumlah Resi"})
            st.dataframe(df_sum, width="stretch", hide_index=True)

    # ── Export ──
    st.markdown("---")
    kurir_label = selected_kurir.replace(" ", "_") if selected_kurir != "Semua Kurir" else "Semua"
    now_exp = datetime.now()
    tipe_file = "Instant" if tipe_kiriman == "INSTANT" else "Reguler"
    filename = f"Handover_{tipe_file}_{kurir_label}_{now_exp.strftime('%d-%m-%Y_%H%M%S')}.xlsx"
    filepath = os.path.join(Config.HANDOVER_FOLDER, filename)
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df_items.to_excel(writer, index=False, sheet_name="Handover")
    with open(filepath, "rb") as fp:
        st.download_button(
            "📥 Download Handover (Excel)",
            fp, file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_{tipe_kiriman}",
        )


def render_reports():
    """Render reports page (Handover & Sales)."""
    db = st.session_state.db
    cache = st.session_state.cache

    st.subheader("📊 Reports")

    tab1, tab2 = st.tabs(["📋 Handover Report", "💰 Sales Report"])

    with tab1:
        st.markdown("### Handover Report per Ekspedisi")
        st.caption("Generate laporan serah terima paket ke ekspedisi (status PACKED).")

        expeditions = db.fetch_all("SELECT DISTINCT ekspedisi FROM scan_aktif WHERE status = 'PACKED' AND ekspedisi != 'CANCEL' ORDER BY ekspedisi")
        exp_list = ["Semua Ekspedisi"] + [e["ekspedisi"] for e in expeditions if e["ekspedisi"]]

        selected_exp = st.selectbox("Pilih Ekspedisi", exp_list, key="handover_exp")

        if st.button("📋 Generate Handover Report", type="primary"):
            filter_exp = None if selected_exp == "Semua Ekspedisi" else selected_exp
            filepath = export_handover_report(db, Config.HANDOVER_FOLDER, filter_exp)
            if filepath:
                with open(filepath, "rb") as fp:
                    st.download_button(
                        "⬇️ Download Handover Report",
                        fp,
                        file_name=os.path.basename(filepath),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                st.success(f"✅ Report tersimpan: {os.path.basename(filepath)}")
            else:
                st.warning("Tidak ada data PACKED untuk diexport.")

    with tab2:
        st.markdown("### Sales Report")
        st.caption("Generate laporan penjualan/pengiriman.")

        # Summary per expedition — mencakup semua status
        rows = db.fetch_all(
            "SELECT ekspedisi, status, COUNT(*) as cnt FROM scan_aktif GROUP BY ekspedisi, status ORDER BY ekspedisi"
        )

        if rows:
            summary = {}
            all_statuses = ["PACKED", "PENDING", "CANCEL", "KIRIM", "RETUR"]
            for r in rows:
                if r["ekspedisi"] not in summary:
                    summary[r["ekspedisi"]] = {s: 0 for s in all_statuses}
                if r["status"] in summary[r["ekspedisi"]]:
                    summary[r["ekspedisi"]][r["status"]] = r["cnt"]

            df_summary = pd.DataFrame([
                {"Ekspedisi": k, **v, "Total": sum(v.values())}
                for k, v in summary.items()
            ])
            df_summary = df_summary.sort_values("Total", ascending=False)

            st.dataframe(df_summary, width="stretch", hide_index=True)

            # Export
            if st.button("📊 Export Sales Report", type="primary"):
                now = datetime.now()
                filename = f"Sales_Report_{now.strftime('%d-%m-%Y_%H%M%S')}.xlsx"
                filepath = os.path.join(Config.SALES_FOLDER, filename)
                with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                    df_summary.to_excel(writer, index=False, sheet_name="Summary")
                with open(filepath, "rb") as fp:
                    st.download_button(
                        "⬇️ Download Sales Report",
                        fp,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                st.success(f"✅ Report tersimpan: {filename}")
        else:
            st.info("Belum ada data scan.")


# ==================== SIDEBAR NAVIGATION ====================
# Sub-menu definitions per main menu
OPERATIONAL_SUB_MENUS = {
    "📊 Dashboard": "Dashboard",
    "📷 SCAN Operasional": "Scan_Operasional",
    "📦 Input Resi & Pesanan": "Sales_Input",
    "🤖 AI Supervisor": "AI_Supervisor",
    "📋 Handover": "Handover",
    "🚚 Ekspedisi": "Ekspedisi",
    "🏪 Toko": "Toko",
    "� Daftar Barang Besar": "Barang_Besar",
    "�📈 Reports": "Reports",
}

SALES_SUB_MENUS = {
    "📊 Dashboard Penjualan": "Sales_Dashboard",
    "📋 Riwayat Penjualan": "Sales_History",
    "📁 Arsip Penjualan": "Sales_Archive",
}

PURCHASE_SUB_MENUS = {
    "📊 Dashboard Pembelian": "Purchase_Dashboard",
    "🏷️ Manajemen SKU": "Purchase_SKU",
    "🛒 Input Pembelian": "Purchase_Input",
    "📋 Riwayat Pembelian": "Purchase_History",
    "💳 Finance (Konfirmasi)": "Purchase_Finance",
    "📁 Arsip Pembelian": "Purchase_Archive",
}


def render_sidebar():
    """Render the sidebar navigation with main-menu → sub-menu hierarchy."""
    with st.sidebar:
        # Logo
        st.markdown(
            """
            <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:20px;">
                <span style="font-size:28px;font-weight:800;color:#FFFFFF;">iScan</span>
                <span style="font-size:20px;font-weight:700;color:#0A84FF;">Pro</span>
                <span style="font-size:12px;color:#AEAEB2;">By MMA</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── Main Menu ──
        main_menus = ["📦 Operasional", "💰 Penjualan", "🛒 Pembelian"]
        main_menu_map = {
            "📦 Operasional": "Operasional",
            "💰 Penjualan": "Penjualan",
            "🛒 Pembelian": "Pembelian",
        }

        # Determine current main menu index
        current_main = st.session_state.get("main_menu", "Operasional")
        main_labels = list(main_menu_map.keys())
        main_index = list(main_menu_map.values()).index(current_main) if current_main in main_menu_map.values() else 0

        selected_main_label = st.selectbox(
            "Menu Utama",
            main_labels,
            index=main_index,
            label_visibility="collapsed",
        )
        st.session_state.main_menu = main_menu_map[selected_main_label]

        st.markdown("---")

        # ── Sub Menu (depends on main menu) ──
        main_menu = st.session_state.main_menu

        if main_menu == "Operasional":
            sub_menus = OPERATIONAL_SUB_MENUS
            default_page = "Dashboard"
        elif main_menu == "Penjualan":
            sub_menus = SALES_SUB_MENUS
            default_page = "Sales_Dashboard"
        else:  # Pembelian
            sub_menus = PURCHASE_SUB_MENUS
            default_page = "Purchase_Dashboard"

        # Auto-reset page when switching main menu
        current_page = st.session_state.get("page", default_page)
        if current_page not in sub_menus.values():
            current_page = default_page

        sub_index = list(sub_menus.values()).index(current_page) if current_page in sub_menus.values() else 0

        selected_sub = st.radio(
            "Sub Menu Operasional" if main_menu == "Operasional" else "Sub Menu",
            list(sub_menus.keys()),
            index=sub_index,
            label_visibility="collapsed",
        )
        st.session_state.page = sub_menus[selected_sub]

        st.markdown("---")

        # ── Stats summary (only for Operasional) ──
        if main_menu == "Operasional":
            stats = get_stats(st.session_state.db)
            st.caption(f"📦 Pesanan dgn Resi: {stats.get('TOTAL_SALES', 0):,}")
            st.caption(f"✅ Packed: {stats.get('PACKED', 0):,} | ⏳ Pending: {stats.get('PENDING', 0):,} | ❌ Cancel: {stats.get('CANCEL', 0):,}")
            st.caption(f"� Instant: {stats.get('INSTANT', 0):,} | 📦 Reguler: {stats.get('PACKED_REGULER', 0):,} | Besar: {stats.get('PACKED_BESAR', 0):,}")

        st.markdown("---")
        st.caption(f"v{APP_VERSION}")


# ==================== MAIN APP ====================
def main():
    """Main Streamlit application."""
    init_session()
    render_sidebar()

    page = st.session_state.page

    # Page title
    if page == "Dashboard":
        st.title("📊 Dashboard Operasional")

        col_title, col_refresh = st.columns([5, 1])
        with col_title:
            st.caption(f"Selamat datang di iScan Pro — {datetime.now().strftime('%d %B %Y, %H:%M')}")
        with col_refresh:
            if st.button("🔄 Refresh", width="stretch", key="dashboard_refresh", help="Klik untuk memperbarui data"):
                st.rerun()

        db = st.session_state.db

        # Stats — selaras dengan Scan Operasional
        stats = get_stats(db)
        render_stats_cards(stats)

        # ── Info orders tanpa resi ──
        orders_tanpa_resi = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan WHERE no_resi = '' OR no_resi IS NULL")
        total_orders_all = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan")
        jika_ada = orders_tanpa_resi["cnt"] if orders_tanpa_resi else 0
        if jika_ada > 0:
            st.warning(
                f"⚠️ **{jika_ada}** dari **{total_orders_all['cnt']}** pesanan belum memiliki No Resi. "
                f"Update di menu **📦 Input Resi & Pesanan** agar bisa di-scan."
            )

        # ── Success Rate ──
        st.markdown("---")
        total_sales = stats.get("TOTAL_SALES", 0)
        packed = stats.get("PACKED", 0)
        cancel = stats.get("CANCEL", 0)
        resolved = packed + cancel  # resi yang sudah ditangani (packed atau cancel)
        success_rate = (resolved / total_sales * 100) if total_sales > 0 else 0

        col_sr1, col_sr2, col_sr3 = st.columns([1, 2, 1])
        with col_sr2:
            # Progress bar
            st.progress(min(success_rate / 100, 1.0), text=f"🎯 Success Rate: {success_rate:.1f}%")

            # Detail metrics
            sr_col1, sr_col2, sr_col3, sr_col4 = st.columns(4)
            with sr_col1:
                st.metric("📦 Pesanan dgn Resi", f"{total_sales:,}")
            with sr_col2:
                st.metric("✅ Packed", f"{packed:,}")
            with sr_col3:
                st.metric("❌ Cancel", f"{cancel:,}")
            with sr_col4:
                belum = stats.get("BELUM_SCAN", 0)
                st.metric("📋 Belum Scan", f"{belum:,}")

            # Status indicator
            if success_rate >= 100:
                st.success(f"🎉 **100% Sukses!** Semua {total_sales:,} pesanan sudah ditangani (Packed + Cancel).")
            elif success_rate >= 80:
                st.info(f"📈 Progress baik: {resolved:,} dari {total_sales:,} resi sudah ditangani ({success_rate:.1f}%).")
            elif success_rate > 0:
                st.warning(f"⏳ Baru {resolved:,} dari {total_sales:,} resi yang ditangani ({success_rate:.1f}%).")
            else:
                st.info("📭 Belum ada aktivitas scan hari ini. Mulai scan di halaman SCAN Operasional.")

        # ── Kategori Breakdown: Reguler vs Barang Besar ──
        if packed > 0:
            st.markdown("---")
            st.subheader("📦 Breakdown Kategori Packing")
            packed_reguler = stats.get("PACKED_REGULER", 0)
            packed_besar = stats.get("PACKED_BESAR", 0)

            kat_col1, kat_col2, kat_col3 = st.columns([1, 1, 2])
            with kat_col1:
                st.metric("📦 Reguler", f"{packed_reguler:,}")
            with kat_col2:
                st.metric("📦 Barang Besar", f"{packed_besar:,}")
            with kat_col3:
                if packed_reguler + packed_besar > 0:
                    besar_pct = packed_besar / (packed_reguler + packed_besar) * 100
                    st.caption(f"Barang besar: {besar_pct:.1f}% dari total packing")

        # ── Recent scans preview (dari scan_aktif + penjualan) ──
        st.markdown("---")
        st.subheader("📋 Scan Terbaru (Packing)")
        scans = db.fetch_all(
            "SELECT s.waktu, s.tanggal, s.resi, s.toko, s.status, s.kategori, s.keterangan_barang, "
            "p.marketplace, p.no_pesanan, p.nama_produk, p.kurir "
            "FROM scan_aktif s LEFT JOIN penjualan p ON s.resi = p.no_resi "
            "ORDER BY s.id DESC LIMIT 10"
        )
        if scans:
            df_recent = pd.DataFrame([dict(r) for r in scans])
            df_recent = df_recent.rename(columns={
                "waktu": "Waktu", "tanggal": "Tanggal", "resi": "No Resi",
                "marketplace": "MP", "no_pesanan": "No Pesanan",
                "nama_produk": "Produk", "kurir": "Kurir",
                "toko": "Toko", "status": "Status",
                "kategori": "Kategori", "keterangan_barang": "Keterangan",
            })

            def color_dashboard_status(val):
                if val == "PACKED":
                    return "background-color: #d4edda; color: #155724; font-weight: bold"
                elif val == "PENDING":
                    return "background-color: #fff3cd; color: #856404; font-weight: bold"
                elif val == "CANCEL":
                    return "background-color: #f8d7da; color: #721c24; font-weight: bold"
                return ""

            def color_kategori_dashboard(val):
                if val == "BESAR":
                    return "background-color: #e8d1f5; color: #6a1b9a; font-weight: bold"
                return ""

            display_cols = ["Waktu", "No Resi", "Kategori", "Keterangan", "MP", "No Pesanan", "Produk", "Kurir", "Toko", "Status"]
            available_cols = [c for c in display_cols if c in df_recent.columns]
            styled = df_recent[available_cols].style.map(color_dashboard_status, subset=["Status"]).map(color_kategori_dashboard, subset=["Kategori"])
            st.dataframe(styled, width="stretch", hide_index=True)

            total_scans = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif")
            if total_scans and total_scans["cnt"] > 10:
                st.caption(f"... dan {total_scans['cnt'] - 10} data lainnya. Lihat di halaman SCAN Operasional.")
        else:
            st.info("📭 Belum ada data scan.")

        # Expedition summary chips — dari scan_aktif
        st.markdown("---")
        st.subheader("🚚 Ringkasan per Ekspedisi (Packing)")
        rows = db.fetch_all(
            "SELECT s.ekspedisi, COUNT(*) as cnt FROM scan_aktif s "
            "WHERE s.status IN ('PACKED', 'PENDING') "
            "GROUP BY s.ekspedisi ORDER BY cnt DESC"
        )
        if rows:
            cols = st.columns(min(len(rows), 5))
            for i, r in enumerate(rows):
                with cols[i % 5]:
                    label = r["ekspedisi"] if r["ekspedisi"] and r["ekspedisi"] != "Unknown" else "❓Unknown"
                    st.metric(label, r["cnt"])
        else:
            st.caption("Belum ada data.")

    elif page == "Scan_Operasional":
        st.title("📷 SCAN Operasional — Packing & Verifikasi")
        st.caption("Scan resi fisik untuk verifikasi packing. Cocokkan dengan data pesanan dari Input Resi & Pesanan.")

        db = st.session_state.db
        cache = st.session_state.cache

        # ── Stats operasional ──
        packed = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED'")
        pending_scan = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PENDING'")
        cancel_scan = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'CANCEL'")
        total_resi_unique = db.fetch_one("SELECT COUNT(DISTINCT no_resi) as cnt FROM penjualan WHERE no_resi != ''")
        total_orders_all = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan")
        orders_tanpa_resi = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan WHERE no_resi = '' OR no_resi IS NULL")

        orders_cnt = total_orders_all["cnt"] if total_orders_all else 0
        resi_cnt = total_resi_unique["cnt"] if total_resi_unique else 0
        tanpa_cnt = orders_tanpa_resi["cnt"] if orders_tanpa_resi else 0
        packed_cnt = packed["cnt"] if packed else 0
        cancel_cnt = cancel_scan["cnt"] if cancel_scan else 0
        pending_cnt = pending_scan["cnt"] if pending_scan else 0
        belum_scan = max(0, resi_cnt - packed_cnt - cancel_cnt)

        # Row 1: Total Orders, Total Resi, Packed, Tanpa Resi
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📦 Total Orders", f"{orders_cnt:,}", help="Semua pesanan unik (dengan & tanpa resi)")
        with col2:
            st.metric("🏷️ Total Resi", f"{resi_cnt:,}", help="Unique resi yang harus di-scan")
        with col3:
            st.metric("✅ Packed", f"{packed_cnt:,}")
        with col4:
            st.metric("⚠️ Tanpa Resi", f"{tanpa_cnt:,}", help="Pesanan belum memiliki No Resi")

        # Row 2: Belum Scan, Pending, Cancel, Sisa
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            st.metric("📋 Belum Scan", f"{belum_scan:,}",
                     help=f"Resi yang belum di-scan. Bisa jadi paket dibatalkan sistem.")
        with col6:
            st.metric("⏳ Pending", f"{pending_cnt:,}", help="Resi di-scan tapi tidak ada di data penjualan")
        with col7:
            st.metric("❌ Cancel", f"{cancel_cnt:,}")
        with col8:
            sisa = orders_cnt - packed_cnt - cancel_cnt
            st.metric("🔍 Sisa", f"{max(0, sisa):,}",
                     help="Total pesanan yang belum selesai (termasuk tanpa resi & belum scan)")

        # ── Info bar ──
        if orders_cnt > 0:
            orders_dengan_resi = orders_cnt - tanpa_cnt
            st.info(
                f"📊 **{orders_cnt}** Total Pesanan → "
                f"**{orders_dengan_resi}** punya Resi ({resi_cnt} unique) + "
                f"**{tanpa_cnt}** tanpa Resi | "
                f"**{belum_scan}** resi belum di-scan | "
                f"**{packed_cnt}** packed | **{cancel_cnt}** cancel"
            )

        # ── Daftar Belum Scan (resi ada, belum diproses) ──
        if belum_scan > 0:
            with st.expander(f"📋 {belum_scan} Resi Belum Di-Scan — Kemungkinan dibatalkan sistem? Klik untuk lihat & intervensi", expanded=False):
                st.caption("Pesanan dengan resi yang belum di-scan. Gunakan mode ❌ CANCEL atau upload pembatalan di Input Resi & Pesanan.")
                belum_list = db.fetch_all(
                    "SELECT p.marketplace, p.no_pesanan, p.no_resi, p.nama_produk, p.kurir, p.nama_toko, p.qty, p.total_harga, p.status_pesanan "
                    "FROM penjualan p "
                    "WHERE p.no_resi != '' AND p.no_resi IS NOT NULL "
                    "AND p.no_resi NOT IN (SELECT resi FROM scan_aktif WHERE status IN ('PACKED', 'CANCEL')) "
                    "ORDER BY p.created_at DESC LIMIT 50"
                )
                if belum_list:
                    df_belum = pd.DataFrame([dict(r) for r in belum_list])
                    df_belum = df_belum.rename(columns={
                        "marketplace": "MP", "no_pesanan": "No Pesanan", "no_resi": "No Resi",
                        "nama_produk": "Produk", "kurir": "Kurir", "nama_toko": "Toko",
                        "qty": "Qty", "total_harga": "Total", "status_pesanan": "Status",
                    })
                    df_belum["Total"] = df_belum["Total"].apply(lambda x: f"Rp {x:,.0f}")
                    st.dataframe(df_belum, width="stretch", height=300, hide_index=True)

                    # Quick CANCEL: input resi langsung dari sini
                    st.markdown("---")
                    st.caption("⚡ **Intervensi Cepat**: Ketik No Resi atau No Pesanan untuk langsung CANCEL:")
                    quick_col1, quick_col2 = st.columns([3, 1])
                    with quick_col1:
                        quick_cancel_input = st.text_input(
                            "No Resi / No Pesanan yang dibatalkan",
                            placeholder="Ketik resi atau no pesanan...",
                            key="quick_cancel_input",
                            label_visibility="collapsed",
                        )
                    with quick_col2:
                        if st.button("❌ CANCEL Cepat", width="stretch", type="primary", key="quick_cancel_btn"):
                            if quick_cancel_input.strip():
                                qc = Validator.sanitize_resi(quick_cancel_input.strip())
                                if qc:
                                    # CANCEL: update penjualan + insert scan_aktif
                                    match_c = db.fetch_one(
                                        "SELECT no_resi, no_pesanan, nama_toko FROM penjualan WHERE no_resi = ? OR no_pesanan = ? LIMIT 1",
                                        (qc, qc),
                                    )
                                    qc_toko = (match_c["nama_toko"] or selected_toko) if match_c else selected_toko
                                    real = match_c["no_resi"] if match_c else qc
                                    dup = db.fetch_one("SELECT id FROM scan_aktif WHERE resi = ?", (real,))
                                    if dup:
                                        st.warning(f"Resi `{real}` sudah ada di scan.")
                                    else:
                                        now = datetime.now()
                                        db.execute(
                                            "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, status, kategori, keterangan_barang, tipe_kiriman, marketplace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                            (now.strftime("%H:%M:%S"), now.strftime("%d-%m-%Y"), qc, "CANCEL", qc_toko, "CANCEL", "REGULER", "", "REGULER", ""),
                                        )
                                        db.execute(
                                            "UPDATE penjualan SET status_pesanan = 'CANCEL', qty = 0, total_harga = 0, harga_jual = 0 WHERE no_resi = ? OR no_pesanan = ?",
                                            (qc, qc),
                                        )
                                        st.success(f"❌ `{qc}` berhasil di-CANCEL.")
                                        st.rerun()
                            else:
                                st.warning("Masukkan No Resi atau No Pesanan.")

        # ── Pesanan Tanpa Resi (expandable) ──
        if tanpa_cnt > 0:
            with st.expander(f"⚠️ {tanpa_cnt} Pesanan Belum Memiliki No Resi — Klik untuk lihat", expanded=False):
                st.caption("Update No Resi di halaman Input Resi & Pesanan agar bisa di-scan.")
                tanpa_list = db.fetch_all(
                    "SELECT marketplace, no_pesanan, nama_produk, nama_toko, qty, total_harga, tanggal_pesanan "
                    "FROM penjualan WHERE no_resi = '' OR no_resi IS NULL "
                    "ORDER BY created_at DESC LIMIT 50"
                )
                if tanpa_list:
                    df_tanpa = pd.DataFrame([dict(r) for r in tanpa_list])
                    df_tanpa = df_tanpa.rename(columns={
                        "marketplace": "MP", "no_pesanan": "No Pesanan",
                        "nama_produk": "Produk", "nama_toko": "Toko",
                        "qty": "Qty", "total_harga": "Total",
                        "tanggal_pesanan": "Tgl Pesan",
                    })
                    df_tanpa["Total"] = df_tanpa["Total"].apply(lambda x: f"Rp {x:,.0f}")
                    st.dataframe(df_tanpa, width="stretch", height=300, hide_index=True)

        st.markdown("---")

        # ── Mode ──
        col_m1, col_m2, col_m3 = st.columns([1, 1, 2])
        with col_m1:
            scan_mode = st.radio(
                "Mode Scan",
                ["📦 PACK", "🚀 INSTANT", "❌ CANCEL"],
                horizontal=True,
                key="scan_ops_mode",
                help="PACK = reguler, INSTANT = kiriman prioritas (siap diambil kurir), CANCEL = batalkan"
            )
        with col_m2:
            # Barang Besar toggle — hanya aktif saat PACK/INSTANT mode
            is_besar = st.checkbox(
                "📦 Barang Besar",
                value=False,
                key="scan_ops_besar",
                help="Centang untuk scan barang besar. Data dipisah dari paket reguler.",
                disabled=(scan_mode == "❌ CANCEL"),
            )
        with col_m3:
            # ── Pilih Toko (dari Manajemen Toko) ──
            toko_list = db.fetch_all("SELECT nama FROM toko ORDER BY nama")
            toko_options = [t["nama"] for t in toko_list] if toko_list else ["Mitra Mulia Abadi"]
            # Default: pakai session state, atau toko pertama
            if "selected_toko_scan" not in st.session_state:
                st.session_state.selected_toko_scan = toko_options[0]
            if st.session_state.selected_toko_scan not in toko_options:
                st.session_state.selected_toko_scan = toko_options[0]
            selected_toko = st.selectbox(
                "🏪 Toko",
                toko_options,
                index=toko_options.index(st.session_state.selected_toko_scan),
                key="scan_ops_toko",
                help="Pilih toko dari Manajemen Toko. Toko dari marketplace akan otomatis tersimpan.",
            )
            st.session_state.selected_toko_scan = selected_toko

        # Tentukan kategori & tipe_kiriman
        if scan_mode == "🚀 INSTANT":
            kategori = "BESAR" if is_besar else "REGULER"
            tipe_kiriman = "INSTANT"
        elif scan_mode == "📦 PACK":
            kategori = "BESAR" if is_besar else "REGULER"
            tipe_kiriman = "REGULER"
        else:
            kategori = "REGULER"
            tipe_kiriman = "REGULER"

        # ── Keterangan Barang Besar ──
        keterangan_barang = ""
        if is_besar and scan_mode != "❌ CANCEL":
            st.markdown("---")
            # Ambil daftar barang besar dari database
            daftar_besar = db.fetch_all("SELECT id, nama_barang, keterangan FROM daftar_barang_besar ORDER BY nama_barang")
            besar_options = [""] + [f"{b['nama_barang']}" for b in daftar_besar] + ["➕ Tambah Baru..."]

            kat_col1, kat_col2 = st.columns([2, 2])
            with kat_col1:
                selected_barang = st.selectbox(
                    "📋 Pilih Barang Besar",
                    besar_options,
                    key="scan_ops_pilih_barang",
                    help="Pilih dari daftar barang besar yang sudah terdaftar, atau pilih 'Tambah Baru' untuk input manual."
                )
            with kat_col2:
                if selected_barang == "➕ Tambah Baru...":
                    keterangan_barang = st.text_input(
                        "✏️ Nama Barang Baru",
                        placeholder="Contoh: Bak Cuci Piring, Portable Wastafel...",
                        key="scan_ops_keterangan_free",
                    )
                elif selected_barang:
                    keterangan_barang = selected_barang
                    # Tampilkan keterangan tambahan jika ada
                    matched = [b for b in daftar_besar if b["nama_barang"] == selected_barang]
                    if matched and matched[0]["keterangan"]:
                        st.caption(f"📝 {matched[0]['keterangan']}")

            if not keterangan_barang and selected_barang == "➕ Tambah Baru...":
                st.warning("⚠️ Isi nama barang terlebih dahulu sebelum scan.")

        # ── Scan input ──
        st.markdown("---")
        scan_col1, scan_col2 = st.columns([4, 1])
        with scan_col1:
            if scan_mode == "🚀 INSTANT":
                placeholder_text = "Scan resi kiriman INSTANT/Prioritas..."
            elif scan_mode == "📦 PACK":
                placeholder_text = "Scan resi fisik paket..."
            else:
                placeholder_text = "Scan/ketik resi CANCEL..."
            resi_input = st.text_input(
                "Scan barcode atau ketik nomor resi",
                placeholder=placeholder_text,
                key="scan_ops_resi",
                label_visibility="collapsed",
            )
        with scan_col2:
            if scan_mode == "🚀 INSTANT":
                btn_label = "🚀 Instant"
            elif scan_mode == "📦 PACK":
                btn_label = "📷 Scan"
            else:
                btn_label = "❌ Cancel"
            scan_btn = st.button(btn_label, width="stretch", type="primary", key="scan_ops_btn")

        if resi_input or scan_btn:
            resi_to_scan = resi_input.strip() if resi_input else ""
            if resi_to_scan:
                cleaned = Validator.sanitize_resi(resi_to_scan)
                if not cleaned:
                    st.error(f"Format resi tidak valid: '{resi_to_scan}'")
                else:
                    # Check duplicate — cek by resi langsung DAN by no_pesanan → resi
                    penj_match = None
                    existing_scan = db.fetch_one(
                        "SELECT id, status, waktu, tanggal, toko FROM scan_aktif WHERE resi = ?",
                        (cleaned,),
                    )
                    if not existing_scan:
                        # Cek juga: apakah cleaned adalah no_pesanan yang resi-nya sudah di-scan?
                        penj_match = db.fetch_one(
                            "SELECT no_resi FROM penjualan WHERE no_pesanan = ? LIMIT 1",
                            (cleaned,),
                        )
                        if penj_match and penj_match["no_resi"]:
                            existing_scan = db.fetch_one(
                                "SELECT id, status, waktu, tanggal, toko FROM scan_aktif WHERE resi = ?",
                                (penj_match["no_resi"],),
                            )

                    if existing_scan:
                        status_emoji = {"PACKED": "✅", "PENDING": "⏳", "CANCEL": "❌"}.get(existing_scan["status"], "📋")
                        st.toast("🚫 DOUBLE SCAN!", icon="🚫")
                        linked_resi = penj_match["no_resi"] if penj_match else cleaned
                        st.error(
                            f"🚫 **DOUBLE SCAN DITOLAK!**\n\n"
                            f"`{cleaned}` → Resi `{linked_resi}` sudah di-scan:\n"
                            f"• Status: {status_emoji} **{existing_scan['status']}**\n"
                            f"• Waktu: {existing_scan['waktu']} | Tanggal: {existing_scan['tanggal']}\n"
                            f"• Toko: {existing_scan['toko']}\n\n"
                            f"Gunakan mode ❌ CANCEL jika ingin membatalkan."
                        )
                    else:
                        now = datetime.now()
                        waktu = now.strftime("%H:%M:%S")
                        tanggal = now.strftime("%d-%m-%Y")

                        if scan_mode == "❌ CANCEL":
                            # ── CANCEL mode: cari by resi ATAU no_pesanan ──
                            match_cancel = db.fetch_one(
                                "SELECT no_resi, no_pesanan, nama_toko FROM penjualan WHERE no_resi = ? OR no_pesanan = ? LIMIT 1",
                                (cleaned, cleaned),
                            )
                            real_resi = match_cancel["no_resi"] if match_cancel else cleaned
                            cancel_toko = (match_cancel["nama_toko"] or selected_toko) if match_cancel else selected_toko

                            # Check duplicate on real resi
                            dup = db.fetch_one("SELECT id FROM scan_aktif WHERE resi = ?", (real_resi,))
                            if dup:
                                st.error(f"🚫 Resi `{real_resi}` sudah di-scan sebelumnya.")
                            else:
                                db.execute(
                                    "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, status, kategori, keterangan_barang, tipe_kiriman, marketplace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    (waktu, tanggal, cleaned, "CANCEL", cancel_toko, "CANCEL", "REGULER", "", "REGULER", ""),
                                )
                                db.execute(
                                    "UPDATE penjualan SET status_pesanan = 'CANCEL', qty = 0, total_harga = 0, harga_jual = 0 WHERE no_resi = ? OR no_pesanan = ?",
                                    (cleaned, cleaned),
                                )
                                extra = f" (No Pesanan: {match_cancel['no_pesanan']})" if match_cancel and cleaned != match_cancel["no_resi"] else ""
                                st.error(f"❌ **CANCEL!** `{cleaned}`{extra} — nilai penjualan dikurangi.")
                            st.rerun()

                        # ── PACK mode: cari by no_resi ATAU no_pesanan ──
                        match = db.fetch_one(
                            "SELECT no_resi, no_pesanan, marketplace, nama_produk, sku_terdeteksi, kurir, nama_toko "
                            "FROM penjualan WHERE (no_resi = ? OR no_pesanan = ?) AND status_pesanan != 'CANCEL' LIMIT 1",
                            (cleaned, cleaned),
                        )

                        if match:
                            real_resi = match["no_resi"]
                            is_order_scan = (cleaned.upper() != real_resi.upper())

                            # Double scan check on real_resi
                            existing = db.fetch_one(
                                "SELECT id, status, waktu, tanggal, toko FROM scan_aktif WHERE resi = ?",
                                (real_resi,),
                            )
                            if existing:
                                status_emoji = {"PACKED": "✅", "PENDING": "⏳", "CANCEL": "❌"}.get(existing["status"], "📋")
                                st.toast("🚫 DOUBLE SCAN!", icon="🚫")
                                st.error(
                                    f"🚫 **DOUBLE SCAN DITOLAK!**\n\n"
                                    f"{'No Pesanan' if is_order_scan else 'Resi'} `{cleaned}` → Resi `{real_resi}` sudah di-scan:\n"
                                    f"• Status: {status_emoji} **{existing['status']}**\n"
                                    f"• Waktu: {existing['waktu']} | Tanggal: {existing['tanggal']}\n"
                                    f"• Toko: {existing['toko']}"
                                )
                            else:
                                scan_toko = match["nama_toko"] or selected_toko
                                db.execute(
                                    "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, status, kategori, keterangan_barang, tipe_kiriman, marketplace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    (waktu, tanggal, real_resi, match["kurir"] or "Unknown", scan_toko, "PACKED", kategori, keterangan_barang, tipe_kiriman, match.get("marketplace", "")),
                                )
                                # Update penjualan — pakai no_resi DAN no_pesanan sekaligus untuk memastikan
                                db.execute(
                                    "UPDATE penjualan SET status_pesanan = 'PACKED' WHERE no_resi = ? OR no_pesanan = ?",
                                    (real_resi, match["no_pesanan"]),
                                )
                                # Verifikasi update berhasil
                                verify = db.fetch_one(
                                    "SELECT COUNT(*) as cnt FROM penjualan WHERE (no_resi = ? OR no_pesanan = ?) AND status_pesanan = 'PACKED'",
                                    (real_resi, match["no_pesanan"]),
                                )
                                if not verify or verify["cnt"] == 0:
                                    st.warning(f"⚠️ Gagal update status penjualan untuk resi `{real_resi}`. Coba refresh.")

                                scan_type = "No Pesanan → Resi" if is_order_scan else "Resi"
                                tipe_label = "🚀 INSTANT" if tipe_kiriman == "INSTANT" else "PACKED"
                                st.success(f"✅ **{tipe_label}!** ({scan_type}) `{real_resi}`")
                                st.info(
                                    f"📦 {match['marketplace']} | {match['no_pesanan']}\n"
                                    f"🛍️ {match['nama_produk'][:50]}\n"
                                    f"🏪 {match['nama_toko'] or '-'} | 🚚 {match['kurir'] or '-'} | SKU: {match['sku_terdeteksi'] or '?'}"
                                )

                                # ── Auto-save barang besar baru ke daftar ──
                                if is_besar and keterangan_barang:
                                    existing_brg = db.fetch_one(
                                        "SELECT id FROM daftar_barang_besar WHERE nama_barang = ?",
                                        (keterangan_barang,),
                                    )
                                    if not existing_brg:
                                        try:
                                            db.execute(
                                                "INSERT INTO daftar_barang_besar (nama_barang, keterangan) VALUES (?, ?)",
                                                (keterangan_barang, "Ditambahkan otomatis dari scan"),
                                            )
                                        except:
                                            pass  # ignore duplicate

                                # ── Auto-sync toko ke toko table ──
                                if match["nama_toko"]:
                                    try:
                                        db.execute(
                                            "INSERT OR IGNORE INTO toko (nama) VALUES (?)",
                                            (match["nama_toko"].strip(),),
                                        )
                                    except:
                                        pass
                        else:
                            # Not found in penjualan
                            db.execute(
                                "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, status, kategori, keterangan_barang, tipe_kiriman, marketplace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (waktu, tanggal, cleaned, "Unknown", selected_toko, "PENDING", kategori, keterangan_barang, tipe_kiriman, ""),
                            )
                            st.warning(f"⏳ **PENDING!** `{cleaned}` belum ada di data penjualan (baik sebagai No Resi maupun No Pesanan).")

                            # ── Auto-save barang besar baru ke daftar (PENDING path) ──
                            if is_besar and keterangan_barang:
                                existing_brg = db.fetch_one(
                                    "SELECT id FROM daftar_barang_besar WHERE nama_barang = ?",
                                    (keterangan_barang,),
                                )
                                if not existing_brg:
                                    try:
                                        db.execute(
                                            "INSERT INTO daftar_barang_besar (nama_barang, keterangan) VALUES (?, ?)",
                                            (keterangan_barang, "Ditambahkan otomatis dari scan"),
                                        )
                                    except:
                                        pass
                        st.rerun()

        st.markdown("---")

        # ── Scan History Table ──
        st.subheader("📋 Riwayat Scan Packing")

        # Filter kategori
        filter_col1, filter_col2 = st.columns([1, 3])
        with filter_col1:
            kategori_filter = st.selectbox(
                "Filter Kategori",
                ["Semua", "REGULER", "BESAR"],
                key="scan_ops_kategori_filter",
            )

        scans = db.fetch_all(
            "SELECT MAX(s.id) as id, s.waktu, s.tanggal, s.resi, s.toko, s.status, s.kategori, s.keterangan_barang, "
            "p.marketplace, p.no_pesanan, "
            "GROUP_CONCAT(p.nama_produk, ', ') as nama_produk, "
            "p.kurir, GROUP_CONCAT(p.sku_terdeteksi, ', ') as sku_terdeteksi "
            "FROM scan_aktif s LEFT JOIN penjualan p ON s.resi = p.no_resi "
            "GROUP BY s.resi ORDER BY MAX(s.id) DESC LIMIT 100"
        )
        if not scans:
            st.info("📭 Belum ada scan. Mulai scan resi fisik.")
        else:
            df_scans = pd.DataFrame([dict(r) for r in scans])

            # Apply kategori filter
            if kategori_filter != "Semua":
                df_scans = df_scans[df_scans["kategori"] == kategori_filter]

            df_scans = df_scans.rename(columns={
                "waktu": "Waktu", "tanggal": "Tanggal", "resi": "No Resi",
                "marketplace": "MP", "no_pesanan": "No Pesanan",
                "nama_produk": "Produk", "kurir": "Kurir",
                "sku_terdeteksi": "SKU", "toko": "Toko", "status": "Status",
                "kategori": "Kategori", "keterangan_barang": "Keterangan",
            })

            def color_packed(val):
                if val == "PACKED":
                    return "background-color: #d4edda; color: #155724; font-weight: bold"
                elif val == "PENDING":
                    return "background-color: #fff3cd; color: #856404; font-weight: bold"
                elif val == "CANCEL":
                    return "background-color: #f8d7da; color: #721c24; font-weight: bold"
                return ""

            def color_kategori(val):
                if val == "BESAR":
                    return "background-color: #e8d1f5; color: #6a1b9a; font-weight: bold"
                return ""

            display_cols = ["Waktu", "No Resi", "Kategori", "Keterangan", "MP", "No Pesanan", "Produk", "SKU", "Kurir", "Toko", "Status"]
            available_cols = [c for c in display_cols if c in df_scans.columns]
            styled = df_scans[available_cols].style.map(color_packed, subset=["Status"]).map(color_kategori, subset=["Kategori"])
            st.dataframe(styled, width="stretch", height=400, hide_index=True)

            # ── Statistik per Kategori ──
            if "Kategori" in df_scans.columns:
                st.markdown("---")
                st.caption("📊 Distribusi Kategori:")
                reg_count = len(df_scans[df_scans["Kategori"] == "REGULER"]) if kategori_filter == "Semua" else 0
                besar_count = len(df_scans[df_scans["Kategori"] == "BESAR"]) if kategori_filter == "Semua" else 0
                if kategori_filter == "Semua":
                    cat_col1, cat_col2 = st.columns(2)
                    with cat_col1:
                        st.metric("📦 Reguler", reg_count)
                    with cat_col2:
                        st.metric("📦 Barang Besar", besar_count)

            # ── Actions ──
            st.markdown("---")
            col_a1, col_a2, col_a3 = st.columns(3)
            with col_a1:
                delete_resi = st.text_input("Hapus Resi", placeholder="Nomor resi...", key="scan_ops_del_resi")
                if st.button("🗑️ Hapus", width="stretch", key="scan_ops_del_btn"):
                    if delete_resi.strip():
                        cleaned_del = Validator.sanitize_resi(delete_resi.strip())
                        if cleaned_del:
                            # Revert penjualan status sebelum hapus scan
                            db.execute("UPDATE penjualan SET status_pesanan = '' WHERE no_resi = ?", (cleaned_del,))
                            db.execute("DELETE FROM scan_aktif WHERE resi = ?", (cleaned_del,))
                            st.success(f"'{cleaned_del}' dihapus — status penjualan dikembalikan.")
                            st.rerun()
            with col_a2:
                if st.button("↩️ Undo Terakhir", width="stretch", key="scan_ops_undo"):
                    row = db.fetch_one("SELECT id, resi FROM scan_aktif ORDER BY id DESC LIMIT 1")
                    if row:
                        # Revert penjualan status sebelum hapus scan
                        db.execute("UPDATE penjualan SET status_pesanan = '' WHERE no_resi = ?", (row["resi"],))
                        db.execute("DELETE FROM scan_aktif WHERE id = ?", (row["id"],))
                        st.success("Scan terakhir di-undo — status penjualan dikembalikan.")
                        st.rerun()
            with col_a3:
                # Export packed items only
                if st.button("📊 Export Packed (Excel)", width="stretch", type="primary", key="scan_ops_export"):
                    packed_items = db.fetch_all(
                        "SELECT s.waktu, s.tanggal, s.resi, s.ekspedisi, s.toko, s.status, "
                        "p.marketplace, p.no_pesanan, p.nama_produk, p.sku_terdeteksi "
                        "FROM scan_aktif s LEFT JOIN penjualan p ON s.resi = p.no_resi "
                        "WHERE s.status IN ('PACKED', 'CANCEL') ORDER BY s.id DESC"
                    )
                    if packed_items:
                        df_exp = pd.DataFrame([dict(r) for r in packed_items])
                        now_exp = datetime.now()
                        filename = f"Packing_List_{now_exp.strftime('%d-%m-%Y_%H%M%S')}.xlsx"
                        filepath = os.path.join(Config.ARSIP_FOLDER, filename)
                        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                            df_exp.to_excel(writer, index=False, sheet_name="Packed")
                        with open(filepath, "rb") as fp:
                            st.download_button("⬇️ Download Packing List", fp, file_name=filename)
                        st.success(f"✅ {filename}")
                    else:
                        st.warning("Tidak ada data PACKED.")

    elif page == "Scan History":
        st.title("📋 Scan History")
        render_scan_history()

    elif page == "Handover":
        st.title("📋 Handover — Serah Terima per Kurir")
        db = st.session_state.db

        # ── Stats ──
        packed = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED' AND tipe_kiriman = 'REGULER'")
        instant = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED' AND tipe_kiriman = 'INSTANT'")
        packed_besar = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED' AND kategori = 'BESAR'")
        st.caption(f"📦 Reguler: {packed['cnt']} | 🚀 Instant: {instant['cnt']} | 📦 Barang Besar: {packed_besar['cnt']}")

        st.markdown("---")

        tab_reg, tab_inst = st.tabs(["📦 Reguler", "🚀 Instant / Prioritas"])

        # ═══════════════ TAB REGULER ═══════════════
        with tab_reg:
            _render_handover_tab(db, "REGULER")

        # ═══════════════ TAB INSTANT ═══════════════
        with tab_inst:
            st.caption("Kiriman Instant/Prioritas — sudah di-scan, siap diambil kurir. Konfirmasi setelah kurir mengambil paket.")
            _render_handover_tab(db, "INSTANT")

    elif page == "Ekspedisi":
        st.title("🚚 Manajemen Ekspedisi")
        render_ekspedisi()

    elif page == "Toko":
        st.title("🏪 Manajemen Toko")
        render_toko()

    elif page == "Barang_Besar":
        st.title("📦 Daftar Barang Besar")
        st.caption("Kelola daftar barang besar untuk keperluan scan packing (bak cuci, wastafel, tempat sampah, gerobak, dll).")

        db = st.session_state.db

        # ── Form Tambah Barang ──
        with st.expander("➕ Tambah Barang Besar Baru", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                nama_baru = st.text_input("Nama Barang", placeholder="Contoh: Bak Cuci Piring", key="besar_nama")
            with col2:
                ket_baru = st.text_input("Keterangan (opsional)", placeholder="Ukuran, bahan, dll", key="besar_ket")
            if st.button("💾 Simpan", type="primary"):
                if nama_baru.strip():
                    try:
                        db.execute(
                            "INSERT INTO daftar_barang_besar (nama_barang, keterangan) VALUES (?, ?)",
                            (nama_baru.strip(), ket_baru.strip()),
                        )
                        st.success(f"✅ '{nama_baru.strip()}' ditambahkan!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal: {e}")
                else:
                    st.warning("Nama barang tidak boleh kosong.")

        st.markdown("---")

        # ── Daftar Barang Besar ──
        daftar = db.fetch_all("SELECT id, nama_barang, keterangan, created_at FROM daftar_barang_besar ORDER BY nama_barang")

        if not daftar:
            st.info("📭 Belum ada daftar barang besar. Tambahkan di atas.")
        else:
            st.subheader(f"📋 Daftar Barang Besar ({len(daftar)} items)")

            for item in daftar:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.markdown(f"**{item['nama_barang']}**")
                    if item["keterangan"]:
                        st.caption(f"📝 {item['keterangan']}")
                with col2:
                    st.caption(f"🕐 {item['created_at'][:10] if item['created_at'] else '-'}")
                with col3:
                    if st.button("🗑️", key=f"del_besar_{item['id']}", help=f"Hapus {item['nama_barang']}"):
                        db.execute("DELETE FROM daftar_barang_besar WHERE id = ?", (item['id'],))
                        st.success(f"🗑️ '{item['nama_barang']}' dihapus.")
                        st.rerun()

        # ── Statistik Barang Besar di Scan ──
        st.markdown("---")
        st.subheader("📊 Statistik Scan Barang Besar")
        besar_scans = db.fetch_all(
            "SELECT s.keterangan_barang, s.kategori, COUNT(*) as cnt "
            "FROM scan_aktif s "
            "WHERE s.kategori = 'BESAR' AND s.keterangan_barang != '' "
            "GROUP BY s.keterangan_barang ORDER BY cnt DESC"
        )
        if besar_scans:
            df_besar_stats = pd.DataFrame([dict(r) for r in besar_scans])
            df_besar_stats = df_besar_stats.rename(columns={
                "keterangan_barang": "Nama Barang",
                "kategori": "Kategori",
                "cnt": "Jumlah Scan",
            })
            st.dataframe(df_besar_stats, width="stretch", hide_index=True)
        else:
            st.caption("Belum ada data scan barang besar.")

    elif page == "Reports":
        st.title("📊 Reports")
        render_reports()

    elif page == "Sales_Input":
        st.title("📦 Input Resi & Pesanan (Marketplace)")
        render_sales_input()

    elif page == "Sales_Daily_Report":
        st.title("📊 Laporan Penjualan Harian")
        render_sales_daily_report()

    elif page == "AI_Supervisor":
        st.title("🤖 AI Supervisor — Pantauan & Rekomendasi")
        render_ai_supervisor()

    # ── Penjualan Pages ──
    elif page == "Sales_Dashboard":
        st.title("💰 Dashboard Penjualan")

        col_title, col_refresh = st.columns([5, 1])
        with col_title:
            st.caption(f"Ringkasan penjualan marketplace — {datetime.now().strftime('%d %B %Y, %H:%M')}")
        with col_refresh:
            if st.button("🔄 Refresh", width="stretch", key="sales_dash_refresh", help="Klik untuk memperbarui data"):
                st.rerun()

        db = st.session_state.db

        # ── Stats: selaras dengan Scan Operasional ──
        # Unique resi (paket fisik yang harus di-scan) — sama dengan Scan Operasional
        total_resi_unique = db.fetch_one("SELECT COUNT(DISTINCT no_resi) as cnt FROM penjualan WHERE no_resi != '' AND no_resi IS NOT NULL")
        total_unique_resi = total_resi_unique["cnt"] if total_resi_unique else 0

        # Total rows dengan resi (termasuk multi-SKU)
        total_rows_resi = db.fetch_one("SELECT COUNT(*) as cnt FROM penjualan WHERE no_resi != '' AND no_resi IS NOT NULL")

        # Total unique orders (semua)
        total_orders = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan")
        total_orders_cnt = total_orders["cnt"] if total_orders else 0

        # Orders tanpa resi
        orders_tanpa_resi = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan WHERE no_resi = '' OR no_resi IS NULL")

        # Total Revenue Input: semua baris
        total_rev_input = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM penjualan")

        # Real Packed: dari scan_aktif (ground truth — unik per resi)
        real_packed = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'PACKED'")
        real_cnt = real_packed["cnt"] if real_packed else 0

        # Cancel: dari scan_aktif
        cancel_cnt_row = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE status = 'CANCEL'")
        cancel_cnt = cancel_cnt_row["cnt"] if cancel_cnt_row else 0

        # Revenue Real: dari penjualan, hanya resi yang PACKED di scan_aktif (termasuk multi-SKU)
        real_rev = db.fetch_one(
            "SELECT COALESCE(SUM(p.total_harga), 0) as total "
            "FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            "WHERE s.status = 'PACKED'"
        )

        # Revenue Cancel
        cancel_rev = db.fetch_one(
            "SELECT COALESCE(SUM(p.total_harga), 0) as total "
            "FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            "WHERE s.status = 'CANCEL'"
        )

        # Today's input
        today_sales = db.fetch_one(
            "SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan WHERE tanggal_pesanan = ?",
            (datetime.now().strftime("%d-%m-%Y"),),
        )

        # ── Kartu Statistik ──
        st.subheader("📊 Ringkasan Penjualan")
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("📦 Total Orders", f"{total_orders_cnt:,}",
                     help=f"Unique orders: {total_orders_cnt} | Unique resi: {total_unique_resi} | Orders tanpa resi: {orders_tanpa_resi['cnt']}")
        with col2:
            st.metric("✅ Real Terkirim (PACKED)", f"{real_cnt:,}",
                     help="Jumlah resi yang berhasil dipacking (dari Scan Operasional)")
        with col3:
            st.metric("❌ Cancel", f"{cancel_cnt:,}",
                     help="Jumlah resi yang dibatalkan saat scan")
        with col4:
            belum = total_unique_resi - real_cnt - cancel_cnt
            st.metric("⏳ Belum Diproses", f"{max(0, belum):,}",
                     help=f"Dari {total_unique_resi} unique resi yang harus di-scan. Total baris (incl. multi-SKU): {total_rows_resi['cnt']}")
        with col5:
            st.metric("📅 Input Hari Ini", f"{today_sales['cnt']}" if today_sales else "0")

        # ── Revenue Comparison ──
        st.markdown("---")
        st.subheader("💰 Perbandingan Revenue")
        rev_col1, rev_col2, rev_col3 = st.columns(3)
        with rev_col1:
            tr = total_rev_input["total"] if total_rev_input else 0
            st.metric("📋 Total Revenue (Input)", f"Rp {tr:,.0f}")
        with rev_col2:
            rr = real_rev["total"] if real_rev else 0
            st.metric("✅ Real Revenue (Terkirim)", f"Rp {rr:,.0f}",
                     delta=f"Rp {rr - tr:,.0f}" if tr != rr else None)
        with rev_col3:
            cr = cancel_rev["total"] if cancel_rev else 0
            st.metric("❌ Revenue Hilang (Cancel)", f"Rp {cr:,.0f}")

        # Progress bar
        if total_unique_resi > 0:
            real_pct = (real_cnt / total_unique_resi * 100)
            cancel_pct = (cancel_cnt / total_unique_resi * 100)
            belum_pct = max(0, 100 - real_pct - cancel_pct)
            st.progress(real_pct / 100, text=f"🎯 Real Terkirim: {real_pct:.1f}% | Cancel: {cancel_pct:.1f}% | Belum: {belum_pct:.1f}%")

        st.markdown("---")

        # ── Per Marketplace (input vs packed via JOIN scan_aktif) ──
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("📊 Per Marketplace")
            mp_data = db.fetch_all(
                "SELECT p.marketplace, "
                "COUNT(DISTINCT p.no_pesanan) as total_orders, "
                "COUNT(DISTINCT CASE WHEN s.status = 'PACKED' THEN p.no_pesanan END) as packed_orders, "
                "COALESCE(SUM(p.total_harga), 0) as rev_input, "
                "COALESCE(SUM(CASE WHEN s.status = 'PACKED' THEN p.total_harga ELSE 0 END), 0) as rev_real "
                "FROM penjualan p LEFT JOIN scan_aktif s ON p.no_resi = s.resi "
                "GROUP BY p.marketplace ORDER BY rev_input DESC"
            )
            if mp_data:
                df_mp = pd.DataFrame([dict(r) for r in mp_data])
                df_mp = df_mp.rename(columns={
                    "marketplace": "Marketplace", "total_orders": "Input (Orders)",
                    "packed_orders": "Packed", "rev_input": "Rev Input", "rev_real": "Rev Real",
                })
                df_mp["Rev Input"] = df_mp["Rev Input"].apply(lambda x: f"Rp {x:,.0f}")
                df_mp["Rev Real"] = df_mp["Rev Real"].apply(lambda x: f"Rp {x:,.0f}")
                st.dataframe(df_mp, width="stretch", hide_index=True)

        with col_right:
            st.subheader("🏪 Per Toko")
            toko_data = db.fetch_all(
                "SELECT p.nama_toko, "
                "COUNT(DISTINCT p.no_pesanan) as total_orders, "
                "COUNT(DISTINCT CASE WHEN s.status = 'PACKED' THEN p.no_pesanan END) as packed_orders, "
                "COALESCE(SUM(CASE WHEN s.status = 'PACKED' THEN p.total_harga ELSE 0 END), 0) as rev_real "
                "FROM penjualan p LEFT JOIN scan_aktif s ON p.no_resi = s.resi "
                "WHERE p.nama_toko != '' "
                "GROUP BY p.nama_toko ORDER BY rev_real DESC LIMIT 10"
            )
            if toko_data:
                df_toko = pd.DataFrame([dict(r) for r in toko_data])
                df_toko = df_toko.rename(columns={
                    "nama_toko": "Toko", "total_orders": "Input (Orders)",
                    "packed_orders": "Packed", "rev_real": "Rev Real",
                })
                df_toko["Rev Real"] = df_toko["Rev Real"].apply(lambda x: f"Rp {x:,.0f}")
                st.dataframe(df_toko, width="stretch", hide_index=True)

        # ── Top SKU (hanya PACKED) ──
        st.markdown("---")
        st.subheader("🏆 Top SKU Terkirim (Real)")
        top_sku = db.fetch_all(
            "SELECT p.sku_terdeteksi, p.nama_produk, SUM(p.qty) as total_qty, SUM(p.total_harga) as total "
            "FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            "WHERE p.sku_terdeteksi != '' AND s.status = 'PACKED' "
            "GROUP BY p.sku_terdeteksi ORDER BY total DESC LIMIT 10"
        )
        if top_sku:
            df_top = pd.DataFrame([dict(r) for r in top_sku])
            df_top = df_top.rename(columns={
                "sku_terdeteksi": "SKU", "nama_produk": "Produk",
                "total_qty": "Total Qty", "total": "Total Real",
            })
            df_top["Total Real"] = df_top["Total Real"].apply(lambda x: f"Rp {x:,.0f}")
            st.dataframe(df_top, width="stretch", hide_index=True)
        else:
            st.info("Belum ada SKU yang berhasil dikirim (PACKED).")

        # ── Recent Orders ──
        st.markdown("---")
        st.subheader("🛍️ Pesanan Terbaru")
        recent = db.fetch_all(
            "SELECT p.marketplace, p.no_pesanan, p.no_resi, p.kurir, p.sku_terdeteksi, p.nama_produk, "
            "p.nama_toko, p.qty, p.total_harga, p.status_pesanan "
            "FROM penjualan p ORDER BY p.created_at DESC LIMIT 10"
        )
        if recent:
            df_rec = pd.DataFrame([dict(r) for r in recent])
            df_rec["total_harga"] = df_rec["total_harga"].apply(lambda x: f"Rp {x:,.0f}")
            df_rec = df_rec.rename(columns={
                "marketplace": "MP", "no_pesanan": "No Pesanan", "no_resi": "Resi", "kurir": "Kurir",
                "sku_terdeteksi": "SKU", "nama_produk": "Produk", "nama_toko": "Toko",
                "qty": "Qty", "total_harga": "Total", "status_pesanan": "Status",
            })
            def color_sales_status(val):
                if val == "PACKED":
                    return "background-color: #d4edda; color: #155724; font-weight: bold"
                elif val == "CANCEL":
                    return "background-color: #f8d7da; color: #721c24; font-weight: bold"
                return ""
            styled = df_rec.style.map(color_sales_status, subset=["Status"])
            st.dataframe(styled, width="stretch", hide_index=True)

    elif page == "Sales_History":
        st.title("📋 Riwayat Penjualan")
        st.info("🚧 Fitur Penjualan akan segera hadir. Halaman ini akan menampilkan riwayat transaksi penjualan dengan filter & pencarian.")
        st.markdown("""
        **Rencana Fitur:**
        - 🔍 Pencarian & filter transaksi
        - 📋 Tabel riwayat penjualan
        - ✏️ Edit / hapus transaksi
        - 📤 Export ke Excel
        """)

    elif page == "Sales_Archive":
        st.title("📁 Arsip Penjualan")
        st.info("🚧 Fitur Penjualan akan segera hadir. Halaman ini akan menyimpan arsip laporan penjualan dalam format Excel.")
        st.markdown("""
        **Rencana Fitur:**
        - 💾 Simpan laporan penjualan ke Excel
        - 📥 Download arsip penjualan
        - 🗑️ Hapus arsip lama
        """)

    # ── Pembelian Pages ──
    elif page == "Purchase_Dashboard":
        st.title("🛒 Dashboard Pembelian")
        st.caption(f"Ringkasan inventaris & pembelian — {datetime.now().strftime('%d %B %Y, %H:%M')}")

        db = st.session_state.db

        # ── Stats Cards ──
        total_sku = db.fetch_one("SELECT COUNT(*) as cnt FROM sku")
        total_stok = db.fetch_one("SELECT COALESCE(SUM(stok), 0) as total FROM sku")
        total_value = db.fetch_one("SELECT COALESCE(SUM(stok * harga_beli), 0) as total FROM sku")
        low_stock = db.fetch_one("SELECT COUNT(*) as cnt FROM sku WHERE stok <= 10 AND stok > 0")
        zero_stock = db.fetch_one("SELECT COUNT(*) as cnt FROM sku WHERE stok = 0")

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("📦 Total SKU", total_sku["cnt"] if total_sku else 0)
        with col2:
            st.metric("📊 Total Stok", f"{total_stok['total']:,}" if total_stok else "0")
        with col3:
            val = total_value["total"] if total_value else 0
            st.metric("💰 Nilai Inventaris", f"Rp {val:,.0f}")
        with col4:
            st.metric("⚠️ Stok Menipis", low_stock["cnt"] if low_stock else 0)
        with col5:
            st.metric("❌ Stok Habis", zero_stock["cnt"] if zero_stock else 0)

        st.markdown("---")

        # ── SKU dengan stok menipis / habis ──
        alert_sku = db.fetch_all(
            "SELECT kode_sku, nama_barang, stok, satuan, supplier FROM sku WHERE stok <= 10 ORDER BY stok ASC"
        )
        if alert_sku:
            st.warning(f"⚠️ **{len(alert_sku)} SKU membutuhkan restock!**")
            df_alert = pd.DataFrame([dict(r) for r in alert_sku])
            df_alert = df_alert.rename(columns={
                "kode_sku": "Kode SKU", "nama_barang": "Nama Barang",
                "stok": "Stok", "satuan": "Satuan", "supplier": "Supplier",
            })
            st.dataframe(df_alert, width="stretch", hide_index=True)

        # ── Ringkasan per Kategori ──
        st.markdown("---")
        st.subheader("📊 Ringkasan per Kategori")
        kat_rows = db.fetch_all(
            "SELECT kategori, COUNT(*) as jml_sku, SUM(stok) as total_stok, "
            "SUM(stok * harga_beli) as total_nilai FROM sku WHERE kategori != '' "
            "GROUP BY kategori ORDER BY total_nilai DESC"
        )
        if kat_rows:
            df_kat = pd.DataFrame([dict(r) for r in kat_rows])
            df_kat = df_kat.rename(columns={
                "kategori": "Kategori", "jml_sku": "Jumlah SKU",
                "total_stok": "Total Stok", "total_nilai": "Total Nilai (Rp)",
            })
            df_kat["Total Nilai (Rp)"] = df_kat["Total Nilai (Rp)"].apply(lambda x: f"Rp {x:,.0f}")
            st.dataframe(df_kat, width="stretch", hide_index=True)

        # ── Quick links ──
        st.markdown("---")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.info("🏷️ **Manajemen SKU** — Tambah, edit, hapus data SKU barang dan update stok secara manual.")
        with col_b:
            st.info("🛒 **Input Pembelian** — Catat pembelian dari supplier, auto-update stok SKU.")
        with col_c:
            st.info("📋 **Riwayat Pembelian** — Lihat & filter history transaksi pembelian.")

        # ── Recent Purchases ──
        st.markdown("---")
        st.subheader("🛒 Pembelian Terbaru")
        recent_purchases = db.fetch_all(
            "SELECT no_faktur, tanggal, supplier, metode_bayar, status_bayar, COUNT(*) as items, SUM(total_harga) as total "
            "FROM pembelian GROUP BY no_faktur ORDER BY created_at DESC LIMIT 5"
        )
        if recent_purchases:
            df_recent = pd.DataFrame([dict(r) for r in recent_purchases])
            df_recent = df_recent.rename(columns={
                "no_faktur": "No Faktur", "tanggal": "Tanggal", "supplier": "Supplier",
                "metode_bayar": "Metode Bayar", "status_bayar": "Status Bayar",
                "items": "Item", "total": "Total",
            })
            df_recent["Total"] = df_recent["Total"].apply(lambda x: f"Rp {x:,.0f}")
            st.dataframe(df_recent, width="stretch", hide_index=True)

            # Total pembelian + pending + kontrabon
            total_pembelian = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM pembelian")
            total_pending = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM pembelian WHERE status_bayar = 'PENDING'")
            total_kontrabon = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM pembelian WHERE status_bayar = 'KONTRA BON'")
            if total_pembelian:
                pd_text = f" | 📌 Pending: **Rp {total_pending['total']:,.0f}**" if total_pending and total_pending["total"] > 0 else ""
                kb_text = f" | ⚠️ Kontrabon: **Rp {total_kontrabon['total']:,.0f}**" if total_kontrabon and total_kontrabon["total"] > 0 else ""
                st.caption(f"💰 Total seluruh pembelian: **Rp {total_pembelian['total']:,.0f}**{pd_text}{kb_text}")
        else:
            st.info("Belum ada transaksi pembelian. Mulai dari menu 🛒 Input Pembelian.")

    elif page == "Purchase_SKU":
        st.title("🏷️ Manajemen SKU")
        render_sku()

    elif page == "Purchase_Input":
        st.title("🛒 Input Pembelian ke Supplier")
        render_purchase_input()

    elif page == "Purchase_History":
        st.title("📋 Riwayat Pembelian")
        render_purchase_history()

    elif page == "Purchase_Finance":
        st.title("💳 Finance — Konfirmasi Pembayaran")
        render_purchase_finance()

    elif page == "Purchase_Archive":
        st.title("📁 Arsip Pembelian")
        render_purchase_archive()


if __name__ == "__main__":
    main()
