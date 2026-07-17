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


# ==================== PWA INJECTION ====================
def inject_pwa():
    """PWA - inject once per session only."""
    if st.session_state.get("_pwa_injected"):
        return
    st.session_state._pwa_injected = True
    st.html('<link rel="manifest" href="/app/static/manifest.json" crossorigin="use-credentials">')


# ==================== DATABASE ====================
class Database:
    """Thread-safe SQLite database wrapper."""

    def __init__(self):
        self.db_path = Config.DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
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
                    biaya_operasional REAL DEFAULT 0,
                    biaya_packing REAL DEFAULT 0,
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
            try:
                cursor.execute("ALTER TABLE pembelian ADD COLUMN biaya_operasional REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE pembelian ADD COLUMN biaya_packing REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

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

            # ── Master Data tables ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS supplier (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT NOT NULL UNIQUE,
                    kontak TEXT DEFAULT '',
                    alamat TEXT DEFAULT '',
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kategori_produk (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT NOT NULL UNIQUE,
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gudang (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT NOT NULL UNIQUE,
                    lokasi TEXT DEFAULT '',
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

            # Migration: settlement reconciliation columns
            try:
                cursor.execute("ALTER TABLE penjualan ADD COLUMN potongan_marketplace REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE penjualan ADD COLUMN status_settlement TEXT DEFAULT 'UNSETTLED'")
            except sqlite3.OperationalError:
                pass
            # Set default for existing rows
            try:
                cursor.execute("UPDATE penjualan SET status_settlement = 'UNSETTLED' WHERE status_settlement IS NULL OR status_settlement = ''")
            except:
                pass

            # ── Aset Tetap & Modal tables ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aset_tetap (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama_aset TEXT NOT NULL,
                    kategori TEXT DEFAULT '',
                    tanggal_perolehan TEXT NOT NULL,
                    harga_perolehan REAL NOT NULL DEFAULT 0,
                    masa_manfaat INTEGER DEFAULT 4,
                    metode_depresiasi TEXT DEFAULT 'GARIS_LURUS',
                    nilai_sisa REAL DEFAULT 0,
                    akumulasi_depresiasi REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS modal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    jenis TEXT NOT NULL DEFAULT 'AWAL',
                    tanggal TEXT NOT NULL,
                    jumlah REAL NOT NULL DEFAULT 0,
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Default modal awal if empty
            try:
                cursor.execute("SELECT COUNT(*) FROM modal")
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "INSERT INTO modal (jenis, tanggal, jumlah, keterangan) VALUES (?, ?, ?, ?)",
                        ("AWAL", datetime.now().strftime("%d-%m-%Y"), 0, "Modal awal - isi dengan jumlah sebenarnya"),
                    )
            except:
                pass

            # ── Pinjaman / Utang Bank ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pinjaman (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama_bank TEXT NOT NULL,
                    pokok REAL NOT NULL DEFAULT 0,
                    bunga_persen REAL DEFAULT 0,
                    tenor_bulan INTEGER DEFAULT 12,
                    cicilan_per_bulan REAL DEFAULT 0,
                    tanggal_mulai TEXT NOT NULL,
                    sisa_pokok REAL DEFAULT 0,
                    total_bunga_dibayar REAL DEFAULT 0,
                    status TEXT DEFAULT 'AKTIF',
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Biaya Dibayar di Muka ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS biaya_dibayar_dimuka (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deskripsi TEXT NOT NULL,
                    kategori TEXT DEFAULT 'Sewa',
                    jumlah_total REAL NOT NULL DEFAULT 0,
                    jumlah_per_bulan REAL DEFAULT 0,
                    bulan_mulai TEXT NOT NULL,
                    bulan_selesai TEXT NOT NULL,
                    sisa_belum_diakui REAL DEFAULT 0,
                    status TEXT DEFAULT 'AKTIF',
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Jurnal Amortisasi (Bunga + Sewa Dimuka) ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS amortisasi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    jenis TEXT NOT NULL,
                    id_ref INTEGER NOT NULL,
                    periode_bulan TEXT NOT NULL,
                    jumlah REAL NOT NULL DEFAULT 0,
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ═══════════════════════════════════════════
            # ── AKUNTANSI AKRUAL: COA + Jurnal Umum ──
            # ═══════════════════════════════════════════

            # Chart of Accounts (COA)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS coa (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kode TEXT UNIQUE NOT NULL,
                    nama TEXT NOT NULL,
                    tipe TEXT NOT NULL DEFAULT 'BEBAN',
                    kelompok TEXT DEFAULT '',
                    saldo_normal TEXT DEFAULT 'DEBIT',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Jurnal Umum (Double-Entry)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jurnal_umum (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tanggal TEXT NOT NULL,
                    no_ref TEXT NOT NULL,
                    kode_akun TEXT NOT NULL,
                    nama_akun TEXT NOT NULL,
                    deskripsi TEXT DEFAULT '',
                    debit REAL DEFAULT 0,
                    kredit REAL DEFAULT 0,
                    sumber TEXT DEFAULT '',
                    id_sumber INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Settlement harian marketplace
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settlement_harian (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tanggal TEXT NOT NULL,
                    marketplace TEXT NOT NULL,
                    total_penjualan REAL DEFAULT 0,
                    total_fee REAL DEFAULT 0,
                    total_pencairan REAL DEFAULT 0,
                    total_biaya_lain REAL DEFAULT 0,
                    saldo_akhir REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Biaya Iklan harian per marketplace
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS iklan_harian (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tanggal TEXT NOT NULL,
                    marketplace TEXT NOT NULL,
                    biaya REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Gudang Inventory ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rak_gudang (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kode TEXT UNIQUE NOT NULL,
                    nama TEXT NOT NULL,
                    lokasi TEXT DEFAULT '',
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_opname (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kode_sku TEXT NOT NULL,
                    stok_sistem INTEGER NOT NULL,
                    stok_fisik INTEGER NOT NULL,
                    selisih INTEGER NOT NULL,
                    keterangan TEXT DEFAULT '',
                    operator TEXT DEFAULT '',
                    tanggal TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Migration: posisi_rak di SKU ──
            try:
                cursor.execute("ALTER TABLE sku ADD COLUMN posisi_rak TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            # ── Seed COA default jika kosong ──
            try:
                cursor.execute("SELECT COUNT(*) FROM coa")
                if cursor.fetchone()[0] == 0:
                    default_coa = [
                        ("1-1000", "Kas & Bank", "ASET", "ASET LANCAR", "DEBIT"),
                        ("1-1100", "Piutang Usaha", "ASET", "ASET LANCAR", "DEBIT"),
                        ("1-1200", "Persediaan Barang", "ASET", "ASET LANCAR", "DEBIT"),
                        ("1-1300", "Biaya Dibayar di Muka", "ASET", "ASET LANCAR", "DEBIT"),
                        ("1-2000", "Aset Tetap", "ASET", "ASET TETAP", "DEBIT"),
                        ("1-2100", "Akumulasi Depresiasi", "ASET", "ASET TETAP", "KREDIT"),
                        ("2-1000", "Hutang Usaha", "LIABILITAS", "LIABILITAS", "KREDIT"),
                        ("2-1100", "Hutang Bank", "LIABILITAS", "LIABILITAS", "KREDIT"),
                        ("2-1200", "PPN Keluaran", "LIABILITAS", "LIABILITAS", "KREDIT"),
                        ("3-1000", "Modal Disetor", "EKUITAS", "EKUITAS", "KREDIT"),
                        ("3-2000", "Laba Ditahan", "EKUITAS", "EKUITAS", "KREDIT"),
                        ("4-1000", "Pendapatan Penjualan", "PENDAPATAN", "PENDAPATAN", "KREDIT"),
                        ("4-1100", "Pendapatan Lainnya", "PENDAPATAN", "PENDAPATAN", "KREDIT"),
                        ("5-1000", "Harga Pokok Penjualan", "BEBAN", "HPP", "DEBIT"),
                        ("5-1100", "Beban Fee Marketplace", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-1200", "Beban Packing Variable", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-1300", "Beban Operasional Tetap", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-1400", "Beban Gaji & Upah", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-1500", "Beban Depresiasi", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-1600", "Beban Bunga", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-1700", "Beban Pajak", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-1800", "Beban Transportasi", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-1900", "Beban Listrik & Air", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-2000", "Beban Internet", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-2100", "Beban Sewa", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-2200", "Beban Retur & Klaim", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                        ("5-2300", "Beban Iklan", "BEBAN", "BEBAN OPERASIONAL", "DEBIT"),
                    ]
                    for row in default_coa:
                        cursor.execute(
                            "INSERT INTO coa (kode, nama, tipe, kelompok, saldo_normal) VALUES (?,?,?,?,?)",
                            row,
                        )
            except:
                pass

            # ── Migration: accrual fields ──
            try:
                cursor.execute("ALTER TABLE opex ADD COLUMN tanggal_akrual TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE pembelian ADD COLUMN tanggal_akrual TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE penjualan ADD COLUMN ppn REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE pembelian ADD COLUMN ppn REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

            # ── Users & Roles table ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    nama_lengkap TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'operator',
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)

            # ── Auth tokens table (persistent login across refresh) ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)

            # ── Operational Expenses (OPEX) table ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS opex (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kategori TEXT NOT NULL DEFAULT 'Lainnya',
                    deskripsi TEXT NOT NULL,
                    supplier TEXT DEFAULT '',
                    qty INTEGER DEFAULT 1,
                    satuan TEXT DEFAULT 'pcs',
                    harga_satuan REAL DEFAULT 0,
                    total_harga REAL DEFAULT 0,
                    tanggal TEXT NOT NULL,
                    no_faktur TEXT DEFAULT '',
                    metode_bayar TEXT DEFAULT 'Transfer',
                    status_bayar TEXT DEFAULT 'PENDING',
                    keterangan TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: add columns for existing opex table
            try:
                cursor.execute("ALTER TABLE opex ADD COLUMN no_faktur TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            # Migration: add tipe column (VARIABLE / TETAP)
            try:
                cursor.execute("ALTER TABLE opex ADD COLUMN tipe TEXT DEFAULT 'VARIABLE'")
            except sqlite3.OperationalError:
                pass

            # Migration: set default tipe for existing rows
            try:
                cursor.execute("UPDATE opex SET tipe = 'VARIABLE' WHERE tipe IS NULL OR tipe = ''")
            except:
                pass

            # ── Retur & Klaim table ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS retur_klaim (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    no_resi TEXT DEFAULT '',
                    no_pesanan TEXT DEFAULT '',
                    marketplace TEXT DEFAULT '',
                    nama_toko TEXT DEFAULT '',
                    sku TEXT DEFAULT '',
                    nama_produk TEXT DEFAULT '',
                    qty INTEGER DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'DITERIMA',
                    alasan_klaim TEXT DEFAULT '',
                    keterangan TEXT DEFAULT '',
                    kurir TEXT DEFAULT '',
                    operator TEXT DEFAULT '',
                    waktu TEXT DEFAULT '',
                    tanggal TEXT DEFAULT '',
                    nominal_klaim REAL DEFAULT 0,
                    status_klaim TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: add columns for existing retur_klaim table
            try:
                cursor.execute("ALTER TABLE retur_klaim ADD COLUMN nominal_klaim REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE retur_klaim ADD COLUMN status_klaim TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            # ── Pengaturan (Settings) table ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pengaturan (
                    kunci TEXT PRIMARY KEY,
                    nilai TEXT DEFAULT ''
                )
            """)

            # Default settings if empty
            cursor.execute("SELECT COUNT(*) FROM pengaturan")
            if cursor.fetchone()[0] == 0:
                defaults = [
                    ("fee_shopee", "5.0"),
                    ("fee_tiktok", "4.0"),
                    ("fee_lazada", "4.5"),
                    ("fee_tokopedia", "4.0"),
                    ("biaya_per_resi", "1250"),
                    ("pph_persen", "0.5"),
                    ("ppn_persen", "11.0"),
                ]
                for k, v in defaults:
                    cursor.execute("INSERT OR IGNORE INTO pengaturan (kunci, nilai) VALUES (?, ?)", (k, v))

            # ── Pencairan (Marketplace Disbursement) table ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pencairan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    marketplace TEXT NOT NULL,
                    jumlah REAL NOT NULL,
                    tanggal TEXT NOT NULL,
                    keterangan TEXT DEFAULT '',
                    operator TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Handover TTD (Electronic Signature) table ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS handover_ttd (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kurir TEXT NOT NULL,
                    tipe_kiriman TEXT DEFAULT 'REGULER',
                    marketplace_filter TEXT DEFAULT '',
                    kategori_filter TEXT DEFAULT '',
                    jumlah_resi INTEGER DEFAULT 0,
                    ttd_operator TEXT DEFAULT '',
                    ttd_ekspedisi TEXT DEFAULT '',
                    nama_ekspedisi TEXT DEFAULT '',
                    waktu_ttd TEXT DEFAULT '',
                    tanggal_ttd TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

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


# ==================== AUTH HELPERS ====================
import hashlib
import secrets

# Role definitions & their menu access
ROLES = {
    "admin": {
        "label": "Admin",
        "desc": "Full access - semua menu termasuk manajemen user",
        "menus": ["Operasional", "Penjualan", "Pembelian", "OPEX", "Finance", "Akuntansi", "Master_Data", "Admin"],
    },
    "supervisor": {
        "label": "Supervisor",
        "desc": "Monitoring - dashboard, AI supervisor, reports",
        "menus": ["Operasional"],
        "pages": ["Dashboard", "AI_Supervisor", "Reports", "Handover", "Ekspedisi", "Retur_Klaim"],
    },
    "operator": {
        "label": "Operator",
        "desc": "Operasional - scan, input resi, handover, retur",
        "menus": ["Operasional"],
        "pages": ["Dashboard", "Scan_Operasional", "Sales_Input", "Handover", "Retur_Klaim", "Ekspedisi"],
    },
    "gudang": {
        "label": "Gudang",
        "desc": "Warehouse - Master Data, pembelian SKU & OPEX",
        "menus": ["Operasional", "Master_Data", "Pembelian", "OPEX"],
        "pages": ["Dashboard",
                  "Master_SKU", "Master_Supplier", "Master_Kategori", "Master_Toko", "Master_Barang_Besar", "Master_Gudang",
                  "Purchase_Dashboard", "Purchase_Input", "Purchase_History",
                  "Opex_Dashboard", "Opex_Input", "Opex_History"],
    },
    "finance": {
        "label": "Finance",
        "desc": "Keuangan - konfirmasi bayar SKU & OPEX, dashboard finance, akuntansi",
        "menus": ["Pembelian", "OPEX", "Finance", "Akuntansi"],
        "pages": ["Purchase_Dashboard", "Purchase_History",
                  "Opex_Dashboard", "Opex_History",
                  "Finance_Dashboard", "Finance_SKU", "Finance_OPEX", "Finance_History",
                  "Rekonsiliasi", "Laba_Rugi_Neraca", "Aset_Modal"],
    },
}

# Role list for dropdown
ROLE_CHOICES = list(ROLES.keys())


def hash_password(password: str) -> str:
    """Hash password with PBKDF2 + SHA256 + random salt."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against the stored hash."""
    try:
        salt, original = stored_hash.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
        return dk.hex() == original
    except (ValueError, AttributeError):
        return False


def authenticate_user(db, username: str, password: str) -> dict | None:
    """Authenticate a user by username & password. Returns user dict or None."""
    user = db.fetch_one(
        "SELECT id, username, nama_lengkap, role, password_hash, active FROM users WHERE username = ?",
        (username.strip().lower(),),
    )
    if not user:
        return None
    if not user["active"]:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    # Update last_login
    db.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))
    return {
        "id": user["id"],
        "username": user["username"],
        "nama_lengkap": user["nama_lengkap"],
        "role": user["role"],
    }


def generate_auth_token(db, user_id: int) -> str:
    """Generate a persistent auth token for the user (valid 7 days)."""
    import secrets
    token = secrets.token_hex(32)  # 64-char hex
    expires_at = datetime.now() + timedelta(days=7)
    # Clean old tokens for this user
    db.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
    # Insert new token
    db.execute(
        "INSERT INTO auth_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at.strftime("%Y-%m-%d %H:%M:%S")),
    )
    return token


def validate_auth_token(db, token: str) -> dict | None:
    """Validate an auth token. Returns user dict or None."""
    row = db.fetch_one(
        """SELECT u.id, u.username, u.nama_lengkap, u.role, u.active
           FROM auth_tokens t
           JOIN users u ON t.user_id = u.id
           WHERE t.token = ? AND t.expires_at > datetime('now', 'localtime')""",
        (token,),
    )
    if not row or not row["active"]:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "nama_lengkap": row["nama_lengkap"],
        "role": row["role"],
    }


def invalidate_auth_token(db, token: str = None, user_id: int = None):
    """Invalidate auth token(s)."""
    if token:
        db.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
    if user_id:
        db.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
    # Also clean expired tokens periodically
    db.execute("DELETE FROM auth_tokens WHERE expires_at <= datetime('now', 'localtime')")


def user_has_access(user_role: str, page: str) -> bool:
    """Check if a role has access to a specific page."""
    role_def = ROLES.get(user_role, {})
    # Admin has access to everything
    if user_role == "admin":
        return True
    # Check explicit page allowlist
    allowed_pages = role_def.get("pages", [])
    if page in allowed_pages:
        return True
    # Check menu-level access
    menu_map = {
        "Operasional": ["Dashboard", "Scan_Operasional", "Gudang_Inventory", "Sales_Input", "Retur_Klaim", "AI_Supervisor",
                        "Handover", "Ekspedisi", "Reports"],
        "Penjualan": ["Sales_Dashboard", "Sales_History", "Sales_Archive"],
        "Pembelian": ["Purchase_Dashboard", "Purchase_Input",
                      "Purchase_History", "Purchase_Archive"],
        "OPEX": ["Opex_Dashboard", "Opex_Input", "Opex_History"],
        "Finance": ["Finance_Dashboard", "Finance_SKU", "Finance_OPEX", "Finance_History", "Laba_Rugi", "Cashflow"],
        "Akuntansi": ["Rekonsiliasi", "Laba_Rugi_Neraca", "Aset_Modal", "Settlement_Harian", "Iklan_Harian"],
        "Master_Data": ["Master_SKU", "Master_Supplier", "Master_Kategori", "Master_Toko", "Master_Barang_Besar", "Master_Gudang"],
        "Admin": ["Admin_Users"],
    }
    allowed_menus = role_def.get("menus", [])
    for menu in allowed_menus:
        if page in menu_map.get(menu, []):
            return True
    return False


def get_user_menus(user_role: str) -> list:
    """Get allowed main menus for a role."""
    role_def = ROLES.get(user_role, {})
    return role_def.get("menus", [])


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

    # ── Auth state ──
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "user" not in st.session_state:
        st.session_state.user = None

    # ── Auto-login from persistent auth token ──
    if not st.session_state.authenticated:
        auth_token = st.query_params.get("auth")
        if not auth_token:
            import re
            try:
                cookie_header = st.context.headers.get("Cookie", "")
                match = re.search(r'(?:^|;\s*)iscan_sid=([^;]+)', cookie_header)
                if match:
                    auth_token = match.group(1)
            except Exception:
                pass
        if auth_token:
            user = validate_auth_token(st.session_state.db, auth_token)
            if user:
                st.session_state.authenticated = True
                st.session_state.user = user
            # No st.rerun() - natural flow handles rendering

    # ── Create default admin (once) ──
    if not st.session_state.get("_db_checked"):
        st.session_state._db_checked = True
        db = st.session_state.db
        user_count = db.fetch_one("SELECT COUNT(*) as cnt FROM users")
        if user_count and user_count["cnt"] == 0:
            db.execute(
                "INSERT INTO users (username, password_hash, nama_lengkap, role) VALUES (?, ?, ?, ?)",
                ("admin", hash_password("admin123"), "Administrator", "admin"),
            )
            logging.info("Default admin user created (admin / admin123)")

    if "selected_store" not in st.session_state:
        st.session_state.selected_store = "Mitra Mulia Abadi"  # default, avoid DB query every rerun
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
    """Get scan statistics - diselaraskan dengan Scan Operasional (PACKED/PENDING/CANCEL)."""
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
            "message": f"✓ {cleaned} -> {ekspedisi} ({status})",
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

    # Clear active scans - revert penjualan status_pesanan terlebih dahulu
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
    """Render statistics cards - diselaraskan dengan Scan Operasional."""
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
                        st.markdown(f"📄 **{f}** - {size_kb:.1f} KB - {mod_time.strftime('%d-%m-%Y %H:%M')}")
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
                st.markdown(f"📄 **{arsip['judul']}** - _{arsip['tanggal']}_")
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
    """Render expedition management page - data dari Scan Operasional."""
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
    - Indonesian: "11.205" (thousands) -> "11205"
    - Indonesian: "1.234,56" -> "1234.56"
    - International: "1,234.56" -> "1234.56"
    - Plain: "11205" -> "11205"
    """
    s = raw.replace("Rp", "").replace("rp", "").replace(" ", "").strip()
    if not s:
        return "0"

    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # Format: 1.234,56 -> Indonesian (dot=thousands, comma=decimal)
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
            # Indonesian decimal: "11205,5" -> "11205.5"
            s = s.replace(",", ".")
        else:
            # International thousands: "1,234" -> "1234"
            s = s.replace(",", "")
    elif has_dot:
        # Only dots: could be "11.205" (thousands) or "11.5" (decimal)
        last_dot = s.rfind(".")
        after_dot = s[last_dot + 1:]
        if len(after_dot) == 3 and after_dot.isdigit() and len(s.replace(".", "")) > 3:
            # Looks like thousands: "11.205" -> "11205"
            s = s.replace(".", "")
        elif len(after_dot) <= 2 and after_dot.isdigit():
            # Decimal: "11.5" -> keep as is
            pass
        else:
            # Ambiguous but likely thousands (e.g., "1.234") -> remove dots
            s = s.replace(".", "")

    return s


def _safe_float(val) -> float:
    """Safely convert a value to float, handling Indonesian number format.

    Also detects pandas auto-conversion: if pandas read '91.250' as 91.25,
    multiplies by 1000 to recover the correct Indonesian thousands value.
    """
    if val is None:
        return 0.0
    try:
        cleaned = _parse_number_str(str(val))
        result = float(cleaned)
        # Heuristic: if result is small (<100k) with decimals, and the original
        # string had 3-digit groups separated by dots, pandas likely mis-parsed.
        # Multiply by 1000 to recover Indonesian thousands format.
        if result < 100000 and result != int(result) and result > 0:
            orig_str = str(val).strip()
            if "." in orig_str:
                # Check if original had 3-digit groups (thousands separator)
                parts = orig_str.split(".")
                if len(parts) >= 2 and all(len(p) <= 3 for p in parts):
                    recovered = result * 1000
                    # Only apply if recovered value makes sense (round number)
                    if abs(recovered - round(recovered)) < 0.001:
                        return round(recovered)
        return result
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
    - If exists -> UPDATE (merge fields, aggregate stock if mode is 'add').
    - If not exists -> INSERT.
    - If stok_mode is 'add' -> ADD incoming stock to existing stock.
    - If update_kosong is True -> only update fields that have non-empty values in Excel.

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
    missing_beli = db.fetch_one("SELECT COUNT(*) as cnt FROM sku WHERE harga_beli IS NULL OR harga_beli = 0")

    col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
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
    with col_s5:
        missing = missing_beli["cnt"] if missing_beli else 0
        st.metric("🚫 Tanpa Harga Modal", missing,
                 delta=f"{missing} SKU perlu di-update" if missing > 0 else None)

    st.markdown("---")

    # ── Alert: SKU tanpa Harga Modal ──
    missing = missing_beli["cnt"] if missing_beli else 0
    if missing > 0:
        total_s = total_sku["cnt"] if total_sku else 1
        pct = (missing / total_s * 100) if total_s > 0 else 0
        st.warning(
            f"🚫 **{missing} SKU ({pct:.0f}%) belum memiliki Harga Modal (Harga Beli)!**\n\n"
            f"SKU tanpa Harga Beli **tidak terhitung di Nilai Inventaris** dan **tidak bisa dihitung laba/rugi-nya**.\n\n"
            f"💡 **Cara update**: Upload massal Excel via fitur **📥 Upload Massal SKU** di bawah - "
            f"cukup kolom Kode SKU + Harga Beli, centang 'Hanya update field yang terisi' agar data lain tidak tertimpa.\n\n"
            f"ℹ️ *Harga Jual diambil otomatis dari data pesanan marketplace (Input Resi & Pesanan), bukan dari SKU.*"
        )

    # ── Upload Massal SKU dari Excel ──
    with st.expander("📥 Upload Massal SKU (Excel - Ipos / ERP MMA)", expanded=False):
        st.markdown("""
        Upload file Excel berisi data SKU untuk diimport secara massal.
        **Upsert:** Jika `Kode SKU` sudah ada -> data diupdate & stok ditambahkan. Jika belum ada -> insert baru.
        """)

        uploaded_file = st.file_uploader(
            "Pilih file Excel (.xlsx / .xls)",
            type=["xlsx", "xls"],
            key="sku_mass_upload",
        )

        if uploaded_file is not None:
            try:
                df_raw = pd.read_excel(uploaded_file, engine="openpyxl", dtype=str)
                # Convert 'nan' strings from empty cells
                for col in df_raw.columns:
                    df_raw[col] = df_raw[col].apply(lambda x: "" if str(x).strip().lower() == "nan" else str(x))
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
                                            f"• **{item['kode']}** - {item['nama']}: "
                                            f"stok {item['stok_sebelum']} -> **{item['stok_sesudah']}** "
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
        stock_filter = st.selectbox("Filter Stok", ["Semua", "Stok Menipis (≤10)", "Stok Habis (0)", "Tersedia (>0)", "⚠️ Tanpa Harga Beli (Modal)"], key="sku_stock_filter")

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
    elif stock_filter == "⚠️ Tanpa Harga Beli (Modal)":
        query += " AND (harga_beli IS NULL OR harga_beli = 0)"

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

        # Color-code missing harga beli
        def color_harga_beli(val):
            if val == "Rp 0" or val == "Rp 0.00":
                return "background-color: #f8d7da; color: #721c24; font-weight: bold"
            return ""

        styled = df_sku[display_cols].style.map(color_stock, subset=["Stok"]).map(color_harga_beli, subset=["Harga Beli"])
        st.dataframe(styled, width="stretch", height=450, hide_index=True)
        st.caption(f"Total: {len(sku_list)} SKU ditampilkan")

    st.markdown("---")

    # ── Edit / Hapus / Tambah Stok per SKU ──
    st.markdown("### ⚙️ Edit / Update Stok SKU")
    sku_options = {f"{r['kode_sku']} - {r['nama_barang']}": r for r in sku_list} if sku_list else {}

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
            with st.expander(f"✏️ Edit: {selected_sku['kode_sku']} - {selected_sku['nama_barang']}", expanded=True):
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
    if "purchase_biaya_operasional" not in st.session_state:
        st.session_state.purchase_biaya_operasional = 0
    if "purchase_biaya_packing" not in st.session_state:
        st.session_state.purchase_biaya_packing = 0

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

    # Load ALL SKU data - supplier only for auto-fill, NOT for filtering
    all_sku = db.fetch_all(
        "SELECT kode_sku, nama_barang, satuan, harga_beli, stok, supplier FROM sku ORDER BY kode_sku"
    )

    if not all_sku:
        st.warning("⚠️ Belum ada data SKU. Tambahkan SKU terlebih dahulu di menu 🏷️ Manajemen SKU.")
    else:
        # Search input: cari by Kode SKU ATAU Nama Barang
        search_term = st.text_input(
            "🔍 Cari SKU (Kode atau Nama Barang) - kosongkan untuk lihat semua",
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
                f"{s['kode_sku']} - {s['nama_barang']} | Stok: {s['stok']} | {s['supplier'] or 'Tanpa Supplier'}": s
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
                    # Check if already in cart (same SKU + same price -> merge qty)
                    existing_idx = None
                    for i, item in enumerate(cart):
                        if item["kode_sku"] == sku_data["kode_sku"] and item["harga_beli"] == harga_manual:
                            existing_idx = i
                            break

                    if existing_idx is not None:
                        cart[existing_idx]["qty"] += qty
                        cart[existing_idx]["total_harga"] = cart[existing_idx]["qty"] * cart[existing_idx]["harga_beli"]
                        st.success(f"Qty {sku_data['kode_sku']} ditambahkan -> {cart[existing_idx]['qty']}")
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

        grand_total_barang = sum(item["total_harga"] for item in cart)
        st.markdown(f"**💵 Total Barang: Rp {grand_total_barang:,.0f}** | **📦 {len(cart)} item**")

        # ── Cart Actions ──
        col_c1, col_c2, col_c3 = st.columns([2, 1, 1])
        with col_c1:
            # Remove item
            remove_idx = st.selectbox(
                "Hapus item dari keranjang",
                [f"{i+1}. {item['kode_sku']} - {item['nama_barang']} (Qty: {item['qty']})" for i, item in enumerate(cart)],
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

    # ── Biaya Tambahan (always visible, outside cart empty check) ──
    st.markdown("---")
    st.markdown("### 💸 Biaya Tambahan")
    col_biaya1, col_biaya2 = st.columns(2)
    with col_biaya1:
        biaya_operasional = st.number_input(
            "🔧 Biaya Operasional Tetap",
            min_value=0, value=st.session_state.purchase_biaya_operasional, step=10000,
            key="purchase_biaya_operasional_input",
            help="Biaya operasional tetap per transaksi (contoh: transport, bongkar muat, dll)",
        )
        st.session_state.purchase_biaya_operasional = biaya_operasional
    with col_biaya2:
        biaya_packing = st.number_input(
            "📦 Biaya Packing",
            min_value=0, value=st.session_state.purchase_biaya_packing, step=5000,
            key="purchase_biaya_packing_input",
            help="Biaya packing / pengemasan per transaksi (contoh: kardus, bubble wrap, lakban, dll)",
        )
        st.session_state.purchase_biaya_packing = biaya_packing

    # ── Grand Total Preview ──
    if cart:
        grand_total_barang = sum(item["total_harga"] for item in cart)
        grand_total = grand_total_barang + biaya_operasional + biaya_packing
        col_gt1, col_gt2, col_gt3 = st.columns(3)
        with col_gt1:
            st.metric("📦 Total Barang", f"Rp {grand_total_barang:,.0f}")
        with col_gt2:
            st.metric("🔧 Biaya Operasional", f"Rp {biaya_operasional:,.0f}" if biaya_operasional else "-")
        with col_gt3:
            st.metric("📦 Biaya Packing", f"Rp {biaya_packing:,.0f}" if biaya_packing else "-")
        st.markdown(f"### 💰 Grand Total: Rp {grand_total:,.0f}")
        if biaya_operasional > 0 or biaya_packing > 0:
            st.caption(f"(Termasuk biaya tambahan: Rp {biaya_operasional + biaya_packing:,.0f})")

    if cart:
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
            # Semua PO baru berstatus PENDING - menunggu konfirmasi Finance
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
                                   qty, satuan, harga_beli, total_harga, keterangan, metode_bayar, status_bayar,
                                   biaya_operasional, biaya_packing)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (faktur.strip(), today_str, supplier,
                                 item["kode_sku"], item["nama_barang"],
                                 item["qty"], item["satuan"], item["harga_beli"],
                                 item["total_harga"], ket_global.strip(),
                                 metode_bayar, status_bayar,
                                 biaya_operasional, biaya_packing),
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
                        with st.expander(f"⚠️ **{len(price_changes)} perubahan Harga Beli terdeteksi** - Klik untuk detail", expanded=True):
                            for pc in price_changes:
                                arah = "📈 NAIK" if pc["selisih"] > 0 else "📉 TURUN"
                                st.markdown(
                                    f"• **{pc['kode']}** - {pc['nama']} | "
                                    f"Harga Lama: Rp {pc['lama']:,.0f} -> Harga Baru: Rp {pc['baru']:,.0f} "
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
                        st.session_state.purchase_biaya_operasional = 0
                        st.session_state.purchase_biaya_packing = 0
                        st.rerun()


def render_purchase_history():
    """Render riwayat transaksi pembelian."""
    db = st.session_state.db

    st.subheader("📋 Riwayat Pembelian")

    # ── Stats ──
    total_trx = db.fetch_one("SELECT COUNT(DISTINCT no_faktur) as cnt FROM pembelian")
    total_items = db.fetch_one("SELECT COUNT(*) as cnt FROM pembelian")
    total_value = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) + COALESCE(SUM(DISTINCT biaya_operasional), 0) + COALESCE(SUM(DISTINCT biaya_packing), 0) as total FROM pembelian"
    )
    total_biaya_ops = db.fetch_one(
        "SELECT COALESCE(SUM(DISTINCT biaya_operasional), 0) as total FROM pembelian"
    )
    total_biaya_pack = db.fetch_one(
        "SELECT COALESCE(SUM(DISTINCT biaya_packing), 0) as total FROM pembelian"
    )
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
        biaya_ops_val = total_biaya_ops["total"] if total_biaya_ops else 0
        biaya_pack_val = total_biaya_pack["total"] if total_biaya_pack else 0
        st.metric("💰 Total Nilai", f"Rp {val:,.0f}",
                  help=f"Termasuk biaya operasional Rp {biaya_ops_val:,.0f} & biaya packing Rp {biaya_pack_val:,.0f}")
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
            "SELECT no_faktur, tanggal, supplier, metode_bayar, status_bayar, "
            "COUNT(*) as items, SUM(total_harga) as total_barang, "
            "MAX(biaya_operasional) as biaya_ops, MAX(biaya_packing) as biaya_pack "
            "FROM pembelian GROUP BY no_faktur ORDER BY created_at DESC",
            params[:len(params)] if params else [],
        )
        if faktur_summary:
            df_faktur = pd.DataFrame([dict(r) for r in faktur_summary])
            # Calculate grand total including biaya
            def calc_grand(row):
                return (row["total_barang"] or 0) + (row["biaya_ops"] or 0) + (row["biaya_pack"] or 0)
            df_faktur["Grand Total"] = df_faktur.apply(calc_grand, axis=1)
            df_faktur = df_faktur.rename(columns={
                "no_faktur": "No Faktur", "tanggal": "Tanggal", "supplier": "Supplier",
                "metode_bayar": "Metode Bayar", "status_bayar": "Status Bayar",
                "items": "Item", "total_barang": "Total Barang",
                "biaya_ops": "Biaya Ops", "biaya_pack": "Biaya Packing",
            })
            df_faktur["Total Barang"] = df_faktur["Total Barang"].apply(lambda x: f"Rp {x:,.0f}")
            df_faktur["Biaya Ops"] = df_faktur["Biaya Ops"].apply(lambda x: f"Rp {x:,.0f}" if x else "-")
            df_faktur["Biaya Packing"] = df_faktur["Biaya Packing"].apply(lambda x: f"Rp {x:,.0f}" if x else "-")
            df_faktur["Grand Total"] = df_faktur["Grand Total"].apply(lambda x: f"Rp {x:,.0f}")
            display_faktur = df_faktur[["No Faktur", "Tanggal", "Supplier", "Metode Bayar", "Status Bayar",
                                         "Item", "Total Barang", "Biaya Ops", "Biaya Packing", "Grand Total"]]
            st.dataframe(display_faktur, width="stretch", hide_index=True)
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
                    # Preserve existing status_bayar - hanya Finance yang bisa mengubah
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
                        st.markdown(f"**{item['kode_sku']}** - {item['nama_barang']} ({item['satuan']})")
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
                        f"{s['kode_sku']} - {s['nama_barang']} | Stok: {s['stok']}": s
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
                                # Get original biaya values to preserve them
                                orig_biaya = db.fetch_one(
                                    "SELECT biaya_operasional, biaya_packing FROM pembelian WHERE no_faktur = ? LIMIT 1",
                                    (no_faktur_revisi,),
                                )
                                orig_biaya_ops = orig_biaya["biaya_operasional"] if orig_biaya else 0
                                orig_biaya_pack = orig_biaya["biaya_packing"] if orig_biaya else 0

                                for item in revisi_cart:
                                    db.execute(
                                        """INSERT INTO pembelian (no_faktur, tanggal, supplier, kode_sku, nama_barang,
                                           qty, satuan, harga_beli, total_harga, keterangan, metode_bayar, status_bayar,
                                           biaya_operasional, biaya_packing)
                                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                        (no_faktur_revisi, current_tanggal, revisi_supplier,
                                         item["kode_sku"], item["nama_barang"],
                                         item["qty"], item["satuan"], item["harga_beli"],
                                         item["total_harga"], revisi_ket.strip(),
                                         revisi_metode, revisi_status,
                                         orig_biaya_ops, orig_biaya_pack),
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
                                        st.caption(f"{arah} {pc['kode']}: Rp {pc['lama']:,.0f} -> Rp {pc['baru']:,.0f}")

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
    """Render halaman Finance - konfirmasi pembayaran PO yang PENDING."""
    db = st.session_state.db

    st.subheader("💳 Finance - Konfirmasi Pembayaran PO")

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
        "SELECT no_faktur, tanggal, supplier, metode_bayar, "
        "COUNT(*) as items, SUM(total_harga) as total_barang, "
        "MAX(biaya_operasional) as biaya_ops, MAX(biaya_packing) as biaya_pack "
        "FROM pembelian WHERE status_bayar = 'PENDING' "
        "GROUP BY no_faktur ORDER BY created_at DESC"
    )

    if not pending_fakturs:
        st.success("✅ Tidak ada PO yang pending. Semua sudah dikonfirmasi.")
    else:
        st.markdown(f"### 📋 {len(pending_fakturs)} PO Menunggu Konfirmasi")

        # ── Tabel PO Pending ──
        # Build pending dataframe with biaya
        df_pending_data = []
        for r in pending_fakturs:
            total_barang = r["total_barang"] or 0
            biaya_ops = r["biaya_ops"] or 0
            biaya_pack = r["biaya_pack"] or 0
            grand_total = total_barang + biaya_ops + biaya_pack
            df_pending_data.append({
                "No Faktur": r["no_faktur"],
                "Tanggal": r["tanggal"],
                "Supplier": r["supplier"],
                "Metode Bayar": r["metode_bayar"],
                "Item": r["items"],
                "Total Barang": f"Rp {total_barang:,.0f}",
                "Biaya Ops": f"Rp {biaya_ops:,.0f}" if biaya_ops else "-",
                "Biaya Packing": f"Rp {biaya_pack:,.0f}" if biaya_pack else "-",
                "Grand Total": f"Rp {grand_total:,.0f}",
                "_grand": grand_total,
            })
        df_pending = pd.DataFrame(df_pending_data)
        df_pending["Pilih"] = False
        st.dataframe(
            df_pending[["No Faktur", "Tanggal", "Supplier", "Metode Bayar", "Item",
                         "Total Barang", "Biaya Ops", "Biaya Packing", "Grand Total"]],
            width="stretch", hide_index=True,
        )

        st.markdown("---")

        # ── Konfirmasi per PO ──
        st.markdown("### ✅ Konfirmasi Pembayaran")

        faktur_options = []
        for r in pending_fakturs:
            total_barang = r["total_barang"] or 0
            biaya_ops = r["biaya_ops"] or 0
            biaya_pack = r["biaya_pack"] or 0
            grand = total_barang + biaya_ops + biaya_pack
            faktur_options.append(
                f"{r['no_faktur']} | {r['tanggal']} | {r['supplier']} | {r['metode_bayar']} | "
                f"{r['items']} item | Barang: Rp {total_barang:,.0f} | Grand: Rp {grand:,.0f}"
            )
        selected_faktur_label = st.selectbox(
            "Pilih PO untuk dikonfirmasi",
            faktur_options,
            key="finance_select_po",
        )
        selected_no_faktur = selected_faktur_label.split(" | ")[0]

        # Show detail items + biaya
        detail_items = db.fetch_all(
            "SELECT kode_sku, nama_barang, qty, satuan, harga_beli, total_harga, "
            "biaya_operasional, biaya_packing FROM pembelian WHERE no_faktur = ?",
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

            # Show biaya breakdown
            biaya_ops_val = detail_items[0]["biaya_operasional"] or 0
            biaya_pack_val = detail_items[0]["biaya_packing"] or 0
            total_barang_val = sum(r["total_harga"] or 0 for r in detail_items)
            grand_val = total_barang_val + biaya_ops_val + biaya_pack_val

            col_b1, col_b2, col_b3, col_b4 = st.columns(4)
            with col_b1:
                st.metric("📦 Total Barang", f"Rp {total_barang_val:,.0f}")
            with col_b2:
                st.metric("🔧 Biaya Operasional", f"Rp {biaya_ops_val:,.0f}" if biaya_ops_val else "-")
            with col_b3:
                st.metric("📦 Biaya Packing", f"Rp {biaya_pack_val:,.0f}" if biaya_pack_val else "-")
            with col_b4:
                st.metric("💰 Grand Total", f"Rp {grand_val:,.0f}")

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
                    st.markdown(f"📄 **{f}** - {size_kb:.1f} KB - {mod_time.strftime('%d-%m-%Y %H:%M')}")
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
            df_raw = pd.read_excel(uploaded_file, engine="openpyxl", dtype=str)
            # Convert 'nan' strings (from empty Excel cells) back to empty strings
            for col in df_raw.columns:
                df_raw[col] = df_raw[col].apply(lambda x: "" if str(x).strip().lower() == "nan" else str(x))
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

                                        # Lazada: setiap baris = 1 qty, UPSERT harus MENAMBAH qty (bukan menimpa)
                                        # Karena Lazada tidak punya kolom Quantity di Excel
                                        if marketplace == "Lazada":
                                            # Ambil qty lama dari database untuk ditambahkan
                                            old_qty_row = db.fetch_one(
                                                "SELECT qty FROM penjualan WHERE id = ?",
                                                (existing["id"],),
                                            )
                                            old_qty = old_qty_row["qty"] if old_qty_row and old_qty_row["qty"] else 0
                                            final_qty = old_qty + 1  # setiap baris Lazada = 1 item
                                            final_total = harga * final_qty
                                        else:
                                            final_qty = qty
                                            final_total = total

                                        db.execute(
                                            """UPDATE penjualan SET no_resi = ?, tanggal_pengiriman = ?,
                                               qty = ?, harga_jual = ?, total_harga = ?,
                                               kurir = ?, status_pesanan = ?, keterangan = ?,
                                               sku_terdeteksi = ?, nama_toko = ?
                                               WHERE id = ?""",
                                            (new_resi, tgl_kirim if tgl_kirim else None,
                                             final_qty, harga, final_total,
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
    """Render upload pesanan dari marketplace - tab terpisah per marketplace."""
    db = st.session_state.db

    st.subheader("📦 Input Resi & No Pesanan (Marketplace)")

    # ── Bulk Cancel Upload (Pembatalan Marketplace) ──
    render_bulk_cancel_upload(db)

    st.markdown("---")

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
    stats_sales = db.fetch_one("SELECT COUNT(*) as rows, COUNT(DISTINCT no_pesanan) as orders, COALESCE(SUM(total_harga), 0) as total FROM penjualan WHERE status_pesanan NOT IN ('RETUR', 'KLAIM_PENDING', 'KLAIM_BERHASIL', 'KLAIM_GAGAL')")
    sku_matched = db.fetch_one("SELECT COUNT(*) as cnt FROM penjualan WHERE sku_terdeteksi != '' AND status_pesanan NOT IN ('RETUR', 'KLAIM_PENDING', 'KLAIM_BERHASIL', 'KLAIM_GAGAL')")

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
    query = "SELECT * FROM penjualan WHERE 1=1 AND status_pesanan NOT IN ('RETUR', 'KLAIM_PENDING', 'KLAIM_BERHASIL', 'KLAIM_GAGAL')"
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
        st.markdown(f"### 📋 {distinct_orders_header} Pesanan ({len(rows)} item) - {rpt_date_str}")

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
                "FROM penjualan WHERE sku_terdeteksi != '' AND status_pesanan NOT IN ('RETUR', 'KLAIM_PENDING', 'KLAIM_BERHASIL', 'KLAIM_GAGAL')" +
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
                "FROM penjualan WHERE 1=1 AND status_pesanan NOT IN ('RETUR', 'KLAIM_PENDING', 'KLAIM_BERHASIL', 'KLAIM_GAGAL')" +
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
                "FROM penjualan WHERE 1=1 AND status_pesanan NOT IN ('RETUR', 'KLAIM_PENDING', 'KLAIM_BERHASIL', 'KLAIM_GAGAL')" +
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
                "FROM penjualan WHERE 1=1 AND status_pesanan NOT IN ('RETUR', 'KLAIM_PENDING', 'KLAIM_BERHASIL', 'KLAIM_GAGAL')" +
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

        # ── Pendapatan Lain: Hasil Klaim (jurnal koreksi) ──
        st.markdown("---")
        st.markdown("### 💰 Pendapatan Lain - Hasil Klaim (Jurnal Koreksi)")

        klaim_params = []
        if mp_filter != "Semua":
            klaim_params.append(mp_filter)
        if toko_filter != "Semua":
            klaim_params.append(toko_filter)

        klaim_income = db.fetch_all(
            "SELECT tanggal, no_resi, no_pesanan, marketplace, nama_toko, sku, nama_produk, "
            "qty, alasan_klaim, nominal_klaim, operator, waktu "
            "FROM retur_klaim WHERE status = 'KLAIM' AND status_klaim = 'BERHASIL' AND nominal_klaim > 0"
            + (" AND marketplace = ?" if mp_filter != "Semua" else "")
            + (" AND nama_toko = ?" if toko_filter != "Semua" else "")
            + (" AND tanggal = ?" if rpt_date_str else "")
            + " ORDER BY id DESC",
            klaim_params if klaim_params else [],
        )

        if klaim_income:
            total_klaim = sum(k["nominal_klaim"] or 0 for k in klaim_income)
            col_k1, col_k2 = st.columns([3, 1])
            with col_k1:
                st.info(
                    f"📋 **{len(klaim_income)} klaim berhasil** - Pendapatan hasil klaim dari marketplace "
                    f"yang sudah disetujui dan dicairkan."
                )
            with col_k2:
                st.metric("💰 Total Hasil Klaim", f"Rp {total_klaim:,.0f}")

            df_klaim = pd.DataFrame([dict(k) for k in klaim_income])
            df_klaim = df_klaim.rename(columns={
                "tanggal": "Tgl Klaim", "no_resi": "No Resi", "no_pesanan": "No Pesanan",
                "marketplace": "MP", "nama_toko": "Toko", "sku": "SKU",
                "nama_produk": "Produk", "qty": "Qty", "alasan_klaim": "Alasan",
                "nominal_klaim": "Nominal", "operator": "Operator", "waktu": "Waktu",
            })
            df_klaim["Nominal"] = df_klaim["Nominal"].apply(lambda x: f"Rp {x:,.0f}")
            display_klaim = [c for c in ["Tgl Klaim", "No Resi", "No Pesanan", "MP", "Toko", "SKU", "Produk", "Qty", "Alasan", "Nominal", "Operator"] if c in df_klaim.columns]
            st.dataframe(df_klaim[display_klaim], width="stretch", height=250, hide_index=True)
        else:
            st.caption("📭 Tidak ada klaim berhasil untuk periode ini.")

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


def render_bulk_cancel_upload(db):
    """Upload & proses pembatalan massal dari marketplace - Bulk CANCEL."""
    with st.expander(
        "📤 **Upload Pembatalan Marketplace** - Bulk CANCEL pesanan yang dibatalkan sistem",
        expanded=False,
    ):
        st.caption(
            "Upload file Excel dari marketplace berisi daftar pesanan yang **dibatalkan oleh sistem** "
            "(Shopee/TikTok/Lazada). Sistem akan otomatis menandai pesanan sebagai CANCEL, "
            "meng-update data penjualan, dan mencatat di riwayat scan - termasuk pesanan **tanpa No Resi**."
        )

        # ── Manual Checker: cek satu No Pesanan tanpa perlu upload ──
        st.markdown("---")
        st.caption("🔍 **Cek Manual**: Ketik No Pesanan untuk melihat apakah ada di database.")
        cek_col1, cek_col2 = st.columns([3, 1])
        with cek_col1:
            cek_input = st.text_input(
                "No Pesanan",
                placeholder="Ketik/copy No Pesanan dari Excel...",
                key="bc_manual_cek",
                label_visibility="collapsed",
            )
        with cek_col2:
            cek_btn = st.button("🔍 Cek Database", key="bc_manual_cek_btn", width="stretch")

        if cek_input and cek_btn:
            cek_clean = str(cek_input).strip().strip("'\"")
            # Try cleaning
            try:
                num_val = float(cek_clean)
                if num_val == int(num_val) and num_val > 100000:
                    cek_clean = str(int(num_val))
            except (ValueError, OverflowError):
                pass
            if cek_clean.endswith(".0") and len(cek_clean) > 4:
                cek_clean = cek_clean[:-2]

            found = False
            strategies_tried = []

            # Strategy 1: exact
            row = db.fetch_one("SELECT * FROM penjualan WHERE no_pesanan = ? LIMIT 1", (cek_clean,))
            strategies_tried.append(("1. Exact match", row is not None))
            if row: found = True

            # Strategy 2: case-insensitive
            if not found:
                row = db.fetch_one("SELECT * FROM penjualan WHERE LOWER(no_pesanan) = LOWER(?) LIMIT 1", (cek_clean,))
                strategies_tried.append(("2. Case-insensitive", row is not None))
                if row: found = True

            # Strategy 3: LIKE %input%
            if not found:
                row = db.fetch_one("SELECT * FROM penjualan WHERE no_pesanan LIKE ? LIMIT 1", (f"%{cek_clean}%",))
                strategies_tried.append(("3. LIKE %input%", row is not None))
                if row: found = True

            # Strategy 4: reversed LIKE
            if not found:
                row = db.fetch_one("SELECT * FROM penjualan WHERE ? LIKE '%' || no_pesanan || '%' LIMIT 1", (cek_clean,))
                strategies_tried.append(("4. Input LIKE %DB%", row is not None))
                if row: found = True

            # Strategy 5: strip prefix
            if not found:
                stripped = re.sub(r'^(INV|ORD|INVOICE|ORDER|#|NO|NOMOR)[\-_\s:]*', '', cek_clean, flags=re.IGNORECASE).strip()
                if stripped and stripped != cek_clean:
                    row = db.fetch_one("SELECT * FROM penjualan WHERE no_pesanan = ? OR no_pesanan LIKE ? LIMIT 1", (stripped, f"%{stripped}%"))
                    strategies_tried.append((f"5. Strip prefix -> '{stripped}'", row is not None))
                    if row: found = True

            # Strategy 6: with .0
            if not found:
                row = db.fetch_one("SELECT * FROM penjualan WHERE no_pesanan = ? LIMIT 1", (cek_clean + ".0",))
                strategies_tried.append((f"6. With '.0' -> '{cek_clean}.0'", row is not None))
                if row: found = True

            # Strategy 7: REPLACE .0 from DB
            if not found:
                row = db.fetch_one("SELECT * FROM penjualan WHERE REPLACE(no_pesanan, '.0', '') = ? LIMIT 1", (cek_clean,))
                strategies_tried.append(("7. DB tanpa .0", row is not None))
                if row: found = True

            # Show results
            if found and row:
                st.success(f"✅ **DITEMUKAN!** - `{cek_clean}`")
                st.json({
                    "No Pesanan (DB)": row["no_pesanan"],
                    "Marketplace": row["marketplace"],
                    "No Resi": row["no_resi"] or "(kosong)",
                    "Produk": row["nama_produk"],
                    "Status": row["status_pesanan"] or "(kosong)",
                    "Toko": row["nama_toko"],
                })
            else:
                st.error(f"❌ **TIDAK DITEMUKAN** - `{cek_clean}` tidak ada di database.")
                # Show all strategies tried
                with st.expander("🔍 Detail strategi yang dicoba"):
                    for name, result in strategies_tried:
                        icon = "✅" if result else "❌"
                        st.caption(f"{icon} {name}")
                st.info(
                    "💡 **Kemungkinan penyebab**:\n"
                    "- No Pesanan belum di-import di tab Shopee/TikTok/Lazada\n"
                    "- Format No Pesanan berbeda (misal: ada spasi, tanda hubung, atau prefix)\n"
                    "- Data pesanan dari marketplace menggunakan ID yang berbeda dengan laporan pembatalan\n"
                    "- Coba copy-paste langsung No Pesanan dari database (lihat contoh di bawah setelah upload file)"
                )

        uploaded_file = st.file_uploader(
            "Upload File Excel Pembatalan (.xlsx / .xls)",
            type=["xlsx", "xls"],
            key="bulk_cancel_file",
            help="Upload file export dari marketplace yang berisi daftar pesanan dibatalkan.",
        )

        if uploaded_file is not None:
            try:
                df_raw = pd.read_excel(uploaded_file, engine="openpyxl", dtype=str)
                # Convert 'nan' strings from empty cells
                for col in df_raw.columns:
                    df_raw[col] = df_raw[col].apply(lambda x: "" if str(x).strip().lower() == "nan" else str(x))
                if df_raw.empty:
                    st.error("File Excel kosong. Silakan pilih file yang berisi data.")
                else:
                    st.success(f"✅ File berhasil dibaca: **{len(df_raw):,} baris**, {len(df_raw.columns)} kolom.")
                    with st.expander("🔍 Lihat nama kolom terdeteksi", expanded=False):
                        st.caption(", ".join(df_raw.columns.astype(str).tolist()))

                    # ── Column detection keywords ──
                    order_keys = [
                        "no_pesanan", "order_id", "id_pesanan", "nomor_pesanan",
                        "order_no", "no_order", "order_number", "pesanan",
                    ]
                    resi_keys = [
                        "no_resi", "resi", "tracking", "tracking_number",
                        "awb", "nomor_resi", "no_awb", "resi_pengiriman",
                    ]
                    status_keys = [
                        "status", "status_pesanan", "order_status", "state",
                        "status_pesanan_akhir", "cancel_status", "status_order",
                        "status_final",
                    ]
                    ket_keys = [
                        "keterangan", "ket", "notes", "remark", "catatan",
                        "alasan_pembatalan", "cancel_reason", "reason",
                        "alasan", "description",
                    ]
                    mp_keys = [
                        "marketplace", "mp", "platform", "channel", "source",
                    ]

                    excel_cols = [""] + df_raw.columns.tolist()

                    # ── Database Sample (bantu debugging format) ──
                    with st.expander("🔍 Lihat Contoh No Pesanan di Database", expanded=False):
                        sample_db = db.fetch_all(
                            "SELECT DISTINCT marketplace, no_pesanan FROM penjualan "
                            "WHERE no_pesanan != '' ORDER BY marketplace, no_pesanan LIMIT 10"
                        )
                        if sample_db:
                            st.caption("Berikut adalah format No Pesanan yang tersimpan di database:")
                            df_db_sample = pd.DataFrame([dict(r) for r in sample_db])
                            df_db_sample = df_db_sample.rename(columns={
                                "marketplace": "Marketplace",
                                "no_pesanan": "No Pesanan (format di DB)",
                            })
                            st.dataframe(df_db_sample, width="stretch", hide_index=True)
                            st.info(
                                "💡 **Bandingkan** format No Pesanan di Excel Anda dengan yang ada di database. "
                                "Jika formatnya berbeda (misal ada spasi, tanda hubung, prefix INV, atau akhiran .0), "
                                "sistem akan kesulitan mencocokkan. Gunakan fitur mapping kolom dengan benar."
                            )
                        else:
                            st.caption("⚠️ Database masih kosong. Import data pesanan terlebih dahulu.")

                    # ── Column Mapping ──
                    st.markdown("#### 🔗 Mapping Kolom")
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        map_order = st.selectbox(
                            "No Pesanan *",
                            excel_cols,
                            key="bc_map_order",
                            index=_auto_detect_sales_column(excel_cols, order_keys),
                            help="Kolom yang berisi nomor pesanan / order ID. WAJIB diisi.",
                        )
                        map_resi = st.selectbox(
                            "No Resi (opsional)",
                            excel_cols,
                            key="bc_map_resi",
                            index=_auto_detect_sales_column(excel_cols, resi_keys),
                            help="Kolom No Resi - jika kosong, sistem tetap akan memproses pembatalan.",
                        )
                        map_status = st.selectbox(
                            "Status Pesanan (opsional)",
                            excel_cols,
                            key="bc_map_status",
                            index=_auto_detect_sales_column(excel_cols, status_keys),
                            help="Jika ada kolom status, sistem bisa memfilter hanya yang dibatalkan.",
                        )
                    with col_m2:
                        map_ket = st.selectbox(
                            "Keterangan / Alasan Batal (opsional)",
                            excel_cols,
                            key="bc_map_ket",
                            index=_auto_detect_sales_column(excel_cols, ket_keys),
                            help="Alasan pembatalan - akan disimpan di keterangan.",
                        )
                        map_mp = st.selectbox(
                            "Marketplace (opsional)",
                            excel_cols,
                            key="bc_map_mp",
                            index=_auto_detect_sales_column(excel_cols, mp_keys),
                            help="Jika ada, pencarian pesanan lebih akurat.",
                        )

                    # ── Filter Options ──
                    filter_col1, filter_col2 = st.columns(2)
                    with filter_col1:
                        filter_by_status = st.checkbox(
                            "🔍 Filter: hanya proses baris dengan status pembatalan",
                            value=True,
                            key="bc_filter_status",
                            help="Hanya baris yang statusnya mengandung kata 'cancel', 'batal', 'gagal', atau 'return' yang akan diproses.",
                        )
                    with filter_col2:
                        if map_status and filter_by_status:
                            try:
                                status_values = df_raw[map_status].dropna().astype(str).unique().tolist()
                                unik = list(dict.fromkeys(status_values))[:8]
                                st.caption(f"Status terdeteksi: {', '.join(unik)}")
                            except Exception:
                                pass

                    # ── Preview ──
                    if map_order:
                        st.markdown("#### 👁️ Preview Data yang Akan Diproses")
                        preview_cols = [c for c in [map_order, map_resi, map_status, map_ket, map_mp] if c]
                        preview_df = df_raw[preview_cols].head(30).copy()

                        cancel_keywords = [
                            "cancel", "cancelled", "dibatalkan", "batal",
                            "pembatalan", "gagal", "failed", "return", "retur",
                        ]

                        if filter_by_status and map_status:
                            mask = preview_df[map_status].astype(str).str.lower().apply(
                                lambda x: any(kw in x for kw in cancel_keywords)
                            )
                            preview_df = preview_df[mask]

                        st.dataframe(preview_df, width="stretch", hide_index=True)
                        if len(df_raw) > 30:
                            st.caption(f"... dan {len(df_raw) - 30:,} baris lainnya.")

                        # ── Count ──
                        total_rows = len(df_raw)
                        cancel_rows = total_rows
                        if filter_by_status and map_status:
                            mask_all = df_raw[map_status].astype(str).str.lower().apply(
                                lambda x: any(kw in x for kw in cancel_keywords)
                            )
                            cancel_rows = int(mask_all.sum())

                        st.info(
                            f"📊 **{cancel_rows:,}** dari **{total_rows:,}** baris "
                            f"akan diproses sebagai pembatalan."
                        )

                    # ── Execute ──
                    st.markdown("---")
                    exec_col1, exec_col2 = st.columns([2, 1])
                    with exec_col1:
                        if st.button(
                            "🚀 **Proses Bulk CANCEL Sekarang**",
                            type="primary",
                            key="bc_execute",
                            use_container_width=True,
                        ):
                            if not map_order:
                                st.error("❌ Kolom **No Pesanan** wajib di-mapping!")
                            else:
                                cancelled_count = 0
                                already_cancelled = 0
                                not_found = 0
                                skipped = 0
                                tanpa_resi_cancelled = 0
                                errors = 0
                                error_details = []
                                not_found_details = []  # track sample not-found for debugging

                                cancel_keywords = [
                                    "cancel", "cancelled", "dibatalkan", "batal",
                                    "pembatalan", "gagal", "failed", "return", "retur",
                                ]

                                progress_bar = st.progress(0, text="⏳ Memproses pembatalan...")
                                status_text = st.empty()

                                for idx, row in df_raw.iterrows():
                                    try:
                                        # Update progress periodically
                                        if (idx + 1) % 50 == 0:
                                            pct = min((idx + 1) / len(df_raw), 1.0)
                                            progress_bar.progress(pct, text=f"⏳ Memproses... {cancelled_count} dibatalkan, {not_found} tidak ditemukan")

                                        no_pesanan = _safe_str(row.get(map_order))
                                        if not no_pesanan:
                                            skipped += 1
                                            continue

                                        # Clean order ID: fix Excel float formatting (5769123456789012.0 -> 5769123456789012)
                                        # Also strip common prefixes/suffixes
                                        original_no_pesanan = no_pesanan
                                        no_pesanan = str(no_pesanan).strip()
                                        # Fix scientific notation from Excel (e.g. 5.76912E+15)
                                        try:
                                            num_val = float(no_pesanan)
                                            if num_val == int(num_val) and num_val > 100000:
                                                no_pesanan = str(int(num_val))
                                        except (ValueError, OverflowError):
                                            pass
                                        # Strip trailing .0 from float-as-string
                                        if no_pesanan.endswith(".0") and len(no_pesanan) > 4:
                                            no_pesanan = no_pesanan[:-2]
                                        # Strip Excel auto-format quotes/spaces
                                        no_pesanan = no_pesanan.strip().strip("'\"")
                                        if not no_pesanan:
                                            no_pesanan = original_no_pesanan

                                        # Filter by status if enabled
                                        if filter_by_status and map_status:
                                            row_status = str(row.get(map_status, "")).lower()
                                            if not any(kw in row_status for kw in cancel_keywords):
                                                skipped += 1
                                                continue

                                        no_resi = _safe_str(row.get(map_resi)) if map_resi else ""
                                        keterangan = _safe_str(row.get(map_ket)) if map_ket else ""
                                        marketplace = _safe_str(row.get(map_mp)) if map_mp else ""

                                        # Find in penjualan - multi-strategy matching
                                        existing = None

                                        # Strategy 1: Exact match (no_pesanan + marketplace)
                                        if marketplace:
                                            existing = db.fetch_one(
                                                "SELECT id, no_resi, status_pesanan, no_pesanan FROM penjualan "
                                                "WHERE no_pesanan = ? AND marketplace = ? LIMIT 1",
                                                (no_pesanan, marketplace),
                                            )

                                        # Strategy 2: Exact match (no_pesanan only, any marketplace)
                                        if not existing:
                                            existing = db.fetch_one(
                                                "SELECT id, no_resi, status_pesanan, no_pesanan, marketplace FROM penjualan "
                                                "WHERE no_pesanan = ? LIMIT 1",
                                                (no_pesanan,),
                                            )

                                        # Strategy 3: Case-insensitive match
                                        if not existing:
                                            existing = db.fetch_one(
                                                "SELECT id, no_resi, status_pesanan, no_pesanan, marketplace FROM penjualan "
                                                "WHERE LOWER(no_pesanan) = LOWER(?) LIMIT 1",
                                                (no_pesanan,),
                                            )

                                        # Strategy 4: LIKE substring (pesanan contains input)
                                        if not existing:
                                            existing = db.fetch_one(
                                                "SELECT id, no_resi, status_pesanan, no_pesanan, marketplace FROM penjualan "
                                                "WHERE no_pesanan LIKE ? LIMIT 1",
                                                (f"%{no_pesanan}%",),
                                            )

                                        # Strategy 5: LIKE substring reversed (input contains pesanan)
                                        if not existing:
                                            existing = db.fetch_one(
                                                "SELECT id, no_resi, status_pesanan, no_pesanan, marketplace FROM penjualan "
                                                "WHERE ? LIKE '%' || no_pesanan || '%' LIMIT 1",
                                                (no_pesanan,),
                                            )

                                        # Strategy 6: Strip common prefixes (INV, ORD, #, etc.) and retry
                                        if not existing:
                                            stripped = re.sub(r'^(INV|ORD|INVOICE|ORDER|#|NO|NOMOR)[\-_\s:]*', '', no_pesanan, flags=re.IGNORECASE).strip()
                                            if stripped and stripped != no_pesanan:
                                                existing = db.fetch_one(
                                                    "SELECT id, no_resi, status_pesanan, no_pesanan, marketplace FROM penjualan "
                                                    "WHERE no_pesanan = ? OR no_pesanan LIKE ? LIMIT 1",
                                                    (stripped, f"%{stripped}%"),
                                                )

                                        # Strategy 7: Match by no_resi (if Excel has resi column)
                                        if not existing and no_resi:
                                            existing = db.fetch_one(
                                                "SELECT id, no_resi, status_pesanan, no_pesanan, marketplace FROM penjualan "
                                                "WHERE no_resi = ? LIMIT 1",
                                                (no_resi,),
                                            )

                                        # Strategy 8: Try with ".0" appended (DB might store float-format IDs)
                                        if not existing:
                                            existing = db.fetch_one(
                                                "SELECT id, no_resi, status_pesanan, no_pesanan, marketplace FROM penjualan "
                                                "WHERE no_pesanan = ? LIMIT 1",
                                                (no_pesanan + ".0",),
                                            )

                                        # Strategy 9: Try stripping ".0" from DB values via LIKE
                                        if not existing and no_pesanan:
                                            existing = db.fetch_one(
                                                "SELECT id, no_resi, status_pesanan, no_pesanan, marketplace FROM penjualan "
                                                "WHERE REPLACE(no_pesanan, '.0', '') = ? LIMIT 1",
                                                (no_pesanan,),
                                            )

                                        if not existing:
                                            not_found += 1
                                            if len(not_found_details) < 50:
                                                not_found_details.append({
                                                    "no_pesanan": no_pesanan[:60],
                                                    "no_pesanan_raw": original_no_pesanan[:60] if original_no_pesanan != no_pesanan else "",
                                                    "no_resi": no_resi[:40] if no_resi else "-",
                                                    "marketplace": marketplace or "-",
                                                })
                                            continue

                                        # Skip if already cancelled
                                        if existing["status_pesanan"] == "CANCEL":
                                            already_cancelled += 1
                                            continue

                                        # Determine the resi to use in scan_aktif
                                        penj_resi = existing["no_resi"] or ""

                                        # Build cancel keterangan
                                        cancel_ket = keterangan if keterangan else "Dibatalkan oleh sistem marketplace"
                                        if marketplace:
                                            cancel_ket = f"[{marketplace}] {cancel_ket}"

                                        # Update penjualan - set CANCEL + zero out financials
                                        db.execute(
                                            "UPDATE penjualan SET status_pesanan = 'CANCEL', "
                                            "qty = 0, total_harga = 0, harga_jual = 0, "
                                            "keterangan = ? WHERE id = ?",
                                            (cancel_ket, existing["id"]),
                                        )

                                        # Insert into scan_aktif
                                        now = datetime.now()
                                        waktu = now.strftime("%H:%M:%S")
                                        tanggal = now.strftime("%d-%m-%Y")

                                        if penj_resi:
                                            # Has resi - insert with resi
                                            dup = db.fetch_one(
                                                "SELECT id FROM scan_aktif WHERE resi = ?",
                                                (penj_resi,),
                                            )
                                            if not dup:
                                                db.execute(
                                                    "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, "
                                                    "status, kategori, keterangan_barang, tipe_kiriman, marketplace) "
                                                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                                    (waktu, tanggal, penj_resi, "CANCEL", "",
                                                     "CANCEL", "REGULER", "", "REGULER",
                                                     existing.get("marketplace", marketplace)),
                                                )
                                        else:
                                            # No resi - still insert cancel using no_pesanan as identifier
                                            tanpa_resi_cancelled += 1
                                            dup = db.fetch_one(
                                                "SELECT id FROM scan_aktif WHERE resi = ?",
                                                (no_pesanan,),
                                            )
                                            if not dup:
                                                db.execute(
                                                    "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, "
                                                    "status, kategori, keterangan_barang, tipe_kiriman, marketplace) "
                                                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                                    (waktu, tanggal, no_pesanan, "CANCEL", "",
                                                     "CANCEL", "REGULER", "", "REGULER",
                                                     existing.get("marketplace", marketplace)),
                                                )

                                        cancelled_count += 1

                                    except Exception as e:
                                        errors += 1
                                        error_details.append(
                                            f"Baris {idx + 2}: {str(e)[:120]}"
                                        )

                                progress_bar.progress(1.0, text="✅ Selesai!")
                                status_text.success("✅ Pemrosesan bulk CANCEL selesai.")

                                # ── Summary ──
                                st.markdown("### 📊 Hasil Bulk CANCEL")
                                col_r1, col_r2, col_r3, col_r4, col_r5, col_r6 = st.columns(6)
                                with col_r1:
                                    st.metric("✅ Berhasil Cancel", cancelled_count)
                                with col_r2:
                                    st.metric("📭 Tanpa Resi (Cancel)", tanpa_resi_cancelled,
                                             help="Pesanan tanpa No Resi yang berhasil dibatalkan.")
                                with col_r3:
                                    st.metric("⚠️ Sudah Cancel", already_cancelled,
                                             help="Pesanan yang statusnya sudah CANCEL sebelumnya.")
                                with col_r4:
                                    st.metric("❓ Tidak Ditemukan", not_found,
                                             help="No Pesanan tidak ditemukan di database penjualan.")
                                with col_r5:
                                    st.metric("⏭️ Dilewati", skipped,
                                             help="Baris yang dilewati (tidak memenuhi filter status).")
                                with col_r6:
                                    st.metric("🚫 Error", errors)

                                if error_details:
                                    with st.expander(f"⚠️ {len(error_details)} error detail"):
                                        for e in error_details[:30]:
                                            st.caption(f"• {e}")
                                        if len(error_details) > 30:
                                            st.caption(f"... dan {len(error_details) - 30} error lainnya.")

                                if not_found_details:
                                    with st.expander(f"🔍 {len(not_found_details)} No Pesanan Tidak Ditemukan - Lihat sampel"):
                                        st.caption("Berikut adalah sampel No Pesanan yang tidak cocok dengan database:")
                                        df_nf = pd.DataFrame(not_found_details[:30])
                                        # Determine which columns to show
                                        nf_cols = {
                                            "no_pesanan": "No Pesanan (setelah dibersihkan)",
                                            "no_pesanan_raw": "No Pesanan (mentah dari Excel)",
                                            "no_resi": "No Resi (dari Excel)",
                                            "marketplace": "Marketplace",
                                        }
                                        df_nf = df_nf.rename(columns=nf_cols)
                                        # Only show columns that have data
                                        show_cols = ["No Pesanan (setelah dibersihkan)", "Marketplace"]
                                        if df_nf["No Pesanan (mentah dari Excel)"].astype(str).str.strip().replace("", pd.NA).notna().any():
                                            show_cols.insert(1, "No Pesanan (mentah dari Excel)")
                                        if df_nf["No Resi (dari Excel)"].astype(str).str.strip().replace("-", pd.NA).notna().any():
                                            show_cols.append("No Resi (dari Excel)")
                                        df_nf = df_nf[[c for c in show_cols if c in df_nf.columns]]
                                        st.dataframe(df_nf, width="stretch", hide_index=True)
                                        st.info(
                                            "💡 **Tips mengatasi**:\n"
                                            "- Gunakan **🔍 Cek Manual** di atas untuk test satu per satu No Pesanan yang gagal\n"
                                            "- Pastikan kolom **No Pesanan** sudah di-mapping dengan benar\n"
                                            "- Coba upload ulang tanpa filter status (uncheck 🔍 Filter)\n"
                                            "- Cek apakah data pesanan sudah di-import di tab Shopee/TikTok/Lazada\n"
                                            "- Bandingkan dengan contoh No Pesanan di database (expandable di atas)"
                                        )

                                # ── Result message ──
                                msg_parts = []
                                if cancelled_count > 0:
                                    msg_parts.append(
                                        f"**{cancelled_count}** pesanan berhasil dibatalkan"
                                    )
                                    if tanpa_resi_cancelled > 0:
                                        msg_parts.append(
                                            f"(termasuk **{tanpa_resi_cancelled}** pesanan tanpa No Resi)"
                                        )
                                if already_cancelled > 0:
                                    msg_parts.append(
                                        f"**{already_cancelled}** sudah cancel sebelumnya"
                                    )
                                if not_found > 0:
                                    msg_parts.append(
                                        f"**{not_found}** tidak ditemukan di database"
                                    )

                                if cancelled_count > 0:
                                    st.success(f"✅ Bulk CANCEL selesai! {' | '.join(msg_parts)}.")
                                    st.info(
                                        "💡 **Tip**: Data sudah terupdate. Statistik di halaman ini akan "
                                        "berubah setelah refresh. Silakan klik tombol Refresh di bawah."
                                    )
                                    if st.button("🔄 Refresh Halaman", width="stretch", key="bc_refresh"):
                                        st.rerun()
                                else:
                                    st.warning(
                                        f"⚠️ Tidak ada pesanan baru yang dibatalkan. {' | '.join(msg_parts)}.\n\n"
                                        "Pastikan file Excel berisi No Pesanan yang valid dan belum di-cancel."
                                    )
                    with exec_col2:
                        st.caption(
                            "💡 **Tips**:\n"
                            "- File bisa dari Shopee, TikTok, atau Lazada\n"
                            "- Sistem membaca No Pesanan untuk mencocokkan\n"
                            "- Pesanan **tanpa No Resi** tetap bisa dibatalkan\n"
                            "- Data otomatis terupdate di halaman ini\n"
                            "- Refresh halaman setelah selesai"
                        )

            except Exception as e:
                st.error(f"❌ Gagal membaca file Excel: {str(e)}")
                st.caption(
                    "Pastikan file berformat .xlsx atau .xls dan tidak sedang dibuka di aplikasi lain."
                )


def render_retur_klaim():
    """Retur & Klaim - scan paket retur dari kurir, tentukan diterima atau klaim."""
    db = st.session_state.db

    st.subheader("🔄 Retur & Klaim - Proses Paket Kembalian")
    st.caption(
        "Scan No Resi atau No Pesanan saat kurir mengembalikan paket. "
        "Tentukan apakah retur **Diterima** atau masuk proses **Klaim**."
    )

    # ── Stats Cards ──
    total_retur = db.fetch_one("SELECT COUNT(*) as cnt FROM retur_klaim")
    diterima = db.fetch_one("SELECT COUNT(*) as cnt FROM retur_klaim WHERE status = 'DITERIMA'")
    klaim = db.fetch_one("SELECT COUNT(*) as cnt FROM retur_klaim WHERE status = 'KLAIM'")
    klaim_berhasil = db.fetch_one("SELECT COUNT(*) as cnt FROM retur_klaim WHERE status = 'KLAIM' AND status_klaim = 'BERHASIL'")
    total_nominal = db.fetch_one("SELECT COALESCE(SUM(nominal_klaim), 0) as total FROM retur_klaim WHERE status = 'KLAIM' AND status_klaim = 'BERHASIL'")
    today_retur = db.fetch_one(
        "SELECT COUNT(*) as cnt FROM retur_klaim WHERE tanggal = ?",
        (datetime.now().strftime("%d-%m-%Y"),),
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("📦 Total Retur", f"{total_retur['cnt']:,}" if total_retur else "0")
    with col2:
        st.metric("✅ Diterima", f"{diterima['cnt']:,}" if diterima else "0")
    with col3:
        st.metric("⚠️ Klaim", f"{klaim['cnt']:,}" if klaim else "0")
    with col4:
        st.metric("💰 Klaim Berhasil", f"{klaim_berhasil['cnt']:,}" if klaim_berhasil else "0",
                 help=f"Total nominal klaim berhasil: Rp {total_nominal['total']:,.0f}" if total_nominal and total_nominal["total"] > 0 else "")
    with col5:
        st.metric("📅 Hari Ini", f"{today_retur['cnt']:,}" if today_retur else "0")

    st.markdown("---")

    # ── Scan Input ──
    st.markdown("### 🔍 Scan Paket Retur")
    scan_col1, scan_col2 = st.columns([3, 1])
    with scan_col1:
        retur_input = st.text_input(
            "Scan barcode atau ketik No Resi / No Pesanan",
            placeholder="Scan atau ketik No Resi / No Pesanan dari paket retur...",
            key="retur_scan_input",
            label_visibility="collapsed",
        )
    with scan_col2:
        scan_btn = st.button("🔍 Cari", width="stretch", type="primary", key="retur_scan_btn")

    if retur_input or scan_btn:
        search_term = retur_input.strip() if retur_input else ""
        if search_term:
            cleaned = Validator.sanitize_resi(search_term) or search_term.strip()

            # ── Search in penjualan by resi OR no_pesanan ──
            match = db.fetch_one(
                "SELECT no_resi, no_pesanan, marketplace, nama_produk, sku_terdeteksi, "
                "nama_toko, kurir, qty, harga_jual, total_harga, status_pesanan "
                "FROM penjualan WHERE (no_resi = ? OR no_pesanan = ?) LIMIT 1",
                (cleaned, cleaned),
            )

            # ── Also check scan_aktif for additional context ──
            scan_info = db.fetch_one(
                "SELECT status, toko, waktu, tanggal FROM scan_aktif WHERE resi = ? OR resi = ? LIMIT 1",
                (cleaned, cleaned),
            )

            if not match and not scan_info:
                st.warning(f"⚠️ `{cleaned}` tidak ditemukan di database penjualan maupun scan.")
            else:
                st.success(f"✅ Data ditemukan untuk `{cleaned}`")

                if match:
                    st.markdown("#### 📋 Detail Pesanan")
                    detail_col1, detail_col2, detail_col3 = st.columns(3)
                    with detail_col1:
                        st.markdown(f"**Marketplace:** {match['marketplace']}")
                        st.markdown(f"**No Pesanan:** `{match['no_pesanan']}`")
                        st.markdown(f"**No Resi:** `{match['no_resi'] or '-'}`")
                        st.markdown(f"**Kurir:** {match['kurir'] or '-'}")
                    with detail_col2:
                        st.markdown(f"**Toko:** {match['nama_toko'] or '-'}")
                        st.markdown(f"**SKU:** `{match['sku_terdeteksi'] or '?'}`")
                        st.markdown(f"**Produk:** {match['nama_produk'][:60] if match['nama_produk'] else '-'}")
                        st.markdown(f"**Qty:** {match['qty']}")
                    with detail_col3:
                        st.markdown(f"**Harga:** Rp {match['harga_jual']:,.0f}" if match['harga_jual'] else "**Harga:** -")
                        st.markdown(f"**Total:** Rp {match['total_harga']:,.0f}" if match['total_harga'] else "**Total:** -")
                        st.markdown(f"**Status Pesanan:** {match['status_pesanan'] or '-'}")

                if scan_info:
                    st.markdown("#### 📋 Info Scan Sebelumnya")
                    st.info(
                        f"Status scan: **{scan_info['status']}** | "
                        f"Toko: **{scan_info['toko']}** | "
                        f"Waktu: {scan_info['waktu']} | Tanggal: {scan_info['tanggal']}"
                    )

                # ── Check if already processed ──
                already_processed = db.fetch_one(
                    "SELECT id, status, alasan_klaim, keterangan, waktu, tanggal FROM retur_klaim "
                    "WHERE no_resi = ? OR no_pesanan = ? ORDER BY id DESC LIMIT 1",
                    (cleaned, cleaned),
                )

                if already_processed:
                    status_label = "✅ DITERIMA" if already_processed["status"] == "DITERIMA" else "⚠️ KLAIM"
                    st.warning(
                        f"⚠️ Paket ini **sudah diproses** sebelumnya:\n"
                        f"• Status: **{status_label}**\n"
                        f"• Alasan: {already_processed['alasan_klaim'] or '-'}\n"
                        f"• Waktu: {already_processed['waktu']} | Tanggal: {already_processed['tanggal']}"
                    )

                # ── Action Buttons ──
                st.markdown("---")
                st.markdown("### ⚡ Tentukan Status Retur")

                act_col1, act_col2, act_col3 = st.columns([1, 1, 2])
                with act_col1:
                    btn_diterima = st.button(
                        "✅ **DITERIMA**",
                        width="stretch",
                        type="primary",
                        key="retur_btn_diterima",
                        help="Retur diterima - barang kembali ke stok",
                    )
                with act_col2:
                    btn_klaim = st.button(
                        "⚠️ **KLAIM**",
                        width="stretch",
                        type="secondary",
                        key="retur_btn_klaim",
                        help="Retur masuk klaim - perlu investigasi",
                    )

                # ── Klaim reason ──
                if btn_klaim or st.session_state.get("retur_show_klaim_form", False):
                    st.session_state.retur_show_klaim_form = True
                    st.markdown("#### ⚠️ Alasan Klaim")
                    alasan_options = [
                        "Barang Rusak / Cacat",
                        "Barang Tidak Sesuai Pesanan",
                        "Barang Hilang Sebagian",
                        "Kemasan Rusak / Bocor",
                        "Jumlah Tidak Sesuai",
                        "Salah Kirim (Toko Lain)",
                        "Pembeli Tidak Mengakui",
                        "Lainnya...",
                    ]
                    klaim_col1, klaim_col2 = st.columns([2, 2])
                    with klaim_col1:
                        alasan_klaim = st.selectbox(
                            "Pilih Alasan Klaim",
                            alasan_options,
                            key="retur_alasan_klaim",
                        )
                    with klaim_col2:
                        if alasan_klaim == "Lainnya...":
                            alasan_lain = st.text_input(
                                "Tulis alasan lain",
                                placeholder="Jelaskan alasan klaim...",
                                key="retur_alasan_lain",
                            )
                        else:
                            alasan_lain = ""

                    ket_klaim = st.text_area(
                        "Keterangan Tambahan",
                        placeholder="Detail tambahan tentang klaim (opsional)...",
                        key="retur_ket_klaim",
                        height=68,
                    )

                    final_alasan = alasan_lain if alasan_klaim == "Lainnya..." and alasan_lain else alasan_klaim

                    # ── Nominal Klaim input ──
                    st.markdown("#### 💰 Hasil Klaim")
                    nominal_col1, nominal_col2 = st.columns(2)
                    with nominal_col1:
                        nominal_klaim = st.number_input(
                            "Nominal Hasil Klaim (Rp)",
                            min_value=0,
                            value=int(match["total_harga"]) if match and match["total_harga"] else 0,
                            step=1000,
                            key="retur_nominal_klaim",
                            help="Jumlah uang yang berhasil diklaim dari marketplace.",
                        )
                    with nominal_col2:
                        status_klaim_select = st.selectbox(
                            "Status Klaim",
                            ["PENDING", "BERHASIL", "GAGAL"],
                            key="retur_status_klaim_select",
                            help="PENDING = masih proses | BERHASIL = klaim disetujui | GAGAL = klaim ditolak",
                        )

                    if st.button("⚠️ **Konfirmasi KLAIM**", width="stretch", type="primary", key="retur_confirm_klaim"):
                        now = datetime.now()
                        waktu = now.strftime("%H:%M:%S")
                        tanggal = now.strftime("%d-%m-%Y")
                        operator_name = st.session_state.get("user", {}).get("nama_lengkap", "Operator")

                        db.execute(
                            "INSERT INTO retur_klaim (no_resi, no_pesanan, marketplace, nama_toko, sku, "
                            "nama_produk, qty, status, alasan_klaim, keterangan, kurir, operator, "
                            "waktu, tanggal, nominal_klaim, status_klaim) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                match["no_resi"] if match else cleaned,
                                match["no_pesanan"] if match else cleaned,
                                match["marketplace"] if match else "",
                                match["nama_toko"] if match else "",
                                match["sku_terdeteksi"] if match else "",
                                match["nama_produk"] if match else "",
                                match["qty"] if match else 1,
                                "KLAIM",
                                final_alasan,
                                ket_klaim if ket_klaim else "",
                                match["kurir"] if match else "",
                                operator_name,
                                waktu, tanggal,
                                nominal_klaim,
                                status_klaim_select,
                            ),
                        )

                        # ── Update penjualan: jika klaim BERHASIL -> catat sebagai pendapatan hasil klaim ──
                        if status_klaim_select == "BERHASIL" and match and nominal_klaim > 0:
                            db.execute(
                                "UPDATE penjualan SET status_pesanan = 'KLAIM_BERHASIL', "
                                "keterangan = ? WHERE id = ?",
                                (f"Klaim disetujui: Rp {nominal_klaim:,.0f} - {final_alasan}", match["id"] if "id" in match.keys() else None),
                            )
                            # Insert ke scan_aktif sebagai catatan klaim
                            dup = db.fetch_one("SELECT id FROM scan_aktif WHERE resi = ? AND status = 'KLAIM'",
                                               (match["no_resi"] if match["no_resi"] else cleaned,))
                            if not dup:
                                db.execute(
                                    "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, "
                                    "status, kategori, keterangan_barang, tipe_kiriman, marketplace) "
                                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    (waktu, tanggal,
                                     match["no_resi"] if match else cleaned,
                                     match["kurir"] if match else "KLAIM",
                                     match["nama_toko"] if match else "",
                                     "KLAIM", "REGULER", f"Hasil Klaim Rp {nominal_klaim:,.0f}", "REGULER",
                                     match["marketplace"] if match else ""),
                                )
                            st.success(
                                f"💰 **KLAIM BERHASIL!** `{cleaned}` - "
                                f"Pendapatan klaim: **Rp {nominal_klaim:,.0f}** tercatat di penjualan."
                            )
                        elif status_klaim_select == "GAGAL":
                            if match:
                                db.execute(
                                    "UPDATE penjualan SET status_pesanan = 'KLAIM_GAGAL', "
                                    "keterangan = ? WHERE no_pesanan = ? OR no_resi = ?",
                                    (f"Klaim gagal: {final_alasan}",
                                     match["no_pesanan"], match["no_resi"]),
                                )
                            st.warning(f"❌ Klaim GAGAL untuk `{cleaned}` - kerugian tidak tertagih.")
                        else:
                            if match:
                                db.execute(
                                    "UPDATE penjualan SET status_pesanan = 'KLAIM_PENDING', "
                                    "keterangan = ? WHERE no_pesanan = ? OR no_resi = ?",
                                    (f"Klaim diproses: {final_alasan}",
                                     match["no_pesanan"], match["no_resi"]),
                                )
                            st.info(f"⏳ Klaim PENDING untuk `{cleaned}` - menunggu hasil.")

                        st.session_state.retur_show_klaim_form = False
                        st.rerun()

                if btn_diterima:
                    now = datetime.now()
                    waktu = now.strftime("%H:%M:%S")
                    tanggal = now.strftime("%d-%m-%Y")
                    operator_name = st.session_state.get("user", {}).get("nama_lengkap", "Operator")

                    db.execute(
                        "INSERT INTO retur_klaim (no_resi, no_pesanan, marketplace, nama_toko, sku, "
                        "nama_produk, qty, status, alasan_klaim, keterangan, kurir, operator, "
                        "waktu, tanggal) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            match["no_resi"] if match else cleaned,
                            match["no_pesanan"] if match else cleaned,
                            match["marketplace"] if match else "",
                            match["nama_toko"] if match else "",
                            match["sku_terdeteksi"] if match else "",
                            match["nama_produk"] if match else "",
                            match["qty"] if match else 1,
                            "DITERIMA",
                            "", "",
                            match["kurir"] if match else "",
                            operator_name,
                            waktu, tanggal,
                        ),
                    )

                    # ── Update penjualan: hanya ubah status, jangan zero-out nilai ──
                    # Data penjualan asli tetap utuh. Koreksi dicatat di jurnal retur_klaim.
                    if match:
                        db.execute(
                            "UPDATE penjualan SET status_pesanan = 'RETUR', "
                            "keterangan = 'Retur diterima - stok dikembalikan (nilai asli tetap)' "
                            "WHERE no_pesanan = ? OR no_resi = ?",
                            (match["no_pesanan"], match["no_resi"]),
                        )
                        # Insert RETUR entry in scan_aktif for dashboard tracking
                        dup_scan = db.fetch_one("SELECT id FROM scan_aktif WHERE resi = ? AND status = 'RETUR'",
                                                (match["no_resi"] if match["no_resi"] else cleaned,))
                        if not dup_scan:
                            db.execute(
                                "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, "
                                "status, kategori, keterangan_barang, tipe_kiriman, marketplace) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (waktu, tanggal,
                                 match["no_resi"] if match["no_resi"] else cleaned,
                                 match["kurir"] if match else "RETUR",
                                 match["nama_toko"] if match else "",
                                 "RETUR", "REGULER", "Retur diterima - stok pulih", "REGULER",
                                 match["marketplace"] if match else ""),
                            )

                    # ── Recover SKU stock ──
                    sku_code = match["sku_terdeteksi"] if match else ""
                    retur_qty = match["qty"] if match else 1
                    if sku_code and retur_qty > 0:
                        existing_sku = db.fetch_one(
                            "SELECT id, stok, nama_barang FROM sku WHERE kode_sku = ?",
                            (sku_code,),
                        )
                        if existing_sku:
                            new_stok = existing_sku["stok"] + retur_qty
                            db.execute(
                                "UPDATE sku SET stok = ?, updated_at = CURRENT_TIMESTAMP WHERE kode_sku = ?",
                                (new_stok, sku_code),
                            )
                            st.info(
                                f"📦 **Stok Pulih**: SKU `{sku_code}` ({existing_sku['nama_barang']}) "
                                f"stok {existing_sku['stok']} -> **{new_stok}** (+{retur_qty})"
                            )
                        else:
                            st.caption(f"⚠️ SKU `{sku_code}` tidak ditemukan - stok tidak di-update.")

                    st.success(
                        f"✅ **DITERIMA** - `{cleaned}` retur diterima. "
                        f"Stok dikembalikan. Transaksi asli tetap utuh, koreksi tercatat di jurnal retur."
                    )
                    st.rerun()

    # ── History Table ──
    st.markdown("---")
    st.markdown("### 📋 Riwayat Retur & Klaim")

    # Filters
    filt_col1, filt_col2, filt_col3, filt_col4 = st.columns([2, 2, 1, 1])
    with filt_col1:
        status_filter = st.selectbox(
            "Filter Status",
            ["Semua", "DITERIMA", "KLAIM"],
            key="retur_filter_status",
        )
    with filt_col2:
        mp_list = db.fetch_all("SELECT DISTINCT marketplace FROM retur_klaim WHERE marketplace != '' ORDER BY marketplace")
        mp_options = ["Semua"] + [r["marketplace"] for r in mp_list]
        mp_filter = st.selectbox("Filter Marketplace", mp_options, key="retur_filter_mp")
    with filt_col3:
        search_retur = st.text_input("🔍 Cari Resi/No Pesanan", placeholder="Ketik...", key="retur_search")
    with filt_col4:
        st.write("")
        if st.button("🔄 Refresh", width="stretch", key="retur_refresh"):
            st.rerun()

    # Build query
    query = "SELECT * FROM retur_klaim WHERE 1=1"
    params = []
    if status_filter != "Semua":
        query += " AND status = ?"
        params.append(status_filter)
    if mp_filter != "Semua":
        query += " AND marketplace = ?"
        params.append(mp_filter)
    if search_retur:
        query += " AND (no_resi LIKE ? OR no_pesanan LIKE ?)"
        params.extend([f"%{search_retur}%", f"%{search_retur}%"])
    query += " ORDER BY id DESC LIMIT 100"

    rows = db.fetch_all(query, params)

    if not rows:
        st.info("📭 Belum ada data retur atau klaim. Scan paket retur dari kurir untuk memulai.")
    else:
        df_retur = pd.DataFrame([dict(r) for r in rows])
        df_retur = df_retur.rename(columns={
            "waktu": "Waktu", "tanggal": "Tanggal", "no_resi": "No Resi",
            "no_pesanan": "No Pesanan", "marketplace": "MP", "nama_toko": "Toko",
            "sku": "SKU", "nama_produk": "Produk", "qty": "Qty",
            "status": "Status", "alasan_klaim": "Alasan Klaim",
            "kurir": "Kurir", "operator": "Operator",
            "nominal_klaim": "Nominal Klaim", "status_klaim": "Status Klaim",
        })

        # Format nominal
        if "Nominal Klaim" in df_retur.columns:
            df_retur["Nominal Klaim"] = df_retur["Nominal Klaim"].apply(
                lambda x: f"Rp {x:,.0f}" if x and x > 0 else "-"
            )

        def color_retur_status(val):
            if val == "DITERIMA":
                return "background-color: #d4edda; color: #155724; font-weight: bold"
            elif val == "KLAIM":
                return "background-color: #f8d7da; color: #721c24; font-weight: bold"
            return ""

        def color_klaim_status(val):
            if val == "BERHASIL":
                return "background-color: #d4edda; color: #155724; font-weight: bold"
            elif val == "GAGAL":
                return "background-color: #f8d7da; color: #721c24; font-weight: bold"
            elif val == "PENDING":
                return "background-color: #fff3cd; color: #856404; font-weight: bold"
            return ""

        display_cols = ["Waktu", "No Resi", "No Pesanan", "MP", "Toko", "SKU", "Produk", "Qty",
                        "Status", "Alasan Klaim", "Nominal Klaim", "Status Klaim", "Kurir", "Operator"]
        available = [c for c in display_cols if c in df_retur.columns]
        styled = df_retur[available].style.map(color_retur_status, subset=["Status"])
        if "Status Klaim" in df_retur.columns:
            styled = styled.map(color_klaim_status, subset=["Status Klaim"])
        st.dataframe(styled, width="stretch", height=450, hide_index=True)

        # Summary per status
        st.markdown("---")
        sum_diterima = len(df_retur[df_retur["Status"] == "DITERIMA"]) if "Status" in df_retur.columns else 0
        sum_klaim = len(df_retur[df_retur["Status"] == "KLAIM"]) if "Status" in df_retur.columns else 0
        sum_klaim_berhasil = len(df_retur[(df_retur["Status"] == "KLAIM") & (df_retur["Status Klaim"] == "BERHASIL")]) if "Status" in df_retur.columns and "Status Klaim" in df_retur.columns else 0
        total_nominal_klaim = sum(r["nominal_klaim"] or 0 for r in rows if r["status"] == "KLAIM" and r.get("status_klaim") == "BERHASIL")

        sum_text = f"📊 Menampilkan {len(df_retur)} data | ✅ Diterima: {sum_diterima} | ⚠️ Klaim: {sum_klaim}"
        if sum_klaim_berhasil > 0:
            sum_text += f" | 💰 Klaim Berhasil: {sum_klaim_berhasil} (Rp {total_nominal_klaim:,.0f})"
        st.caption(sum_text)

        # ── Delete action ──
        with st.expander("🗑️ Hapus Data Retur", expanded=False):
            del_id = st.number_input("ID Data yang akan dihapus", min_value=1, step=1, key="retur_del_id")
            if st.button("🗑️ Hapus", width="stretch", key="retur_del_btn"):
                existing = db.fetch_one("SELECT id FROM retur_klaim WHERE id = ?", (del_id,))
                if existing:
                    db.execute("DELETE FROM retur_klaim WHERE id = ?", (del_id,))
                    st.success(f"✅ Data retur ID `{del_id}` dihapus.")
                    st.rerun()
                else:
                    st.warning(f"ID `{del_id}` tidak ditemukan.")


# ==================== SETTINGS HELPERS ====================
def _get_setting(db, kunci: str, default: str = "") -> str:
    """Get a setting value from pengaturan table."""
    row = db.fetch_one("SELECT nilai FROM pengaturan WHERE kunci = ?", (kunci,))
    return row["nilai"] if row else default


def _save_setting(db, kunci: str, nilai: str):
    """Save a setting value to pengaturan table."""
    db.execute(
        "INSERT OR REPLACE INTO pengaturan (kunci, nilai) VALUES (?, ?)",
        (kunci, nilai),
    )


# ==================== LABA RUGI HARIAN ====================
def render_laba_rugi():
    """Laba Rugi Harian - Gross Omset - Potongan Marketplace - Biaya/Resi - Modal = Net Profit."""
    db = st.session_state.db

    st.subheader("💰 Laba Rugi Harian - Berdasarkan Pesanan Terkirim (PACKED)")
    st.caption(
        "Menghitung keuntungan bersih harian dari pesanan yang sudah di-packing. "
        "**Gross Omset** = total penjualan | **Net Profit** = omset dikurangi potongan marketplace, "
        "biaya per resi (Rp 1.250), dan Harga Modal (HPP)."
    )

    # ── Settings ──
    with st.expander("⚙️ Pengaturan Potongan Marketplace & Biaya", expanded=False):
        st.caption("Atur persentase potongan per marketplace dan biaya tetap per resi. Disimpan otomatis.")
        set_col1, set_col2, set_col3, set_col4 = st.columns(4)
        with set_col1:
            fee_shopee = st.number_input(
                "Fee Shopee (%)", min_value=0.0, max_value=30.0,
                value=float(_get_setting(db, "fee_shopee", "5.0")),
                step=0.1, key="laba_set_fee_shopee",
            )
        with set_col2:
            fee_tiktok = st.number_input(
                "Fee TikTok (%)", min_value=0.0, max_value=30.0,
                value=float(_get_setting(db, "fee_tiktok", "4.0")),
                step=0.1, key="laba_set_fee_tiktok",
            )
        with set_col3:
            fee_lazada = st.number_input(
                "Fee Lazada (%)", min_value=0.0, max_value=30.0,
                value=float(_get_setting(db, "fee_lazada", "4.5")),
                step=0.1, key="laba_set_fee_lazada",
            )
        with set_col4:
            biaya_per_resi = st.number_input(
                "Biaya per Resi (Rp)", min_value=0, max_value=100000,
                value=int(_get_setting(db, "biaya_per_resi", "1250")),
                step=100, key="laba_set_biaya_resi",
            )

        tax_col1, tax_col2, _, _ = st.columns(4)
        with tax_col1:
            pph_persen = st.number_input(
                "PPh Final UMKM (%)", min_value=0.0, max_value=10.0,
                value=float(_get_setting(db, "pph_persen", "0.5")),
                step=0.1, key="laba_set_pph",
                help="PPh Final 0.5% dari gross omset (PP 23/2018). Otomatis dipotong marketplace."
            )
        with tax_col2:
            ppn_persen = st.number_input(
                "PPN (%)", min_value=0.0, max_value=20.0,
                value=float(_get_setting(db, "ppn_persen", "11.0")),
                step=0.1, key="laba_set_ppn",
                help="PPN 11% untuk PKP. Set 0 jika non-PKP."
            )

        if st.button("💾 Simpan Pengaturan", key="laba_save_settings"):
            _save_setting(db, "fee_shopee", str(fee_shopee))
            _save_setting(db, "fee_tiktok", str(fee_tiktok))
            _save_setting(db, "fee_lazada", str(fee_lazada))
            _save_setting(db, "biaya_per_resi", str(biaya_per_resi))
            _save_setting(db, "pph_persen", str(pph_persen))
            _save_setting(db, "ppn_persen", str(ppn_persen))
            st.success("✅ Pengaturan disimpan!")
            st.rerun()

    st.markdown("---")

    # ── Date Filter ──
    filt_col1, filt_col2 = st.columns([2, 2])
    with filt_col1:
        today = datetime.now()
        tgl_laba = st.date_input("Tanggal", value=today.date(), key="laba_tgl")
        tgl_str = tgl_laba.strftime("%d-%m-%Y") if tgl_laba else today.strftime("%d-%m-%Y")
    with filt_col2:
        st.write("")
        if st.button("🔄 Refresh Data", width="stretch", key="laba_refresh"):
            st.rerun()

    # ── Fee mapping ──
    fee_map = {
        "Shopee": fee_shopee / 100.0,
        "TikTok": fee_tiktok / 100.0,
        "Lazada": fee_lazada / 100.0,
    }

    # ── Query: PACKED orders on selected date ──
    packed_orders = db.fetch_all(
        "SELECT p.id, p.marketplace, p.no_pesanan, p.no_resi, p.sku_terdeteksi, "
        "p.nama_produk, p.nama_toko, p.qty, p.harga_jual, p.total_harga "
        "FROM penjualan p "
        "INNER JOIN scan_aktif s ON p.no_resi = s.resi "
        "WHERE s.status = 'PACKED' AND s.tanggal = ?",
        (tgl_str,),
    )

    if not packed_orders:
        st.info(f"📭 Belum ada pesanan PACKED untuk tanggal {tgl_str}.")
        return

    # ── Build SKU harga_beli lookup ──
    all_sku_codes = list(set(r["sku_terdeteksi"] for r in packed_orders if r["sku_terdeteksi"]))
    sku_harga = {}
    if all_sku_codes:
        # Batch lookup
        placeholders = ",".join(["?" for _ in all_sku_codes])
        sku_rows = db.fetch_all(
            f"SELECT kode_sku, harga_beli, nama_barang FROM sku WHERE kode_sku IN ({placeholders})",
            all_sku_codes,
        )
        for sr in sku_rows:
            sku_harga[sr["kode_sku"]] = {
                "harga_beli": sr["harga_beli"] or 0,
                "nama": sr["nama_barang"],
            }

    # ── Calculate per-order ──
    total_gross = 0.0
    total_modal = 0.0
    total_fee_pct = 0.0
    total_biaya_resi = 0.0
    unique_resi = set()
    sku_missing_modal = set()
    per_mp = {}  # per marketplace breakdown

    for order in packed_orders:
        gross = order["total_harga"] or 0
        mp = order["marketplace"] or "Lainnya"
        resi = order["no_resi"]
        sku = order["sku_terdeteksi"]
        qty = order["qty"] or 1

        total_gross += gross
        if resi:
            unique_resi.add(resi)

        # Fee percentage
        fee_rate = fee_map.get(mp, 0.05)  # default 5% if unknown
        fee_amount = gross * fee_rate
        total_fee_pct += fee_amount

        # Per-resi cost (already added per unique resi below)
        # Modal (HPP)
        modal_per_item = sku_harga.get(sku, {}).get("harga_beli", 0) if sku else 0
        modal_total = modal_per_item * qty
        total_modal += modal_total
        if sku and modal_per_item == 0:
            sku_missing_modal.add(sku)

        # Per marketplace tracking
        if mp not in per_mp:
            per_mp[mp] = {"gross": 0, "fee": 0, "modal": 0, "orders": 0, "resi": set()}
        per_mp[mp]["gross"] += gross
        per_mp[mp]["fee"] += fee_amount
        per_mp[mp]["modal"] += modal_total
        per_mp[mp]["orders"] += 1
        if resi:
            per_mp[mp]["resi"].add(resi)

    # Biaya per resi (unique)
    total_biaya_resi = len(unique_resi) * biaya_per_resi

    # ── Biaya Packing Variable Harian (dari OPEX tipe VARIABLE) ──
    opex_var_harian = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE tipe = 'VARIABLE' AND tanggal = ? AND status_bayar = 'LUNAS'",
        (tgl_str,),
    )
    total_opex_var = opex_var_harian["total"] if opex_var_harian else 0

    # Net Profit = Gross - Fee MP - Biaya/Resi - Modal (HPP) - Packing Variable
    net_profit = total_gross - total_fee_pct - total_biaya_resi - total_modal - total_opex_var

    # ── Summary Cards ──
    st.markdown("### 📊 Ringkasan Laba Rugi")
    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
    with col1:
        st.metric("💰 Gross Omset", f"Rp {total_gross:,.0f}")
    with col2:
        st.metric("🔻 Potongan MP", f"Rp {total_fee_pct:,.0f}",
                 help=f"Fee marketplace ({fee_shopee}%/{fee_tiktok}%/{fee_lazada}%)")
    with col3:
        st.metric("📦 Biaya / Resi", f"Rp {total_biaya_resi:,.0f}",
                 help=f"{len(unique_resi)} resi × Rp {biaya_per_resi:,}")
    with col4:
        st.metric("📋 Harga Modal", f"Rp {total_modal:,.0f}",
                 help="HPP = qty × harga_beli dari SKU")
    with col5:
        st.metric("📦 Packing Variable", f"Rp {total_opex_var:,.0f}",
                 help="Biaya packing harian: bubble, kardus, lakban, bensin (dari OPEX VARIABLE LUNAS)")
    with col6:
        pct_margin = (net_profit / total_gross * 100) if total_gross > 0 else 0
        st.metric("✅ Net Profit", f"Rp {net_profit:,.0f}",
                 delta=f"{pct_margin:.1f}% margin")
    with col7:
        st.metric("📦 Total Resi", len(unique_resi))

    if sku_missing_modal:
        st.warning(
            f"⚠️ **{len(sku_missing_modal)} SKU** belum memiliki Harga Modal (Harga Beli). "
            f"SKU: {', '.join(sorted(list(sku_missing_modal))[:10])}"
            f"{'...' if len(sku_missing_modal) > 10 else ''}. "
            "Lengkapi di Manajemen SKU agar perhitungan laba rugi akurat."
        )

    # ── Margin bar ──
    st.markdown("---")
    if total_gross > 0:
        fee_pct = total_fee_pct / total_gross * 100
        biaya_pct = total_biaya_resi / total_gross * 100
        modal_pct = total_modal / total_gross * 100
        opex_var_pct = total_opex_var / total_gross * 100
        profit_pct = max(0, net_profit / total_gross * 100)

        st.caption(f"💡 **Komposisi Omset**: Fee MP {fee_pct:.1f}% | Biaya/Resi {biaya_pct:.1f}% | Modal {modal_pct:.1f}% | Packing Var {opex_var_pct:.1f}% | Profit {profit_pct:.1f}%")
        if total_opex_var > 0:
            st.caption(f"📦 Biaya packing variable hari ini: **Rp {total_opex_var:,.0f}** (bubble, kardus, lakban, bensin, dll.)")

    # ── Monthly OPEX Tetap Info ──
    st.markdown("---")
    this_month_str = datetime.now().strftime("%m-%Y")
    opex_tetap_bulan = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE tipe = 'TETAP' AND tanggal LIKE ? AND status_bayar = 'LUNAS'",
        (f"%{this_month_str}%",),
    )
    tetap_val = opex_tetap_bulan["total"] if opex_tetap_bulan else 0
    hari_dalam_bulan = datetime.now().day
    total_hari_bulan = 30  # approximate
    tetap_per_hari = tetap_val / total_hari_bulan if tetap_val > 0 else 0

    st.info(
        f"🏢 **OPEX Tetap Bulanan**: Rp {tetap_val:,.0f}/bulan (≈ Rp {tetap_per_hari:,.0f}/hari). "
        f"OPEX tetap (Gaji, Listrik, Internet, Sewa, dll.) akan dihitung penuh di **Laba Rugi Bulanan** pada Dashboard Finance."
    )

    # ── Per Marketplace Breakdown ──
    st.markdown("---")
    st.markdown("### 🏪 Per Marketplace")
    if per_mp:
        mp_rows = []
        for mp, data in sorted(per_mp.items()):
            mp_net = data["gross"] - data["fee"] - (len(data["resi"]) * biaya_per_resi) - data["modal"]
            mp_rows.append({
                "Marketplace": mp,
                "Pesanan": data["orders"],
                "Resi": len(data["resi"]),
                "Gross": f"Rp {data['gross']:,.0f}",
                "Fee MP": f"Rp {data['fee']:,.0f}",
                "Biaya/Resi": f"Rp {len(data['resi']) * biaya_per_resi:,.0f}",
                "Modal": f"Rp {data['modal']:,.0f}",
                "Net Profit": f"Rp {mp_net:,.0f}",
            })
        df_mp = pd.DataFrame(mp_rows)
        st.dataframe(df_mp, width="stretch", hide_index=True)

    # ── Monthly trend (optional, quick view) ──
    st.markdown("---")
    st.markdown("### 📅 7 Hari Terakhir")
    last_7 = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.strftime("%d-%m-%Y")
        day_data = db.fetch_all(
            "SELECT p.total_harga, p.marketplace, p.sku_terdeteksi, p.qty, s.resi "
            "FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            "WHERE s.status = 'PACKED' AND s.tanggal = ?",
            (d_str,),
        )
        if day_data:
            day_gross = sum(r["total_harga"] or 0 for r in day_data)
            day_resi = set(r["resi"] for r in day_data if r["resi"])
            day_fee = sum((r["total_harga"] or 0) * fee_map.get(r["marketplace"] or "Lainnya", 0.05) for r in day_data)
            day_biaya = len(day_resi) * biaya_per_resi
            # Modal quick calc
            day_sku_codes = set(r["sku_terdeteksi"] for r in day_data if r["sku_terdeteksi"])
            day_modal = 0
            if day_sku_codes:
                day_modals = {}
                for r in day_data:
                    sk = r["sku_terdeteksi"]
                    if sk and sk in sku_harga:
                        day_modal += (sku_harga[sk]["harga_beli"] or 0) * (r["qty"] or 1)
            # Daily variable OPEX (packing)
            day_opex_var = db.fetch_one(
                "SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE tipe = 'VARIABLE' AND tanggal = ? AND status_bayar = 'LUNAS'",
                (d_str,),
            )
            day_opex_val = day_opex_var["total"] if day_opex_var else 0
            day_net = day_gross - day_fee - day_biaya - day_modal - day_opex_val
            last_7.append({
                "Tanggal": d_str,
                "Gross": day_gross,
                "Packing Var": day_opex_val,
                "Net Profit": day_net,
                "Resi": len(day_resi),
                "Margin": f"{(day_net / day_gross * 100):.1f}%" if day_gross > 0 else "0%",
            })

    if last_7:
        df_trend = pd.DataFrame(last_7)
        df_trend["Gross"] = df_trend["Gross"].apply(lambda x: f"Rp {x:,.0f}")
        df_trend["Packing Var"] = df_trend["Packing Var"].apply(lambda x: f"Rp {x:,.0f}")
        df_trend["Net Profit"] = df_trend["Net Profit"].apply(lambda x: f"Rp {x:,.0f}")
        st.dataframe(df_trend, width="stretch", hide_index=True)
    else:
        st.caption("Belum ada data 7 hari terakhir.")


# ==================== CASHFLOW & PENC AIRAN ====================
def render_cashflow():
    """Cashflow - Laporan Keuangan ala Marketplace: Saldo, Penjualan, Biaya, Pencairan per platform."""
    db = st.session_state.db

    st.subheader("💵 Cashflow & Pencairan Marketplace")
    st.caption(
        "Informasi keuangan seperti yang tampil di Seller Center: **Saldo per Marketplace**, "
        "penjualan, potongan, biaya, klaim, pencairan, dan arus kas gabungan."
    )

    # ── Load settings ──
    fee_shopee = float(_get_setting(db, "fee_shopee", "5.0"))
    fee_tiktok = float(_get_setting(db, "fee_tiktok", "4.0"))
    fee_lazada = float(_get_setting(db, "fee_lazada", "4.5"))
    biaya_per_resi = int(_get_setting(db, "biaya_per_resi", "1250"))
    fee_map = {"Shopee": fee_shopee / 100.0, "TikTok": fee_tiktok / 100.0, "Lazada": fee_lazada / 100.0}

    # ── Period Filter ──
    filt_c1, filt_c2, filt_c3 = st.columns([2, 2, 1])
    with filt_c1:
        cf_start = st.date_input("Dari Tanggal", value=datetime.now().replace(day=1).date(), key="cf_start")
    with filt_c2:
        cf_end = st.date_input("Sampai Tanggal", value=datetime.now().date(), key="cf_end")
    with filt_c3:
        st.write("")
        if st.button("🔄 Refresh", width="stretch", key="cf_refresh"):
            st.rerun()

    tgl_list = []
    d = cf_start
    while d <= cf_end:
        tgl_list.append(d.strftime("%d-%m-%Y"))
        d += timedelta(days=1)

    tempat = ",".join(["?" for _ in tgl_list]) if tgl_list else ""

    # ═══════════════════════════════════════════
    # PER-MARKETPLACE CALCULATION
    # ═══════════════════════════════════════════
    MARKETPLACES = ["Shopee", "TikTok", "Lazada"]
    mp_data = {}
    total_income_all = 0
    total_expenses_all = 0
    total_penjualan_all = 0
    total_fee_all = 0
    total_biaya_all = 0
    total_modal_all = 0
    total_klaim_all = 0
    all_skus_for_modal = set()

    for mp in MARKETPLACES:
        # Penjualan PACKED per MP
        mp_penjualan = db.fetch_all(
            f"SELECT p.total_harga, p.no_resi, p.sku_terdeteksi, p.qty "
            f"FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            f"WHERE s.status = 'PACKED' AND p.marketplace = ? AND s.tanggal IN ({tempat})",
            [mp] + tgl_list,
        ) if tgl_list else []

        mp_gross = sum(r["total_harga"] or 0 for r in mp_penjualan)
        mp_resi = set(r["no_resi"] for r in mp_penjualan if r["no_resi"])
        mp_fee = mp_gross * fee_map.get(mp, 0.05)
        mp_biaya = len(mp_resi) * biaya_per_resi

        # Modal
        mp_modal = 0
        for r in mp_penjualan:
            if r["sku_terdeteksi"]:
                all_skus_for_modal.add(r["sku_terdeteksi"])

        # Klaim BERHASIL per MP
        mp_klaim_row = db.fetch_one(
            f"SELECT COALESCE(SUM(nominal_klaim), 0) as tot FROM retur_klaim "
            f"WHERE status='KLAIM' AND status_klaim='BERHASIL' AND marketplace = ? AND tanggal IN ({tempat})",
            [mp] + tgl_list,
        ) if tgl_list else None
        mp_klaim = mp_klaim_row["tot"] if mp_klaim_row else 0

        # Pencairan per MP (all-time)
        mp_cair_all = db.fetch_one(
            "SELECT COALESCE(SUM(jumlah), 0) as tot FROM pencairan WHERE marketplace = ?",
            (mp,),
        )
        mp_cair_total = mp_cair_all["tot"] if mp_cair_all else 0

        # Pencairan periode
        mp_cair_periode = db.fetch_one(
            f"SELECT COALESCE(SUM(jumlah), 0) as tot FROM pencairan WHERE marketplace = ? AND tanggal IN ({tempat})",
            [mp] + tgl_list,
        ) if tgl_list else None
        mp_cair_per = mp_cair_periode["tot"] if mp_cair_periode else 0

        mp_data[mp] = {
            "gross": mp_gross,
            "resi": len(mp_resi),
            "fee": mp_fee,
            "biaya": mp_biaya,
            "klaim": mp_klaim,
            "modal": 0,  # will fill after SKU lookup
            "penjualan_rows": mp_penjualan,
            "pencairan_all": mp_cair_total,
            "pencairan_periode": mp_cair_per,
        }
        total_penjualan_all += mp_gross
        total_fee_all += mp_fee
        total_biaya_all += mp_biaya
        total_klaim_all += mp_klaim

    # ── SKU Modal lookup (batch) ──
    sku_modal = {}
    if all_skus_for_modal:
        ph = ",".join(["?" for _ in all_skus_for_modal])
        sku_rows = db.fetch_all(
            f"SELECT kode_sku, harga_beli FROM sku WHERE kode_sku IN ({ph})",
            list(all_skus_for_modal),
        )
        for sr in sku_rows:
            sku_modal[sr["kode_sku"]] = sr["harga_beli"] or 0

    # Fill per-MP modal
    for mp in MARKETPLACES:
        mp_modal = 0
        for r in mp_data[mp]["penjualan_rows"]:
            sku = r["sku_terdeteksi"]
            qty = r["qty"] or 1
            mp_modal += (sku_modal.get(sku, 0)) * qty
        mp_data[mp]["modal"] = mp_modal
        total_modal_all += mp_modal

    # ── Per-MP Net Profit (all-time for saldo) ──
    for mp in MARKETPLACES:
        mp_all_gross = db.fetch_one(
            "SELECT COALESCE(SUM(p.total_harga), 0) as tot FROM penjualan p "
            "INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            "WHERE s.status='PACKED' AND p.marketplace = ?", (mp,),
        )
        mp_all_g = mp_all_gross["tot"] if mp_all_gross else 0
        mp_all_fee = mp_all_g * fee_map.get(mp, 0.05)

        mp_all_resi = db.fetch_one(
            "SELECT COUNT(DISTINCT p.no_resi) as cnt FROM penjualan p "
            "INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            "WHERE s.status='PACKED' AND p.marketplace = ? AND p.no_resi != ''", (mp,),
        )
        mp_all_biaya = (mp_all_resi["cnt"] if mp_all_resi else 0) * biaya_per_resi

        # All-time modal & klaim per MP
        mp_all_sku_rows = db.fetch_all(
            "SELECT p.sku_terdeteksi, p.qty FROM penjualan p "
            "INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            "WHERE s.status='PACKED' AND p.marketplace = ? AND p.sku_terdeteksi != ''", (mp,),
        )
        mp_all_modal = 0
        for r in mp_all_sku_rows:
            mp_all_modal += (sku_modal.get(r["sku_terdeteksi"], 0)) * (r["qty"] or 1)

        mp_all_klaim = db.fetch_one(
            "SELECT COALESCE(SUM(nominal_klaim), 0) as tot FROM retur_klaim "
            "WHERE status='KLAIM' AND status_klaim='BERHASIL' AND marketplace = ?", (mp,),
        )
        mp_klaim_all = mp_all_klaim["tot"] if mp_all_klaim else 0

        mp_net_alltime = mp_all_g + mp_klaim_all - mp_all_fee - mp_all_biaya - mp_all_modal
        mp_data[mp]["net_alltime"] = mp_net_alltime
        mp_data[mp]["saldo"] = mp_net_alltime - mp_data[mp]["pencairan_all"]

    # ── OPEX + Pembelian (global, not per-MP) ──
    opex_total = db.fetch_one(
        f"SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE status_bayar='LUNAS' AND tanggal IN ({tempat})",
        tgl_list,
    ) if tgl_list else None
    total_opex = opex_total["total"] if opex_total else 0

    pembelian_total = db.fetch_one(
        f"SELECT COALESCE(SUM(total_harga), 0) as total FROM pembelian WHERE status_bayar='LUNAS' AND tanggal IN ({tempat})",
        tgl_list,
    ) if tgl_list else None
    total_pembelian = pembelian_total["total"] if pembelian_total else 0

    total_income_all = total_penjualan_all + total_klaim_all
    total_expenses_all = total_fee_all + total_biaya_all + total_modal_all + total_opex + total_pembelian
    net_profit = total_income_all - total_expenses_all

    # Global all-time for combined saldo
    all_net = _hitung_all_time_net(db, fee_map, biaya_per_resi)
    all_pencairan = db.fetch_one("SELECT COALESCE(SUM(jumlah), 0) as total FROM pencairan")
    total_pencairan_all = all_pencairan["total"] if all_pencairan else 0
    saldo_global = all_net - total_pencairan_all

    # ═══════════════════════════════════════════
    # 📊 PER-MARKETPLACE SALDO CARDS
    # ═══════════════════════════════════════════
    st.markdown("### 💎 Saldo per Marketplace")
    st.caption("Saldo = (Penjualan + Klaim - Fee - Biaya - Modal) - Pencairan - **uang yang masih di marketplace, belum dicairkan**.")

    saldo_cols = st.columns(len(MARKETPLACES))
    mp_colors = {"Shopee": "#EE4D2D", "TikTok": "#000000", "Lazada": "#0F1568"}
    for i, mp in enumerate(MARKETPLACES):
        d = mp_data[mp]
        with saldo_cols[i]:
            saldo_val = d["saldo"]
            st.markdown(f"##### 🏪 {mp}")
            st.metric(
                "💎 Saldo Tersedia",
                f"Rp {saldo_val:,.0f}",
                help=(
                    f"Penjualan All-Time + Klaim - Fee - Biaya - Modal = Rp {d['net_alltime']:,.0f}\n"
                    f"Dikurangi Pencairan: Rp {d['pencairan_all']:,.0f}\n"
                    f"= Saldo: Rp {saldo_val:,.0f}"
                ),
            )
            st.caption(
                f"📦 Penjualan: Rp {d['gross']:,.0f}\n"
                f"⚖️ Klaim: Rp {d['klaim']:,.0f}\n"
                f"🔻 Fee: Rp {d['fee']:,.0f}\n"
                f"🏦 Pencairan: Rp {d['pencairan_periode']:,.0f}"
            )

    st.markdown("---")

    # ═══════════════════════════════════════════
    # 📊 RINGKASAN GABUNGAN
    # ═══════════════════════════════════════════
    st.markdown("### 📊 Ringkasan Keuangan (Gabungan)")
    col_a, col_b, col_c, col_d, col_e = st.columns(5)
    with col_a:
        st.metric("💰 Total Income", f"Rp {total_income_all:,.0f}",
                 help="Penjualan PACKED + Klaim Berhasil (semua marketplace)")
    with col_b:
        st.metric("📤 Total Expenses", f"Rp {total_expenses_all:,.0f}",
                 help="Fee MP + Biaya/Resi + Modal + OPEX + Pembelian")
    with col_c:
        margin = (net_profit / total_income_all * 100) if total_income_all > 0 else 0
        st.metric("✅ Net Profit", f"Rp {net_profit:,.0f}",
                 delta=f"{margin:.1f}% margin")
    with col_d:
        # Pencairan periode
        cair_periode_all = sum(d["pencairan_periode"] for d in mp_data.values())
        st.metric("🏦 Pencairan Periode", f"Rp {cair_periode_all:,.0f}")
    with col_e:
        st.metric("💎 Saldo Global", f"Rp {saldo_global:,.0f}",
                 help=f"Saldo gabungan semua marketplace = Akumulasi Net Profit - Total Pencairan")

    # ── Expense Ratio ──
    if total_income_all > 0:
        ratio = total_expenses_all / total_income_all
        st.progress(min(ratio, 1.0), text=f"📊 Expense Ratio: {ratio*100:.1f}% dari Income | Profit Margin: {max(0,100-ratio*100):.1f}%")

    st.markdown("---")

    # ═══════════════════════════════════════════
    # 📊 DETAIL PER MARKETPLACE
    # ═══════════════════════════════════════════
    st.markdown("### 🏪 Detail per Marketplace")

    mp_tabs = st.tabs(["🟠 Shopee", "⚫ TikTok", "🔵 Lazada"])
    for i, mp in enumerate(MARKETPLACES):
        with mp_tabs[i]:
            d = mp_data[mp]
            mp_net = d["gross"] + d["klaim"] - d["fee"] - d["biaya"] - d["modal"]
            mp_cair = d["pencairan_periode"]

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("📦 Penjualan", f"Rp {d['gross']:,.0f}")
            with c2:
                st.metric("⚖️ Klaim", f"Rp {d['klaim']:,.0f}")
            with c3:
                st.metric("🔻 Fee + Biaya", f"Rp {d['fee'] + d['biaya']:,.0f}")
            with c4:
                st.metric("📋 Modal (HPP)", f"Rp {d['modal']:,.0f}")

            st.markdown("---")
            df_mp_detail = pd.DataFrame([
                {"Item": "📦 Penjualan (Gross)", "Jumlah": f"Rp {d['gross']:,.0f}"},
                {"Item": "⚖️ Klaim Berhasil (+)", "Jumlah": f"Rp {d['klaim']:,.0f}"},
                {"Item": f"🔻 Fee Marketplace ({fee_map[mp]*100:.1f}%)", "Jumlah": f"Rp {d['fee']:,.0f}"},
                {"Item": f"📦 Biaya / Resi ({d['resi']} resi × Rp {biaya_per_resi:,})", "Jumlah": f"Rp {d['biaya']:,.0f}"},
                {"Item": "📋 Harga Modal (HPP)", "Jumlah": f"Rp {d['modal']:,.0f}"},
                {"Item": "━ **Net Profit**", "Jumlah": f"**Rp {mp_net:,.0f}**"},
                {"Item": "🏦 Pencairan Periode", "Jumlah": f"Rp {mp_cair:,.0f}"},
                {"Item": "💎 **Saldo Tersedia**", "Jumlah": f"**Rp {d['saldo']:,.0f}**"},
            ])
            st.dataframe(df_mp_detail, width="stretch", hide_index=True)

    st.markdown("---")

    # ═══════════════════════════════════════════
    # GLOBAL BREAKDOWN
    # ═══════════════════════════════════════════
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("#### 💰 Income")
        inc_rows = [
            {"Sumber": f"📦 {mp}", "Jumlah": f"Rp {mp_data[mp]['gross']:,.0f}"}
            for mp in MARKETPLACES
        ]
        inc_rows.append({"Sumber": "⚖️ Klaim Berhasil", "Jumlah": f"Rp {total_klaim_all:,.0f}"})
        inc_rows.append({"Sumber": "━ Total Income", "Jumlah": f"Rp {total_income_all:,.0f}"})
        st.dataframe(pd.DataFrame(inc_rows), width="stretch", hide_index=True)

    with col_r:
        st.markdown("#### 📤 Expenses")
        exp_rows = [
            {"Kategori": "🔻 Fee Marketplace", "Jumlah": f"Rp {total_fee_all:,.0f}"},
            {"Kategori": "📦 Biaya / Resi", "Jumlah": f"Rp {total_biaya_all:,.0f}"},
            {"Kategori": "📋 Harga Modal (HPP)", "Jumlah": f"Rp {total_modal_all:,.0f}"},
            {"Kategori": "📝 OPEX (Operasional)", "Jumlah": f"Rp {total_opex:,.0f}"},
            {"Kategori": "🛒 Pembelian SKU", "Jumlah": f"Rp {total_pembelian:,.0f}"},
            {"Kategori": "━ Total Expenses", "Jumlah": f"Rp {total_expenses_all:,.0f}"},
        ]
        st.dataframe(pd.DataFrame(exp_rows), width="stretch", hide_index=True)

    st.markdown("---")

    # ═══════════════════════════════════════════
    # PENC AIRAN FORM
    # ═══════════════════════════════════════════
    st.markdown("### 🏦 Catat Pencairan dari Marketplace")
    st.caption("Finance mencatat pencairan dana dari marketplace ke rekening bank.")

    cair_col1, cair_col2, cair_col3, cair_col4 = st.columns([2, 2, 1.5, 1.5])
    with cair_col1:
        cair_mp = st.selectbox("Marketplace", MARKETPLACES, key="cair_mp")
    with cair_col2:
        # Auto-suggest saldo tersedia
        suggested = mp_data[cair_mp]["saldo"]
        cair_jumlah = st.number_input(
            f"Jumlah Pencairan (Rp)",
            min_value=0, value=int(max(0, suggested)),
            step=100000, key="cair_jumlah",
            help=f"Saldo tersedia di {cair_mp}: Rp {suggested:,.0f}"
        )
    with cair_col3:
        cair_tgl = st.date_input("Tanggal Pencairan", value=datetime.now().date(), key="cair_tgl")
    with cair_col4:
        cair_ket = st.text_input("Keterangan", placeholder="Batch ID, referensi...", key="cair_ket")

    if st.button("🏦 **Catat Pencairan**", type="primary", key="cair_btn"):
        if cair_jumlah <= 0:
            st.error("Jumlah pencairan harus > 0!")
        else:
            db.execute(
                "INSERT INTO pencairan (marketplace, jumlah, tanggal, keterangan, operator) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    cair_mp, cair_jumlah, cair_tgl.strftime("%d-%m-%Y"),
                    cair_ket.strip(),
                    st.session_state.get("user", {}).get("nama_lengkap", "Finance"),
                ),
            )
            st.success(f"🏦 Pencairan **Rp {cair_jumlah:,.0f}** dari **{cair_mp}** berhasil dicatat!")
            st.rerun()

    st.markdown("---")

    # ── Pencairan History ──
    st.markdown("### 📋 Riwayat Pencairan")
    cair_history = db.fetch_all(
        "SELECT * FROM pencairan ORDER BY tanggal DESC, id DESC LIMIT 50"
    )
    if cair_history:
        df_cair = pd.DataFrame([dict(r) for r in cair_history])
        df_cair = df_cair.rename(columns={
            "tanggal": "Tanggal", "marketplace": "MP",
            "jumlah": "Jumlah", "keterangan": "Keterangan",
            "operator": "Operator",
        })
        df_cair["Jumlah"] = df_cair["Jumlah"].apply(lambda x: f"Rp {x:,.0f}")
        total_cair_semua = sum(r["jumlah"] for r in cair_history)
        st.dataframe(df_cair[["Tanggal", "MP", "Jumlah", "Keterangan", "Operator"]],
                    width="stretch", hide_index=True)
        st.caption(f"Total seluruh pencairan: **Rp {total_cair_semua:,.0f}** | {len(cair_history)} transaksi")
        mp_cair = {}
        for r in cair_history:
            mp_cair[r["marketplace"]] = mp_cair.get(r["marketplace"], 0) + r["jumlah"]
        st.caption(" | ".join(f"**{mp}**: Rp {jml:,.0f}" for mp, jml in sorted(mp_cair.items())))
    else:
        st.info("📭 Belum ada pencairan. Catat pencairan pertama menggunakan form di atas.")

    # Delete
    with st.expander("🗑️ Hapus Pencairan", expanded=False):
        del_cair_id = st.number_input("ID Pencairan", min_value=1, step=1, key="cair_del_id")
        if st.button("🗑️ Hapus", key="cair_del_btn"):
            r = db.fetch_one("SELECT * FROM pencairan WHERE id = ?", (del_cair_id,))
            if r:
                db.execute("DELETE FROM pencairan WHERE id = ?", (del_cair_id,))
                st.success(f"Pencairan Rp {r['jumlah']:,.0f} ({r['marketplace']}) dihapus.")
                st.rerun()
            else:
                st.warning("ID tidak ditemukan.")


def _hitung_all_time_net(db, fee_map, biaya_per_resi):
    """Hitung akumulasi Net Profit all-time dari semua pesanan PACKED."""
    all_packed = db.fetch_all(
        "SELECT p.total_harga, p.marketplace, p.no_resi, p.sku_terdeteksi, p.qty "
        "FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
        "WHERE s.status = 'PACKED'"
    )
    if not all_packed:
        return 0

    gross = sum(r["total_harga"] or 0 for r in all_packed)
    fee = sum((r["total_harga"] or 0) * fee_map.get(r["marketplace"] or "Lainnya", 0.05) for r in all_packed)
    resi_unik = set(r["no_resi"] for r in all_packed if r["no_resi"])
    biaya = len(resi_unik) * biaya_per_resi

    # Modal
    skus = set(r["sku_terdeteksi"] for r in all_packed if r["sku_terdeteksi"])
    sku_h = {}
    if skus:
        ph = ",".join(["?" for _ in skus])
        for sr in db.fetch_all(f"SELECT kode_sku, harga_beli FROM sku WHERE kode_sku IN ({ph})", list(skus)):
            sku_h[sr["kode_sku"]] = sr["harga_beli"] or 0
    modal = sum((sku_h.get(r["sku_terdeteksi"], 0)) * (r["qty"] or 1) for r in all_packed)

    # Klaim berhasil
    klaim = db.fetch_one("SELECT COALESCE(SUM(nominal_klaim), 0) as tot FROM retur_klaim WHERE status='KLAIM' AND status_klaim='BERHASIL'")
    total_klaim = klaim["tot"] if klaim else 0

    # OPEX + Pembelian all-time
    opex_all = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE status_bayar='LUNAS'")
    pemb_all = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM pembelian WHERE status_bayar='LUNAS'")

    net = gross + total_klaim - fee - biaya - modal - (opex_all["tot"] if opex_all else 0) - (pemb_all["tot"] if pemb_all else 0)
    return net


def render_ai_supervisor():
    """AI Supervisor - analisa & rekomendasi kinerja operasional."""
    db = st.session_state.db
    today_str = datetime.now().strftime("%d-%m-%Y")
    today_date = datetime.now().strftime("%Y-%m-%d")

    st.subheader("🤖 AI Supervisor - Analisa Kinerja Operasional")
    st.caption("AI menganalisa seluruh pipeline: Pesanan Masuk -> Packing -> Handover -> Selesai")

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
            insights.append(("✅", "Efisiensi packing sangat baik", f"{packing_rate:.0f}% resi sudah dipacking - tim operasional bekerja optimal.", "good"))
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
                alerts.append(("🔴", "Cancel Rate Tinggi", f"{cancel_rate:.0f}% pesanan dibatalkan - perlu investigasi penyebab cancel."))
            elif cancel_rate > 5:
                alerts.append(("⚠️", "Cancel Rate Meningkat", f"{cancel_rate:.0f}% cancel - pantau terus dan evaluasi stok/proses."))

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
                alerts.append(("⚠️", "Scan Pending Terdeteksi", f"{pending} resi pending - pastikan data penjualan sudah lengkap."))

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
                    f"{instant_waiting} pesanan instant ({instant_unpacked_pct:.0f}%) masih menunggu - SLA pengiriman lebih ketat.", "warn"))
            else:
                instant_done_pct = (instant_done / instant_total * 100) if instant_total > 0 else 0
                insights.append(("✅", "Semua Instant Terpacking", 
                    f"{instant_done}/{instant_total} pesanan instant sudah selesai dipacking. Good job!", "good"))

    # ═══════════════════════════════════════════
    # 📋 RECOMMENDATIONS
    # ═══════════════════════════════════════════
    if instant_waiting > 0:
        recommendations.insert(0, ("🚀", "DAHULUKAN INSTANT!", 
            f"🚨 {instant_waiting} pesanan instant/same-day belum dipacking. SLA ketat - kerjakan SEKARANG sebelum reguler!"))
    if tanpa_resi_cnt > 0:
        recommendations.append(("📋", "Update No Resi", f"Prioritaskan update {tanpa_resi_cnt} pesanan tanpa resi di menu Input Resi & Pesanan."))
    if pending > 0:
        recommendations.append(("🔍", "Verifikasi Pending", f"Cek {pending} scan pending - pastikan data penjualan sesuai dengan resi fisik."))
    if handover_ready > 0:
        recommendations.append(("📤", "Siapkan Handover", f"{handover_ready} resi siap handover. Export laporan handover untuk kurir."))
    if cancel > 10:
        recommendations.append(("🛑", "Evaluasi Cancel", f"Cancel rate tinggi ({cancel} resi). Review proses quality control dan stok barang."))
    if packed > 0 and with_resi_cnt > 0 and (with_resi_cnt - packed) > 0:
        recommendations.append(("🎯", "Target Packing", f"Selesaikan {with_resi_cnt - packed} resi tersisa untuk capai 100% packing rate."))
    if sku_match_pct < 85:
        recommendations.append(("🏷️", "Perbaiki SKU", f"Tingkatkan SKU matching ({sku_match_pct:.0f}%) - update file Excel dengan kode SKU yang benar."))

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
        <p style="margin: 5px 0 0 0; color: #AEAEB2; font-size: 14px;">Status: <strong style="color: {health_color};">{health_label}</strong> - diperbarui {datetime.now().strftime('%H:%M')}</p>
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
            <span style="color: #FF9F0A;">{instant_waiting} dari {instant_total} pesanan <strong>instant/same-day</strong> ({instant_pct:.0f}%) belum dipacking - 
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
        st.success("✅ Tidak ada alert - semua berjalan normal!")

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
                // Voices belum load - tunggu dan retry
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
            st.info(f"🔇 Snooze aktif - suara dinonaktifkan selama {remaining // 60}m {remaining % 60}d lagi.")
        else:
            st.session_state.voice_snooze_until = None

    # ── Build voice message ──
    voice_msg = ""
    if instant_waiting > 0:
        voice_msg = (f"Perhatian! {instant_waiting} pesanan instant atau same-day belum dipacking. "
                     f"Dahulukan segera sebelum reguler. ")
    elif alerts:
        first_alert = alerts[0]
        voice_msg = f"{first_alert[1]}. {first_alert[2].split(chr(8212))[0].strip().rstrip('.')}. "  # chr(8212) = -
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
            st.caption(f"🔊 Alert sudah diucapkan - klik 'Analisa Ulang' untuk refresh.")

    elif voice_enabled and snooze_active:
        st.caption("🔇 Suara ditunda (snooze).")
    elif voice_enabled and not voice_msg:
        st.caption("✅ Tidak ada alert - semua aman.")

    # ═══════════════════════════════════════════
    # 🔄 AUTO-REFRESH (via JavaScript timer)
    # ═══════════════════════════════════════════
    if voice_enabled and not snooze_active:
        # Inject auto-refresh timer - reload halaman setiap voice_interval detik
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
        st.caption(f"🔄 Auto-refresh aktif - halaman refresh setiap {voice_interval} detik.")

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
    """Render satu tab Handover (REGULER atau INSTANT) - dengan Marketplace filter, unique resi, TTD Elektronik."""
    tipe_label = "🚀 Instant" if tipe_kiriman == "INSTANT" else "📦 Reguler"
    now = datetime.now()

    # ── Filter Baris 1: Kategori + Marketplace ──
    f1, f2 = st.columns(2)
    with f1:
        kat_filter = st.selectbox(
            "Filter Kategori",
            ["Semua", "REGULER", "BESAR"],
            key=f"handover_kat_{tipe_kiriman}",
        )
    with f2:
        mp_list = db.fetch_all(
            "SELECT DISTINCT p.marketplace FROM scan_aktif s "
            "JOIN penjualan p ON s.resi = p.no_resi "
            f"WHERE s.status = 'PACKED' AND s.tipe_kiriman = '{tipe_kiriman}' AND p.marketplace != '' "
            "ORDER BY p.marketplace"
        )
        mp_options = ["Semua Marketplace"] + [m["marketplace"] for m in mp_list]
        mp_filter = st.selectbox("Filter Marketplace", mp_options, key=f"handover_mp_{tipe_kiriman}")

    # Build WHERE clauses
    where = [f"s.tipe_kiriman = '{tipe_kiriman}'", "s.status = 'PACKED'"]
    if kat_filter != "Semua":
        where.append(f"s.kategori = '{kat_filter}'")
    if mp_filter != "Semua Marketplace":
        where.append(f"p.marketplace = '{mp_filter}'")
    where_clause = " AND ".join(where)

    # ── Kurir List (Filtered) ──
    kurir_list = db.fetch_all(
        f"SELECT DISTINCT p.kurir FROM scan_aktif s "
        "JOIN penjualan p ON s.resi = p.no_resi "
        f"WHERE {where_clause} AND p.kurir != '' ORDER BY p.kurir"
    )

    if not kurir_list:
        st.info(f"📭 Belum ada resi PACKED {tipe_label} dengan filter tersebut.")
        return

    kurir_options = ["Semua Kurir"] + [k["kurir"] for k in kurir_list]
    selected_kurir = st.selectbox("Pilih Kurir / Ekspedisi", kurir_options, key=f"handover_kurir_{tipe_kiriman}")

    kurir_where = "" if selected_kurir == "Semua Kurir" else f" AND p.kurir = '{selected_kurir}'"

    # ── Query: GROUP BY resi (1 resi = 1 baris, multi-SKU digabung) ──
    items = db.fetch_all(
        f"SELECT s.id as scan_id, s.waktu, s.tanggal, s.resi, s.kategori, s.keterangan_barang, s.tipe_kiriman, "
        "p.marketplace, p.no_pesanan, "
        "GROUP_CONCAT(p.nama_produk, ' | ') as nama_produk, "
        "p.kurir, p.nama_toko, "
        "GROUP_CONCAT(p.sku_terdeteksi, ', ') as sku_terdeteksi, "
        "SUM(p.qty) as total_qty "
        "FROM scan_aktif s JOIN penjualan p ON s.resi = p.no_resi "
        f"WHERE {where_clause} {kurir_where} "
        "GROUP BY s.resi ORDER BY p.kurir, s.id"
    )

    if not items:
        st.info(f"Tidak ada resi {tipe_label} untuk kurir '{selected_kurir}'.")
        return

    # ── Display Table ──
    df_items = pd.DataFrame([dict(r) for r in items])
    df_items["No"] = range(1, len(items) + 1)
    df_items = df_items.rename(columns={
        "waktu": "Waktu", "tanggal": "Tanggal", "resi": "No Resi",
        "marketplace": "MP", "no_pesanan": "No Pesanan",
        "nama_produk": "Produk", "kurir": "Kurir",
        "nama_toko": "Toko", "sku_terdeteksi": "SKU",
        "kategori": "Kategori", "keterangan_barang": "Keterangan",
        "tipe_kiriman": "Tipe", "total_qty": "Total Qty",
    })

    display_cols = ["No", "Waktu", "No Resi", "Kategori", "Keterangan", "MP", "No Pesanan", "Produk", "SKU", "Total Qty", "Kurir", "Toko"]
    available_cols = [c for c in display_cols if c in df_items.columns]
    st.dataframe(df_items[available_cols], width="stretch", height=400, hide_index=True)

    # ── Summary ──
    unique_resi_count = len(items)
    total_qty_all = sum(r["total_qty"] or 0 for r in items) if "total_qty" in df_items.columns else unique_resi_count
    st.info(
        f"📋 **{unique_resi_count} resi unik** (total {total_qty_all} item) {tipe_label} "
        f"siap diserahkan ke **{selected_kurir}**"
        + (f" | Marketplace: {mp_filter}" if mp_filter != "Semua Marketplace" else "")
    )

    # ── Konfirmasi Instant: sudah diambil kurir ──
    if tipe_kiriman == "INSTANT":
        st.markdown("---")
        st.subheader("✅ Konfirmasi Pengambilan Kurir (Instant)")
        st.caption("Paket Instant otomatis muncul di sini setelah di-scan. Klik **✅ Diambil** atau scan resi untuk konfirmasi.")

        # Mode 1: One-click per resi
        if items:
            st.markdown("**Klik per resi - lebih cepat:**")
            # Show in compact grid with confirm buttons
            for idx, item in enumerate(items):
                c_col1, c_col2, c_col3, c_col4, c_col5 = st.columns([2, 2, 3, 1.5, 1.5])
                with c_col1:
                    st.caption(f"`{item['resi']}`")
                with c_col2:
                    st.caption(item["marketplace"] or "-")
                with c_col3:
                    st.caption((item["nama_produk"] or "-")[:40])
                with c_col4:
                    st.caption(f"{item['nama_toko'] or '-'}")
                with c_col5:
                    if st.button("✅ Diambil", key=f"instant_ambil_{item['resi']}_{idx}"):
                        db.execute("DELETE FROM scan_aktif WHERE resi = ? AND tipe_kiriman = 'INSTANT'", (item["resi"],))
                        db.execute("UPDATE penjualan SET status_pesanan = 'TERKIRIM' WHERE no_resi = ?", (item["resi"],))
                        st.success(f"✅ `{item['resi']}` diserahkan ke kurir - status: TERKIRIM.")
                        st.rerun()

        # Mode 2: Scan/ketik resi (buat yang pakai barcode scanner)
        st.markdown("---")
        st.caption("Atau scan/ketik No Resi (untuk barcode scanner):")
        konfirm_col1, konfirm_col2 = st.columns([3, 1])
        with konfirm_col1:
            konfirm_resi = st.text_input(
                "Scan No Resi",
                placeholder="Scan barcode atau ketik no resi...",
                key=f"konfirm_instant_{tipe_kiriman}",
                label_visibility="collapsed",
            )
        with konfirm_col2:
            if st.button("🔍 Konfirmasi", width="stretch", key=f"konfirm_btn_{tipe_kiriman}"):
                if konfirm_resi.strip():
                    c_clean = Validator.sanitize_resi(konfirm_resi.strip())
                    if c_clean:
                        db.execute("DELETE FROM scan_aktif WHERE resi = ? AND tipe_kiriman = 'INSTANT'", (c_clean,))
                        db.execute("UPDATE penjualan SET status_pesanan = 'TERKIRIM' WHERE no_resi = ?", (c_clean,))
                        st.success(f"✅ `{c_clean}` dikonfirmasi - sudah diambil kurir & status: TERKIRIM.")
                        st.rerun()
                else:
                    st.warning("Masukkan No Resi.")

    # ── Ringkasan per Kurir (jika Semua Kurir) ──
    if selected_kurir == "Semua Kurir":
        st.markdown("---")
        st.subheader("📊 Ringkasan per Kurir / Ekspedisi")
        summary = db.fetch_all(
            f"SELECT p.kurir, COUNT(DISTINCT s.resi) as jml_resi, SUM(p.qty) as jml_item "
            "FROM scan_aktif s JOIN penjualan p ON s.resi = p.no_resi "
            f"WHERE {where_clause} GROUP BY p.kurir ORDER BY jml_resi DESC"
        )
        if summary:
            df_sum = pd.DataFrame([dict(r) for r in summary])
            df_sum = df_sum.rename(columns={"kurir": "Kurir", "jml_resi": "Jml Resi", "jml_item": "Jml Item"})
            st.dataframe(df_sum, width="stretch", hide_index=True)

    # ═══════════════════════════════════════════
    # TTD ELEKTRONIK & PRINT
    # ═══════════════════════════════════════════
    st.markdown("---")
    st.markdown("### ✍️ Serah Terima & Tanda Tangan Elektronik")

    ttd_col1, ttd_col2 = st.columns(2)
    with ttd_col1:
        ttd_op = st.text_input(
            "Nama Operator (Penyerah)",
            value=st.session_state.get("user", {}).get("nama_lengkap", ""),
            key=f"ttd_op_{tipe_kiriman}",
            placeholder="Nama operator...",
        )
    with ttd_col2:
        ttd_eks = st.text_input(
            "Nama Petugas Ekspedisi (Penerima)",
            key=f"ttd_eks_{tipe_kiriman}",
            placeholder="Nama petugas kurir...",
        )
    nama_eks = st.text_input(
        "Nama Perusahaan Ekspedisi",
        value=selected_kurir if selected_kurir != "Semua Kurir" else "",
        key=f"ttd_nama_eks_{tipe_kiriman}",
        placeholder="Nama perusahaan ekspedisi...",
    )

    ttd_col_a, ttd_col_b = st.columns(2)
    with ttd_col_a:
        if st.button("✍️ **Simpan TTD & Konfirmasi Serah Terima**", width="stretch", type="primary",
                     key=f"ttd_simpan_{tipe_kiriman}"):
            if not ttd_op.strip():
                st.error("Nama Operator wajib diisi!")
            elif not ttd_eks.strip():
                st.error("Nama Petugas Ekspedisi wajib diisi!")
            else:
                now_ttd = datetime.now()
                db.execute(
                    "INSERT INTO handover_ttd (kurir, tipe_kiriman, marketplace_filter, kategori_filter, "
                    "jumlah_resi, ttd_operator, ttd_ekspedisi, nama_ekspedisi, waktu_ttd, tanggal_ttd) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        selected_kurir, tipe_kiriman,
                        mp_filter if mp_filter != "Semua Marketplace" else "",
                        kat_filter if kat_filter != "Semua" else "",
                        unique_resi_count,
                        ttd_op.strip(), ttd_eks.strip(), nama_eks.strip(),
                        now_ttd.strftime("%H:%M:%S"), now_ttd.strftime("%d-%m-%Y"),
                    ),
                )
                st.success(
                    f"✅ **Serah Terima Tercatat!**\n\n"
                    f"📦 {unique_resi_count} resi diserahkan oleh **{ttd_op.strip()}** "
                    f"kepada **{ttd_eks.strip()}** ({nama_eks.strip() or selected_kurir})\n"
                    f"🕐 {now_ttd.strftime('%d %B %Y, %H:%M')}"
                )
                st.balloons()
                st.rerun()

    with ttd_col_b:
        if st.button("🖨️ **Cetak / Print Handover**", width="stretch", key=f"ttd_print_{tipe_kiriman}"):
            # Show printable view
            st.markdown("---")
            st.markdown("## 📋 SURAT SERAH TERIMA PAKET")
            st.markdown(f"**iScan Pro By MMA** - Handover {tipe_label}")
            st.markdown(f"Tanggal: **{now.strftime('%d %B %Y')}** | Jam: **{now.strftime('%H:%M')}**")
            st.markdown(f"Kurir/Ekspedisi: **{selected_kurir}**")
            if mp_filter != "Semua Marketplace":
                st.markdown(f"Marketplace: **{mp_filter}**")
            st.markdown(f"Jumlah Resi: **{unique_resi_count}** | Total Item: **{total_qty_all}**")
            st.markdown("---")
            
            # Compact table for print
            print_cols = ["No", "No Resi", "MP", "No Pesanan", "Produk", "SKU", "Total Qty", "Toko"]
            print_avail = [c for c in print_cols if c in df_items.columns]
            st.dataframe(df_items[print_avail], width="stretch", hide_index=True)
            
            st.markdown("---")
            st.markdown("### ✍️ Tanda Tangan")
            p_col1, p_col2 = st.columns(2)
            with p_col1:
                st.markdown(f"**Penyerah (Operator)**\n\n\n\n\n_________________________\n**{ttd_op.strip() or '(Nama Operator)'}**")
            with p_col2:
                st.markdown(f"**Penerima (Ekspedisi)**\n\n\n\n\n_________________________\n**{ttd_eks.strip() or '(Nama Petugas)'}**\n{nama_eks.strip() or '(Ekspedisi)'}")
            
            st.caption("🖨️ Gunakan Ctrl+P untuk mencetak halaman ini sebagai bukti serah terima.")

    # ── Riwayat TTD ──
    with st.expander("📋 Riwayat Serah Terima (TTD Elektronik)", expanded=False):
        ttd_history = db.fetch_all(
            "SELECT * FROM handover_ttd WHERE tipe_kiriman = ? ORDER BY id DESC LIMIT 20",
            (tipe_kiriman,),
        )
        if ttd_history:
            df_ttd = pd.DataFrame([dict(r) for r in ttd_history])
            df_ttd = df_ttd.rename(columns={
                "tanggal_ttd": "Tanggal", "waktu_ttd": "Waktu",
                "kurir": "Kurir", "tipe_kiriman": "Tipe",
                "jumlah_resi": "Jml Resi",
                "ttd_operator": "Operator", "ttd_ekspedisi": "Petugas Ekspedisi",
                "nama_ekspedisi": "Ekspedisi",
                "marketplace_filter": "Marketplace",
            })
            st.dataframe(df_ttd[["Tanggal", "Waktu", "Kurir", "Tipe", "Marketplace", "Jml Resi", "Operator", "Petugas Ekspedisi", "Ekspedisi"]],
                        width="stretch", hide_index=True)
        else:
            st.caption("Belum ada riwayat TTD.")

    # ── Export ──
    st.markdown("---")
    kurir_label = selected_kurir.replace(" ", "_") if selected_kurir != "Semua Kurir" else "Semua"
    tipe_file = "Instant" if tipe_kiriman == "INSTANT" else "Reguler"
    filename = f"Handover_{tipe_file}_{kurir_label}_{now.strftime('%d-%m-%Y_%H%M%S')}.xlsx"
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

        # Summary per expedition - mencakup semua status
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


# ==================== LOGIN PAGE ====================
def render_login():
    """Render the login form page."""
    # Hide sidebar on login page
    st.markdown("""
    <style>
        [data-testid="stSidebar"] { display: none; }
        [data-testid="stSidebarCollapsedControl"] { display: none; }
    </style>
    """, unsafe_allow_html=True)

    col_center = st.columns([1, 2, 1])
    with col_center[1]:
        st.markdown("<br><br>", unsafe_allow_html=True)

        # Logo
        st.markdown("""
        <div style="text-align:center;margin-bottom:30px;">
            <span style="font-size:42px;font-weight:800;color:#FFFFFF;">iScan</span>
            <span style="font-size:32px;font-weight:700;color:#0A84FF;">Pro</span>
            <br><span style="font-size:14px;color:#AEAEB2;">By MMA - Mitra Mulia Abadi</span>
        </div>
        """, unsafe_allow_html=True)

        # Login card
        with st.container(border=True):
            st.markdown("### 🔐 Login")
            username = st.text_input("Username", placeholder="Masukkan username", key="login_username")
            password = st.text_input("Password", type="password", placeholder="Masukkan password", key="login_password")

            col_btn, _ = st.columns([1, 2])
            with col_btn:
                login_btn = st.button("🔓 Masuk", type="primary", width="stretch", key="login_btn")

            if login_btn:
                if not username.strip() or not password.strip():
                    st.error("Username dan password harus diisi!")
                else:
                    db = st.session_state.db
                    user = authenticate_user(db, username.strip(), password.strip())
                    if user:
                        # Generate persistent auth token
                        token = generate_auth_token(db, user["id"])
                        st.session_state.authenticated = True
                        st.session_state.user = user
                        st.query_params["auth"] = token
                        logging.info(f"[AUTH] Login SUCCESS: {user['username']}")
                        st.rerun()
                    else:
                        st.error("❌ Username atau password salah, atau akun tidak aktif.")

        st.markdown("""
        <div style="text-align:center;margin-top:20px;color:#636366;font-size:13px;">
            <p>Hubungi admin jika lupa password.</p>
        </div>
        """, unsafe_allow_html=True)


# ==================== OPEX (Operational Expenses) ====================
# ── Tipe OPEX ──
OPEX_TIPE = ["📦 Biaya Packing Variable (Harian)", "🏢 OPEX Tetap (Bulanan)"]

# ── Kategori per Tipe ──
OPEX_VARIABLE_CATEGORIES = [
    "Bubble Wrap", "Kardus", "Lakban / Selotip", "Bensin / Transport Harian",
    "Packing Lainnya",
]

OPEX_TETAP_CATEGORIES = [
    "Gaji / Upah", "Internet", "Listrik", "Air", "Sewa Tempat",
    "Maintenance", "ATK", "Lainnya",
]

# ── Legacy (backward compatible, digabung untuk filter) ──
OPEX_CATEGORIES = OPEX_VARIABLE_CATEGORIES + OPEX_TETAP_CATEGORIES


def _generate_opex_faktur(db) -> str:
    """Generate auto-incrementing faktur number for OPEX: OPEX-YYYYMMDD-NNN."""
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"OPEX-{today}-"
    existing = db.fetch_one(
        "SELECT no_faktur FROM opex WHERE no_faktur LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{prefix}%",),
    )
    if existing and existing["no_faktur"]:
        last_num = int(existing["no_faktur"].split("-")[-1])
        return f"{prefix}{last_num + 1:03d}"
    return f"{prefix}001"


def render_opex_input():
    """Render form input biaya operasional (OPEX) - Variable Harian & Tetap Bulanan."""
    db = st.session_state.db

    st.subheader("📝 Input Biaya Operasional (OPEX)")
    st.caption("Pisahkan biaya packing variable harian (bubble, kardus, lakban, bensin) dan OPEX tetap bulanan (gaji, listrik, internet, dll).")

    # ── Init session state ──
    if "opex_cart" not in st.session_state:
        st.session_state.opex_cart = []
    if "opex_supplier" not in st.session_state:
        st.session_state.opex_supplier = ""
    if "opex_faktur" not in st.session_state:
        st.session_state.opex_faktur = _generate_opex_faktur(db)
    if "opex_tipe" not in st.session_state:
        st.session_state.opex_tipe = "📦 Biaya Packing Variable (Harian)"
    if "opex_kategori" not in st.session_state:
        st.session_state.opex_kategori = OPEX_VARIABLE_CATEGORIES[0]

    cart = st.session_state.opex_cart

    # ── Tipe OPEX ──
    st.markdown("### ⚡ Tipe Biaya")
    tipe_col1, tipe_col2 = st.columns([2, 2])
    with tipe_col1:
        opex_tipe = st.radio(
            "Pilih Tipe OPEX",
            OPEX_TIPE,
            index=0 if st.session_state.opex_tipe.startswith("📦") else 1,
            key="opex_tipe_radio",
            horizontal=True,
            help="📦 Variable = biaya harian (bubble, kardus, bensin) | 🏢 Tetap = biaya bulanan (gaji, listrik, internet)",
        )
        st.session_state.opex_tipe = opex_tipe
    with tipe_col2:
        if opex_tipe.startswith("📦"):
            st.info("📦 **Variable Harian** - biaya packing & operasional yang berubah tiap hari.")
        else:
            st.info("🏢 **Tetap Bulanan** - biaya rutin yang dibayar per bulan.")

    is_variable = opex_tipe.startswith("📦")

    # ── Header ──
    col_h1, col_h2, col_h3 = st.columns([2, 2, 1])
    with col_h1:
        cat_list = OPEX_VARIABLE_CATEGORIES if is_variable else OPEX_TETAP_CATEGORIES
        # Ensure kategori is valid for current tipe
        if st.session_state.opex_kategori not in cat_list:
            st.session_state.opex_kategori = cat_list[0]
        kategori = st.selectbox("Kategori *", cat_list,
                                index=cat_list.index(st.session_state.opex_kategori) if st.session_state.opex_kategori in cat_list else 0,
                                key="opex_kategori_select")
        st.session_state.opex_kategori = kategori
    with col_h2:
        faktur = st.text_input("No Referensi", value=st.session_state.opex_faktur, key="opex_faktur_input",
                               help="Nomor faktur/referensi/invoice")
        st.session_state.opex_faktur = faktur
    with col_h3:
        st.write("")
        st.write("")
        if st.button("🔄 New Ref", width="stretch"):
            st.session_state.opex_faktur = _generate_opex_faktur(db)
            st.session_state.opex_cart = []
            st.rerun()

    st.markdown("---")

    # ── Add Item ──
    st.markdown("### ➕ Tambah Biaya")
    col_i1, col_i2, col_i3, col_i4, col_i5 = st.columns([3, 1, 1, 1, 1])
    with col_i1:
        desc_placeholder = "Bayar listrik bulan Juli..." if not is_variable else "Bubble wrap 5 roll..."
        deskripsi = st.text_input("Deskripsi", placeholder=desc_placeholder, key="opex_desc")
    with col_i2:
        supplier = st.text_input("Supplier/Vendor", placeholder="PLN/Telkom...", key="opex_supplier_input")
    with col_i3:
        qty = st.number_input("Qty", min_value=1, value=1, step=1, key="opex_qty")
    with col_i4:
        default_satuan = "bulan" if not is_variable else "pcs"
        satuan_list = ["bulan", "pcs", "liter", "kg", "paket", "unit", "kali", "roll", "buah"]
        satuan = st.selectbox("Satuan", satuan_list,
                              index=satuan_list.index(default_satuan) if default_satuan in satuan_list else 1,
                              key="opex_satuan")
    with col_i5:
        harga_satuan = st.number_input("Harga/Unit", min_value=0, value=0, step=10000, key="opex_harga")

    if st.button("➕ Tambah ke Daftar", type="primary", width="stretch"):
        if not deskripsi.strip():
            st.error("Deskripsi wajib diisi!")
        elif harga_satuan <= 0:
            st.error("Harga harus > 0!")
        else:
            cart.append({
                "kategori": kategori,
                "deskripsi": deskripsi.strip(),
                "supplier": supplier.strip() or "-",
                "qty": qty,
                "satuan": satuan,
                "harga_satuan": harga_satuan,
                "total_harga": qty * harga_satuan,
                "tipe": "VARIABLE" if is_variable else "TETAP",
            })
            st.success(f"✅ '{deskripsi}' ditambahkan!")
            st.rerun()

    # ── OPEX Cart Table ──
    st.markdown("---")
    st.markdown("### 📋 Daftar Biaya")

    if not cart:
        st.info("Belum ada biaya ditambahkan.")
    else:
        df_cart = pd.DataFrame(cart)
        df_cart["No"] = range(1, len(cart) + 1)
        df_cart["Harga/Unit"] = df_cart["harga_satuan"].apply(lambda x: f"Rp {x:,.0f}")
        df_cart["Total"] = df_cart["total_harga"].apply(lambda x: f"Rp {x:,.0f}")
        df_cart["Tipe"] = df_cart["tipe"].apply(lambda x: "📦 Variable" if x == "VARIABLE" else "🏢 Tetap")
        df_display = df_cart[["No", "Tipe", "kategori", "deskripsi", "supplier", "qty", "satuan", "Harga/Unit", "Total"]]
        df_display = df_display.rename(columns={
            "kategori": "Kategori", "deskripsi": "Deskripsi",
            "supplier": "Supplier", "qty": "Qty", "satuan": "Satuan",
        })
        st.dataframe(df_display, width="stretch", hide_index=True)

        var_total = sum(item["total_harga"] for item in cart if item.get("tipe") == "VARIABLE")
        tetap_total = sum(item["total_harga"] for item in cart if item.get("tipe") == "TETAP")
        grand_total = sum(item["total_harga"] for item in cart)

        t_col1, t_col2, t_col3 = st.columns(3)
        with t_col1:
            st.metric("📦 Variable", f"Rp {var_total:,.0f}")
        with t_col2:
            st.metric("🏢 Tetap", f"Rp {tetap_total:,.0f}")
        with t_col3:
            st.metric("💰 Total OPEX", f"Rp {grand_total:,.0f}")
        st.caption(f"📋 {len(cart)} item dalam daftar")

        # Remove item
        col_r1, col_r2 = st.columns([3, 1])
        with col_r1:
            remove_idx = st.selectbox(
                "Hapus item",
                [f"{i+1}. [{item.get('tipe','?')}] {item['deskripsi']} ({item['kategori']}) - Rp {item['total_harga']:,.0f}" for i, item in enumerate(cart)],
                key="opex_remove",
            )
        with col_r2:
            if st.button("🗑️ Hapus", width="stretch"):
                idx = int(remove_idx.split(".")[0]) - 1
                cart.pop(idx)
                st.rerun()

        # ── Save ──
        st.markdown("---")
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            ket = st.text_input("Keterangan", placeholder="Catatan tambahan...", key="opex_ket")
        with col_s2:
            metode_bayar = st.selectbox("Metode Bayar", ["Transfer", "Cash", "Kontrabon"], key="opex_metode")
        with col_s3:
            st.write("")
            st.write("")
            if st.button("💾 Simpan OPEX", type="primary", width="stretch"):
                if not faktur.strip():
                    st.error("No Referensi wajib diisi!")
                else:
                    today_str = datetime.now().strftime("%d-%m-%Y")
                    saved = 0
                    for item in cart:
                        db.execute(
                            """INSERT INTO opex (kategori, deskripsi, supplier, qty, satuan,
                               harga_satuan, total_harga, tanggal, no_faktur,
                               metode_bayar, status_bayar, keterangan, tipe)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (item["kategori"], item["deskripsi"], item["supplier"],
                             item["qty"], item["satuan"], item["harga_satuan"],
                             item["total_harga"], today_str, faktur.strip(),
                             metode_bayar, "PENDING", ket.strip(), item.get("tipe", "VARIABLE")),
                        )
                        saved += 1
                    st.success(f"✅ {saved} biaya OPEX tersimpan! Status: PENDING (menunggu konfirmasi Finance)")
                    st.session_state.opex_cart = []
                    st.session_state.opex_faktur = _generate_opex_faktur(db)
                    st.rerun()


def render_opex_history():
    """Render riwayat OPEX."""
    db = st.session_state.db

    st.subheader("📋 Riwayat Biaya OPEX")

    total_opex = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM opex")
    pending_opex = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE status_bayar = 'PENDING'")
    total_trx = db.fetch_one("SELECT COUNT(DISTINCT no_faktur) as cnt FROM opex")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📋 Total Transaksi", total_trx["cnt"] if total_trx else 0)
    with col2:
        st.metric("💰 Total OPEX", f"Rp {total_opex['total']:,.0f}" if total_opex else "Rp 0")
    with col3:
        st.metric("📌 Pending", f"Rp {pending_opex['total']:,.0f}" if pending_opex else "Rp 0")

    st.markdown("---")

    # Per kategori
    st.markdown("### 📊 Breakdown per Kategori & Tipe")
    kat_rows = db.fetch_all(
        "SELECT tipe, kategori, COUNT(*) as cnt, SUM(total_harga) as total FROM opex GROUP BY tipe, kategori ORDER BY tipe, total DESC"
    )
    if kat_rows:
        df_kat = pd.DataFrame([dict(r) for r in kat_rows])
        df_kat["Tipe"] = df_kat["tipe"].apply(lambda x: "📦 Variable" if x == "VARIABLE" else "🏢 Tetap")
        df_kat["Total"] = df_kat["total"].apply(lambda x: f"Rp {x:,.0f}")
        df_kat = df_kat.rename(columns={"kategori": "Kategori", "cnt": "Jumlah", "total": "_total"})
        st.dataframe(df_kat[["Tipe", "Kategori", "Jumlah", "Total"]], width="stretch", hide_index=True)

    # Detail
    st.markdown("---")
    st.markdown("### 📋 Detail Transaksi OPEX")
    faktur_rows = db.fetch_all(
        "SELECT no_faktur, tanggal, tipe, kategori, metode_bayar, status_bayar, "
        "COUNT(*) as items, SUM(total_harga) as total "
        "FROM opex GROUP BY no_faktur ORDER BY created_at DESC LIMIT 100"
    )
    if faktur_rows:
        df_f = pd.DataFrame([dict(r) for r in faktur_rows])
        df_f["Tipe"] = df_f["tipe"].apply(lambda x: "📦 Var" if x == "VARIABLE" else "🏢 Tetap")
        df_f["Total"] = df_f["total"].apply(lambda x: f"Rp {x:,.0f}")
        df_f = df_f.rename(columns={
            "no_faktur": "No Ref", "tanggal": "Tanggal", "kategori": "Kategori",
            "metode_bayar": "Metode Bayar", "status_bayar": "Status Bayar",
            "items": "Item", "total": "_total",
        })
        st.dataframe(df_f[["No Ref", "Tanggal", "Tipe", "Kategori", "Metode Bayar", "Status Bayar", "Item", "Total"]],
                     width="stretch", hide_index=True)


def render_opex_dashboard():
    """Dashboard ringkasan OPEX - Variable Harian vs Tetap Bulanan."""
    db = st.session_state.db
    st.subheader("📊 Dashboard Biaya Operasional")
    st.caption("Biaya Packing Variable (harian) + OPEX Tetap (bulanan) - masuk ke perhitungan laba rugi.")

    # ── Totals ──
    total_var = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE tipe = 'VARIABLE'")
    total_tetap = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE tipe = 'TETAP'")
    total_all = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM opex")
    pending = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE status_bayar = 'PENDING'")
    this_month = datetime.now().strftime("%m-%Y")

    var_bulan = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE tipe = 'VARIABLE' AND tanggal LIKE ?",
        (f"%{this_month}%",),
    )
    tetap_bulan = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as total FROM opex WHERE tipe = 'TETAP' AND tanggal LIKE ?",
        (f"%{this_month}%",),
    )

    # ── Summary Cards ──
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("📦 Variable (All-Time)", f"Rp {total_var['total']:,.0f}" if total_var else "Rp 0")
    with col2:
        st.metric("🏢 Tetap (All-Time)", f"Rp {total_tetap['total']:,.0f}" if total_tetap else "Rp 0")
    with col3:
        st.metric("💰 Total OPEX", f"Rp {total_all['total']:,.0f}" if total_all else "Rp 0")
    with col4:
        st.metric("📌 Pending Bayar", f"Rp {pending['total']:,.0f}" if pending else "Rp 0")
    with col5:
        st.metric("📅 Variable Bulan Ini", f"Rp {var_bulan['total']:,.0f}" if var_bulan else "Rp 0")
    with col6:
        st.metric("📅 Tetap Bulan Ini", f"Rp {tetap_bulan['total']:,.0f}" if tetap_bulan else "Rp 0")

    st.markdown("---")

    # ── Variable vs Tetap breakdown ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("### 📦 Biaya Packing Variable")
        var_kat = db.fetch_all(
            "SELECT kategori, SUM(total_harga) as total FROM opex WHERE tipe = 'VARIABLE' GROUP BY kategori ORDER BY total DESC"
        )
        if var_kat:
            for r in var_kat:
                pct = (r["total"] / total_var["total"] * 100) if total_var and total_var["total"] > 0 else 0
                st.progress(min(pct / 100, 1.0), text=f"{r['kategori']}: Rp {r['total']:,.0f} ({pct:.1f}%)")
        else:
            st.caption("Belum ada biaya variable.")

    with col_right:
        st.markdown("### 🏢 OPEX Tetap Bulanan")
        tetap_kat = db.fetch_all(
            "SELECT kategori, SUM(total_harga) as total FROM opex WHERE tipe = 'TETAP' GROUP BY kategori ORDER BY total DESC"
        )
        if tetap_kat:
            for r in tetap_kat:
                pct = (r["total"] / total_tetap["total"] * 100) if total_tetap and total_tetap["total"] > 0 else 0
                st.progress(min(pct / 100, 1.0), text=f"{r['kategori']}: Rp {r['total']:,.0f} ({pct:.1f}%)")
        else:
            st.caption("Belum ada biaya tetap.")

    # ── Monthly trend ──
    st.markdown("---")
    st.markdown("### 📈 Tren Bulanan (6 Bulan Terakhir)")
    monthly_rows = db.fetch_all(
        "SELECT SUBSTR(tanggal, 4, 7) as bulan, tipe, SUM(total_harga) as total "
        "FROM opex GROUP BY bulan, tipe ORDER BY bulan DESC LIMIT 12"
    )
    if monthly_rows:
        df_monthly = pd.DataFrame([dict(r) for r in monthly_rows])
        df_monthly["Tipe"] = df_monthly["tipe"].apply(lambda x: "📦 Variable" if x == "VARIABLE" else "🏢 Tetap")
        df_monthly["Total"] = df_monthly["total"].apply(lambda x: f"Rp {x:,.0f}")
        df_monthly = df_monthly.rename(columns={"bulan": "Bulan", "total": "_total"})
        st.dataframe(df_monthly[["Bulan", "Tipe", "Total"]], width="stretch", hide_index=True)


# ==================== FINANCE ====================
def generate_finance_pdf(db, fee_map, biaya_per_resi, start_date, end_date):
    """Generate PDF laporan keuangan lengkap."""
    from fpdf import FPDF
    import tempfile

    today = datetime.now()
    tgl_list = []
    d = start_date
    while d <= end_date:
        tgl_list.append(d.strftime("%d-%m-%Y"))
        d += timedelta(days=1)

    tempat = ",".join(["?" for _ in tgl_list]) if tgl_list else ""

    # ═══ QUERY DATA ═══
    # Sales PACKED
    sales_rows = db.fetch_all(
        f"SELECT p.total_harga, p.marketplace, p.no_resi, p.sku_terdeteksi, p.qty, s.tanggal "
        f"FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
        f"WHERE s.status = 'PACKED' AND s.tanggal IN ({tempat}) ORDER BY s.tanggal",
        tgl_list,
    ) if tgl_list else []

    gross = sum(r["total_harga"] or 0 for r in sales_rows)
    resi_unik = set(r["no_resi"] for r in sales_rows if r["no_resi"])
    fee_mp = sum((r["total_harga"] or 0) * fee_map.get(r["marketplace"] or "Lainnya", 0.05) for r in sales_rows)
    biaya = len(resi_unik) * biaya_per_resi

    # Modal
    skus = set(r["sku_terdeteksi"] for r in sales_rows if r["sku_terdeteksi"])
    sku_h = {}
    if skus:
        ph = ",".join(["?" for _ in skus])
        for r in db.fetch_all(f"SELECT kode_sku, harga_beli FROM sku WHERE kode_sku IN ({ph})", list(skus)):
            sku_h[r["kode_sku"]] = r["harga_beli"] or 0
    modal = sum(sku_h.get(r["sku_terdeteksi"], 0) * (r["qty"] or 1) for r in sales_rows)

    # Klaim
    klaim = db.fetch_one(
        f"SELECT COALESCE(SUM(nominal_klaim), 0) as tot FROM retur_klaim WHERE status='KLAIM' AND status_klaim='BERHASIL' AND tanggal IN ({tempat})",
        tgl_list,
    ) if tgl_list else None
    klaim_val = klaim["tot"] if klaim else 0

    # OPEX + Pembelian
    opex = db.fetch_one(f"SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE status_bayar='LUNAS' AND tanggal IN ({tempat})", tgl_list) if tgl_list else None
    pemb = db.fetch_one(f"SELECT COALESCE(SUM(total_harga), 0) as tot FROM pembelian WHERE status_bayar='LUNAS' AND tanggal IN ({tempat})", tgl_list) if tgl_list else None
    opex_val = opex["tot"] if opex else 0
    pemb_val = pemb["tot"] if pemb else 0

    income = gross + klaim_val
    expense = fee_mp + biaya + modal + opex_val + pemb_val
    net = income - expense
    margin = (net / income * 100) if income > 0 else 0

    # Pencairan
    cair_all = db.fetch_one("SELECT COALESCE(SUM(jumlah), 0) as tot FROM pencairan")
    cair_val = cair_all["tot"] if cair_all else 0

    # Inventory
    inv = db.fetch_one("SELECT COUNT(*) as cnt, COALESCE(SUM(stok * harga_beli), 0) as tot FROM sku")
    inv_cnt = inv["cnt"] if inv else 0
    inv_val = inv["tot"] if inv else 0

    # Health score (simplified)
    health = 100
    if margin < 0: health -= 30
    elif margin < 10: health -= 15
    elif margin < 20: health -= 5
    missing_modal = db.fetch_one("SELECT COUNT(*) as cnt FROM sku WHERE harga_beli IS NULL OR harga_beli = 0")
    if missing_modal and inv_cnt > 0 and missing_modal["cnt"] / inv_cnt > 0.3: health -= 15
    health = max(0, min(100, health))
    health_label = "SEHAT" if health >= 80 else ("HATI-HATI" if health >= 50 else "KRITIS")

    # Daily breakdown
    daily_data = {}
    for r in sales_rows:
        tgl = r["tanggal"]
        if tgl not in daily_data:
            daily_data[tgl] = {"sales": 0, "resi": set(), "fee": 0, "modal": 0}
        daily_data[tgl]["sales"] += r["total_harga"] or 0
        if r["no_resi"]: daily_data[tgl]["resi"].add(r["no_resi"])

    for tgl in daily_data:
        daily_data[tgl]["fee"] = daily_data[tgl]["sales"] * 0.05
        daily_data[tgl]["biaya"] = len(daily_data[tgl]["resi"]) * biaya_per_resi

    # ═══ BUILD PDF ═══
    pdf = FPDF()
    pdf.add_page()
    
    # Font
    pdf.set_auto_page_break(auto=True, margin=15)

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "iScan Pro By MMA", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Laporan Keuangan Lengkap", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Periode: {start_date.strftime('%d %B %Y')} - {end_date.strftime('%d %B %Y')}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 6, f"Dicetak: {today.strftime('%d %B %Y, %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    # Health Score
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, f"Skor Kesehatan Keuangan: {health}/100 - {health_label}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Summary Table
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Ringkasan Keuangan", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    
    summary_items = [
        ("Total Penjualan (Gross)", f"Rp {gross:,.0f}"),
        ("Klaim Berhasil", f"Rp {klaim_val:,.0f}"),
        ("Total Income", f"Rp {income:,.0f}"),
        ("Fee Marketplace", f"Rp {fee_mp:,.0f}"),
        ("Biaya / Resi", f"Rp {biaya:,.0f}"),
        ("Harga Modal (HPP)", f"Rp {modal:,.0f}"),
        ("Biaya OPEX", f"Rp {opex_val:,.0f}"),
        ("Pembelian SKU", f"Rp {pemb_val:,.0f}"),
        ("Total Expenses", f"Rp {expense:,.0f}"),
        ("NET PROFIT", f"Rp {net:,.0f} ({margin:.1f}% margin)"),
        ("Pencairan (All-Time)", f"Rp {cair_val:,.0f}"),
        ("Nilai Inventaris", f"Rp {inv_val:,.0f} ({inv_cnt} SKU)"),
    ]
    for label, value in summary_items:
        pdf.set_font("Helvetica", "B" if "NET PROFIT" in label else "", 10)
        pdf.cell(90, 6, label)
        pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Daily Cashflow Table
    if daily_data:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, "Cashflow Harian", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 9)
        col_w = [30, 40, 40, 40, 40]
        headers = ["Tanggal", "Penjualan", "Fee+Biaya", "Modal Est.", "Net"]
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], 6, h, border=1, align="C")
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 9)
        for tgl in sorted(daily_data.keys()):
            d = daily_data[tgl]
            d_net = d["sales"] - d["fee"] - d["biaya"] - (d["sales"] * 0.4)  # rough modal
            pdf.cell(col_w[0], 6, tgl, border=1)
            pdf.cell(col_w[1], 6, f"{d['sales']:,.0f}", border=1, align="R")
            pdf.cell(col_w[2], 6, f"{(d['fee']+d['biaya']):,.0f}", border=1, align="R")
            pdf.cell(col_w[3], 6, f"{d['sales']*0.4:,.0f}", border=1, align="R")
            pdf.cell(col_w[4], 6, f"{d_net:,.0f}", border=1, align="R")
            pdf.ln()
        pdf.ln(4)

    # Per Marketplace
    mp_data = {}
    for r in sales_rows:
        mp = r["marketplace"] or "Lainnya"
        if mp not in mp_data:
            mp_data[mp] = {"gross": 0, "count": 0}
        mp_data[mp]["gross"] += r["total_harga"] or 0
        mp_data[mp]["count"] += 1

    if mp_data:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, "Per Marketplace", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 9)
        for i, h in enumerate(["Marketplace", "Penjualan", "Pesanan", "Fee %", "Fee (Rp)"]):
            pdf.cell([35, 45, 25, 25, 50][i], 6, h, border=1, align="C" if i > 0 else "L")
        pdf.ln()
        pdf.set_font("Helvetica", "", 9)
        for mp, d in sorted(mp_data.items(), key=lambda x: -x[1]["gross"]):
            mp_fee = d["gross"] * fee_map.get(mp, 0.05)
            pdf.cell(35, 6, mp, border=1)
            pdf.cell(45, 6, f"Rp {d['gross']:,.0f}", border=1, align="R")
            pdf.cell(25, 6, str(d["count"]), border=1, align="C")
            pdf.cell(25, 6, f"{fee_map.get(mp,0.05)*100:.0f}%", border=1, align="C")
            pdf.cell(50, 6, f"Rp {mp_fee:,.0f}", border=1, align="R")
            pdf.ln()

    # Footer
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, "iScan Pro By MMA - Laporan Keuangan Otomatis", align="C")
    pdf.cell(0, 5, "Data diambil dari pesanan PACKED, OPEX, Pembelian, dan Pencairan.", new_x="LMARGIN", new_y="NEXT", align="C")

    # Save to temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(tmp.name)
    return tmp.name


def render_finance_dashboard():
    """Dashboard Finance Komprehensif - Kesehatan Cashflow, Profit, Aset, Grafik, & AI Audit."""
    db = st.session_state.db
    today = datetime.now()
    month_start = today.replace(day=1).strftime("%d-%m-%Y")
    today_str = today.strftime("%d-%m-%Y")

    st.subheader("💳 Dashboard Finance - Kesehatan Keuangan")
    st.caption(f"Analisa & rekomendasi keuangan per **{today.strftime('%d %B %Y, %H:%M')}**")

    # ═══════════════════════════════════
    # SETTINGS LOAD
    # ═══════════════════════════════════
    fee_shopee = float(_get_setting(db, "fee_shopee", "5.0"))
    fee_tiktok = float(_get_setting(db, "fee_tiktok", "4.0"))
    fee_lazada = float(_get_setting(db, "fee_lazada", "4.5"))
    biaya_per_resi = int(_get_setting(db, "biaya_per_resi", "1250"))
    fee_map = {"Shopee": fee_shopee / 100.0, "TikTok": fee_tiktok / 100.0, "Lazada": fee_lazada / 100.0}

    # ═══════════════════════════════════
    # MONTHLY METRICS
    # ═══════════════════════════════════
    # Penjualan bulan ini (PACKED)
    bln_sales = db.fetch_all(
        "SELECT p.total_harga, p.marketplace, p.no_resi, p.sku_terdeteksi, p.qty "
        "FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
        "WHERE s.status = 'PACKED' AND s.tanggal >= ?",
        (month_start,),
    )
    bln_gross = sum(r["total_harga"] or 0 for r in bln_sales)
    bln_resi = len(set(r["no_resi"] for r in bln_sales if r["no_resi"]))
    bln_fee = sum((r["total_harga"] or 0) * fee_map.get(r["marketplace"] or "Lainnya", 0.05) for r in bln_sales)
    bln_biaya = bln_resi * biaya_per_resi

    # SKU Modal lookup
    bln_skus = set(r["sku_terdeteksi"] for r in bln_sales if r["sku_terdeteksi"])
    sku_harga = {}
    if bln_skus:
        ph = ",".join(["?" for _ in bln_skus])
        for r in db.fetch_all(f"SELECT kode_sku, harga_beli FROM sku WHERE kode_sku IN ({ph})", list(bln_skus)):
            sku_harga[r["kode_sku"]] = r["harga_beli"] or 0
    bln_modal = sum(sku_harga.get(r["sku_terdeteksi"], 0) * (r["qty"] or 1) for r in bln_sales)

    bln_klaim = db.fetch_one(
        "SELECT COALESCE(SUM(nominal_klaim), 0) as tot FROM retur_klaim "
        "WHERE status='KLAIM' AND status_klaim='BERHASIL' AND tanggal >= ?", (month_start,),
    )
    bln_klaim_val = bln_klaim["tot"] if bln_klaim else 0

    # OPEX + Pembelian bulan ini (LUNAS) - split Variable vs Tetap
    bln_opex = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE status_bayar='LUNAS' AND tanggal >= ?",
        (month_start,),
    )
    bln_opex_val = bln_opex["tot"] if bln_opex else 0
    bln_opex_var = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE tipe = 'VARIABLE' AND status_bayar='LUNAS' AND tanggal >= ?",
        (month_start,),
    )
    bln_opex_var_val = bln_opex_var["tot"] if bln_opex_var else 0
    bln_opex_tetap = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE tipe = 'TETAP' AND status_bayar='LUNAS' AND tanggal >= ?",
        (month_start,),
    )
    bln_opex_tetap_val = bln_opex_tetap["tot"] if bln_opex_tetap else 0
    bln_pemb = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM pembelian WHERE status_bayar='LUNAS' AND tanggal >= ?",
        (month_start,),
    )
    bln_pemb_val = bln_pemb["tot"] if bln_pemb else 0

    bln_income = bln_gross + bln_klaim_val
    bln_expense = bln_fee + bln_biaya + bln_modal + bln_opex_val + bln_pemb_val
    bln_net = bln_income - bln_expense
    bln_margin = (bln_net / bln_income * 100) if bln_income > 0 else 0

    # Inventory value
    inv_val = db.fetch_one("SELECT COALESCE(SUM(stok * harga_beli), 0) as tot FROM sku")
    inv_total = inv_val["tot"] if inv_val else 0
    inv_sku_count = db.fetch_one("SELECT COUNT(*) as cnt FROM sku")
    inv_count = inv_sku_count["cnt"] if inv_sku_count else 0
    inv_missing_modal = db.fetch_one("SELECT COUNT(*) as cnt FROM sku WHERE harga_beli IS NULL OR harga_beli = 0")
    inv_no_modal = inv_missing_modal["cnt"] if inv_missing_modal else 0

    # Outstanding: kewajiban pending
    pending_sku = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM pembelian WHERE status_bayar IN ('PENDING', 'KONTRA BON')")
    pending_opex = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE status_bayar = 'PENDING'")
    outstanding = (pending_sku["tot"] if pending_sku else 0) + (pending_opex["tot"] if pending_opex else 0)

    # Saldo Toko (all-time)
    all_net = _hitung_all_time_net(db, fee_map, biaya_per_resi)
    all_cair = db.fetch_one("SELECT COALESCE(SUM(jumlah), 0) as tot FROM pencairan")
    saldo_toko = all_net - (all_cair["tot"] if all_cair else 0)

    # ═══════════════════════════════════
    # HEALTH SCORE (0-100)
    # ═══════════════════════════════════
    health_score = 100
    alerts = []
    recommendations = []

    # Profit margin check
    if bln_margin < 0:
        health_score -= 30
        alerts.append(f"🔴 **RUGI!** Net Profit bulan ini negatif: Rp {bln_net:,.0f}")
        recommendations.append("🚨 **URGENT**: Evaluasi semua biaya. Profit margin negatif - bisnis merugi.")
    elif bln_margin < 10:
        health_score -= 15
        alerts.append(f"🟡 Margin profit rendah: {bln_margin:.1f}% (target minimal 10%)")
        recommendations.append("📉 **Margin Tipis**: Pertimbangkan menaikkan harga jual atau menurunkan biaya operasional.")
    elif bln_margin < 20:
        health_score -= 5
        alerts.append(f"🟢 Margin profit cukup: {bln_margin:.1f}%")
    else:
        alerts.append(f"🟢 Margin profit sehat: {bln_margin:.1f}%")

    # Inventory missing modal
    if inv_no_modal > inv_count * 0.3:
        health_score -= 15
        alerts.append(f"🔴 {inv_no_modal}/{inv_count} SKU belum punya Harga Modal ({inv_no_modal/inv_count*100:.0f}%)")
        recommendations.append("📋 **Lengkapi Harga Modal**: Banyak SKU tanpa HPP - laba/rugi tidak akurat. Upload massal di Manajemen SKU.")
    elif inv_no_modal > 0:
        health_score -= 5
        recommendations.append(f"📝 **{inv_no_modal} SKU** belum ada Harga Modal. Lengkapi agar perhitungan akurat.")

    # Outstanding check
    if outstanding > bln_income * 0.5:
        health_score -= 10
        alerts.append(f"🔴 Kewajiban pending Rp {outstanding:,.0f} - >50% dari income bulanan")
        recommendations.append(f"⚠️ **Kewajiban Tinggi**: Segera lunasi tagihan pending Rp {outstanding:,.0f}.")
    elif outstanding > 0:
        alerts.append(f"📌 Kewajiban pending: Rp {outstanding:,.0f}")

    # Inventory turnover (sales vs stock value)
    if inv_total > 0 and bln_modal > 0:
        turnover = bln_modal / inv_total
        if turnover < 0.1:
            health_score -= 5
            recommendations.append("📦 **Stok Menumpuk**: Perputaran stok rendah. Evaluasi pembelian atau promo untuk mengurangi stok.")
        elif turnover > 0.5:
            alerts.append("🟢 Perputaran stok baik - penjualan aktif.")

    # Expense ratio
    if bln_income > 0:
        exp_ratio = bln_expense / bln_income
        if exp_ratio > 0.95:
            health_score -= 10
            recommendations.append("⚠️ **Expense Ratio >95%**: Hampir semua pendapatan habis untuk biaya. Kurangi pengeluaran.")
        elif exp_ratio > 0.8:
            recommendations.append("📊 Expense ratio {:.0f}% - masih bisa dioptimalkan.".format(exp_ratio * 100))

    health_score = max(0, min(100, health_score))
    health_label = (
        "🟢 SEHAT" if health_score >= 80 else
        "🟡 HATI-HATI" if health_score >= 50 else
        "🔴 KRITIS"
    )

    # ═══════════════════════════════════
    # TOP CARDS
    # ═══════════════════════════════════
    col_h, col1, col2, col3, col4 = st.columns([1.5, 1, 1, 1, 1])
    with col_h:
        st.metric(
            f"🏥 Kesehatan Keuangan",
            f"{health_score}/100 {health_label}",
            help="Skor 0-100 berdasarkan margin, stok, kewajiban, dan rasio biaya."
        )
    with col1:
        st.metric("✅ Net Profit (Bln)", f"Rp {bln_net:,.0f}", delta=f"{bln_margin:.1f}% margin")
    with col2:
        st.metric("📦 Aset Stok", f"Rp {inv_total:,.0f}", help=f"{inv_count} SKU, {inv_no_modal} tanpa harga modal")
    with col3:
        st.metric("💎 Saldo Toko", f"Rp {saldo_toko:,.0f}", help="Akumulasi net profit - pencairan (all marketplace)")
    with col4:
        st.metric("📌 Kewajiban", f"Rp {outstanding:,.0f}", delta="Segera dibayar" if outstanding > 0 else "✅ Lunas")

    # ═══════════════════════════════════
    # ALERTS & RECOMMENDATIONS (AI)
    # ═══════════════════════════════════
    st.markdown("---")
    st.markdown("### 🤖 AI Financial Audit & Rekomendasi")

    if alerts:
        for a in alerts:
            if "🔴" in a:
                st.error(a)
            elif "🟡" in a:
                st.warning(a)
            else:
                st.info(a)

    if recommendations:
        with st.expander("💡 **AI Recommendations** - Tindakan yang Disarankan", expanded=True):
            for i, rec in enumerate(recommendations, 1):
                st.markdown(f"{i}. {rec}")
    else:
        st.success("✅ Tidak ada rekomendasi khusus. Keuangan dalam kondisi baik.")

    # ═══════════════════════════════════
    # CHARTS: Daily Sales vs Expenses
    # ═══════════════════════════════════
    st.markdown("---")
    st.markdown("### 📊 Grafik Penjualan & Pengeluaran - 30 Hari Terakhir")

    chart_data = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.strftime("%d-%m-%Y")
        # Sales PACKED
        day_sales = db.fetch_all(
            "SELECT p.total_harga FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            "WHERE s.status = 'PACKED' AND s.tanggal = ?", (d_str,),
        )
        day_gross = sum(r["total_harga"] or 0 for r in day_sales)

        # Expenses (OPEX + Pembelian LUNAS on that day)
        day_opex = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE status_bayar='LUNAS' AND tanggal = ?", (d_str,))
        day_pemb = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM pembelian WHERE status_bayar='LUNAS' AND tanggal = ?", (d_str,))
        day_exp = (day_opex["tot"] if day_opex else 0) + (day_pemb["tot"] if day_pemb else 0)

        # Fee + Biaya + Modal estimasi harian
        day_fee = 0
        day_modal = 0
        day_resi_set = set()
        for r in day_sales:
            mp = "Lainnya"  # simplified
            day_fee += (r["total_harga"] or 0) * 0.05  # avg fee
        # rough modal
        day_modal = day_gross * 0.4  # estimasi 40% HPP jika tidak ada data SKU

        day_total_exp = day_exp + day_fee + day_modal
        day_net = day_gross - day_total_exp

        chart_data.append({
            "Tanggal": d_str[-5:],  # DD-MM
            "Penjualan": day_gross,
            "Pengeluaran": day_total_exp,
            "Net": day_net,
        })

    if chart_data:
        df_chart = pd.DataFrame(chart_data)
        # Bar chart: Penjualan vs Pengeluaran
        st.bar_chart(df_chart.set_index("Tanggal")[["Penjualan", "Pengeluaran"]], width="stretch", height=300)

        # Line chart: Net Profit harian
        st.line_chart(df_chart.set_index("Tanggal")[["Net"]], width="stretch", height=200)

    # ═══════════════════════════════════
    # MONTHLY TREND (6 months)
    # ═══════════════════════════════════
    st.markdown("---")
    st.markdown("### 📅 Tren Bulanan - 6 Bulan Terakhir")
    monthly_trend = []
    for m in range(5, -1, -1):
        ym = today - timedelta(days=30 * m)
        m_start = ym.replace(day=1).strftime("%d-%m-%Y")
        m_label = ym.strftime("%b %Y")

        m_sales = db.fetch_all(
            "SELECT p.total_harga FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
            "WHERE s.status = 'PACKED' AND s.tanggal >= ? AND s.tanggal < ?",
            (m_start, (ym.replace(day=28) + timedelta(days=7)).replace(day=1).strftime("%d-%m-%Y")),
        )
        m_gross = sum(r["total_harga"] or 0 for r in m_sales)

        m_opex = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE status_bayar='LUNAS' AND tanggal >= ? AND tanggal < ?",
                             (m_start, (ym.replace(day=28) + timedelta(days=7)).replace(day=1).strftime("%d-%m-%Y")))
        m_pemb = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM pembelian WHERE status_bayar='LUNAS' AND tanggal >= ? AND tanggal < ?",
                             (m_start, (ym.replace(day=28) + timedelta(days=7)).replace(day=1).strftime("%d-%m-%Y")))

        m_exp = (m_opex["tot"] if m_opex else 0) + (m_pemb["tot"] if m_pemb else 0)

        monthly_trend.append({
            "Bulan": m_label,
            "Penjualan": m_gross,
            "Pengeluaran": m_exp,
        })

    if monthly_trend:
        df_monthly = pd.DataFrame(monthly_trend)
        st.bar_chart(df_monthly.set_index("Bulan")[["Penjualan", "Pengeluaran"]], width="stretch", height=250)

    # ═══════════════════════════════════
    # QUICK SUMMARY
    # ═══════════════════════════════════
    st.markdown("---")
    col_q1, col_q2, col_q3 = st.columns(3)

    with col_q1:
        st.markdown("#### 📦 Penjualan Bulan Ini")
        mp_sales = {}
        for r in bln_sales:
            mp = r["marketplace"] or "Lainnya"
            mp_sales[mp] = mp_sales.get(mp, 0) + (r["total_harga"] or 0)
        for mp, val in sorted(mp_sales.items(), key=lambda x: -x[1]):
            st.metric(f"🏪 {mp}", f"Rp {val:,.0f}")

    with col_q2:
        st.markdown("#### 📤 Pengeluaran Bulan Ini")
        st.metric("🔻 Fee Marketplace", f"Rp {bln_fee:,.0f}")
        st.metric("📦 Biaya / Resi", f"Rp {bln_biaya:,.0f}")
        st.metric("📋 Harga Modal", f"Rp {bln_modal:,.0f}")
        st.metric("📝 OPEX", f"Rp {bln_opex_val:,.0f}",
                 help=f"Variable (packing): Rp {bln_opex_var_val:,.0f} | Tetap (gaji/listrik/dll): Rp {bln_opex_tetap_val:,.0f}")
        st.metric("🛒 Pembelian", f"Rp {bln_pemb_val:,.0f}")

    with col_q3:
        st.markdown("#### 📊 Rasio Keuangan")
        st.metric("Margin Profit", f"{bln_margin:.1f}%")
        exp_ratio_q = (bln_expense / bln_income * 100) if bln_income > 0 else 0
        st.metric("Expense Ratio", f"{exp_ratio_q:.1f}%")
        st.metric("Aset Inventaris", f"Rp {inv_total:,.0f}")
        st.metric("ROI Inventory", f"{(bln_modal / inv_total * 100):.1f}%" if inv_total > 0 else "N/A",
                 help="Perputaran modal terhadap nilai stok")

    # ═══════════════════════════════════
    # QUICK LINKS + PDF DOWNLOAD
    # ═══════════════════════════════════
    st.markdown("---")
    col_dl1, col_dl2 = st.columns([3, 1])
    with col_dl1:
        st.caption("🔗 **Quick Links**: 💰 Laba Rugi Harian | 💵 Cashflow & Pencairan | 🏷️ Manajemen SKU | ✅ Konfirmasi Bayar")
    with col_dl2:
        if st.button("📥 **Download Laporan PDF**", width="stretch", type="primary", key="fin_download_pdf",
                     help="Download laporan keuangan lengkap dalam format PDF (Gross, Net Profit, Cashflow Harian, Bulanan)"):
            with st.spinner("📄 Membuat laporan PDF..."):
                pdf_path = generate_finance_pdf(
                    db, fee_map, biaya_per_resi,
                    start_date=today.replace(day=1),
                    end_date=today,
                )
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "⬇️ Klik untuk Download PDF",
                        f,
                        file_name=f"Laporan_Keuangan_iScan_{today.strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                    )
                try:
                    os.unlink(pdf_path)
                except:
                    pass


def render_finance_opex():
    """Konfirmasi pembayaran OPEX."""
    db = st.session_state.db
    st.subheader("✅ Konfirmasi Pembayaran OPEX")

    pending = db.fetch_all(
        "SELECT no_faktur, tanggal, kategori, metode_bayar, "
        "COUNT(*) as items, SUM(total_harga) as total "
        "FROM opex WHERE status_bayar = 'PENDING' "
        "GROUP BY no_faktur ORDER BY created_at DESC"
    )

    if not pending:
        st.success("✅ Semua biaya OPEX sudah LUNAS.")
        return

    st.markdown(f"### 📋 {len(pending)} OPEX Menunggu Konfirmasi")

    df = []
    for r in pending:
        df.append({
            "No Ref": r["no_faktur"], "Tanggal": r["tanggal"], "Kategori": r["kategori"],
            "Metode Bayar": r["metode_bayar"], "Item": r["items"],
            "Total": f"Rp {r['total']:,.0f}",
        })
    st.dataframe(pd.DataFrame(df), width="stretch", hide_index=True)

    st.markdown("---")
    ref_options = [f"{r['no_faktur']} | {r['tanggal']} | {r['kategori']} | Rp {r['total']:,.0f}" for r in pending]
    selected = st.selectbox("Pilih OPEX untuk dikonfirmasi", ref_options, key="finance_opex_select")
    selected_ref = selected.split(" | ")[0]

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Konfirmasi LUNAS", type="primary", width="stretch", key="opex_lunas_btn"):
            db.execute("UPDATE opex SET status_bayar = 'LUNAS' WHERE no_faktur = ?", (selected_ref,))
            st.success(f"OPEX '{selected_ref}' dikonfirmasi LUNAS! ✅")
            st.rerun()
    with col2:
        if st.button("📋 Konfirmasi KONTRA BON", width="stretch", key="opex_kontrabon_btn"):
            db.execute("UPDATE opex SET status_bayar = 'KONTRA BON' WHERE no_faktur = ?", (selected_ref,))
            st.warning(f"OPEX '{selected_ref}' dicatat sebagai KONTRA BON.")
            st.rerun()


def render_finance_history():
    """Riwayat pembayaran SKU + OPEX."""
    db = st.session_state.db
    st.subheader("📋 Riwayat Pembayaran")

    # Lunas SKU
    sku_lunas = db.fetch_all(
        "SELECT no_faktur, tanggal, supplier, metode_bayar, status_bayar, "
        "COUNT(*) as items, SUM(total_harga) as total_barang, "
        "MAX(biaya_operasional) as biaya_ops, MAX(biaya_packing) as biaya_pack "
        "FROM pembelian WHERE status_bayar = 'LUNAS' "
        "GROUP BY no_faktur ORDER BY created_at DESC LIMIT 50"
    )

    # Lunas OPEX
    opex_lunas = db.fetch_all(
        "SELECT no_faktur, tanggal, kategori, metode_bayar, status_bayar, "
        "COUNT(*) as items, SUM(total_harga) as total "
        "FROM opex WHERE status_bayar = 'LUNAS' "
        "GROUP BY no_faktur ORDER BY created_at DESC LIMIT 50"
    )

    tab1, tab2 = st.tabs(["📦 Pembayaran SKU", "📋 Pembayaran OPEX"])
    with tab1:
        if sku_lunas:
            df_s = pd.DataFrame([dict(r) for r in sku_lunas])
            for _, row in df_s.iterrows():
                grand = (row["total_barang"] or 0) + (row["biaya_ops"] or 0) + (row["biaya_pack"] or 0)
                row["Grand Total"] = grand
            df_s["Total Barang"] = df_s["total_barang"].apply(lambda x: f"Rp {x:,.0f}")
            df_s["Grand Total"] = df_s["Grand Total"].apply(lambda x: f"Rp {x:,.0f}")
            df_s = df_s.rename(columns={"no_faktur": "No Faktur", "tanggal": "Tanggal", "supplier": "Supplier",
                                         "metode_bayar": "Metode Bayar", "items": "Item"})
            st.dataframe(df_s[["No Faktur", "Tanggal", "Supplier", "Metode Bayar", "Item", "Total Barang", "Grand Total"]],
                         width="stretch", hide_index=True)
        else:
            st.info("Belum ada pembayaran SKU LUNAS.")

    with tab2:
        if opex_lunas:
            df_o = pd.DataFrame([dict(r) for r in opex_lunas])
            df_o["Total"] = df_o["total"].apply(lambda x: f"Rp {x:,.0f}")
            df_o = df_o.rename(columns={"no_faktur": "No Ref", "tanggal": "Tanggal", "kategori": "Kategori",
                                         "metode_bayar": "Metode Bayar", "items": "Item"})
            st.dataframe(df_o[["No Ref", "Tanggal", "Kategori", "Metode Bayar", "Item", "Total"]],
                         width="stretch", hide_index=True)
        else:
            st.info("Belum ada pembayaran OPEX LUNAS.")


# ==================== ADMIN USER MANAGEMENT ====================
def render_admin_users():
    """Render the admin user management page."""
    db = st.session_state.db
    current_user = st.session_state.user

    st.subheader("👥 Manajemen User & Role")

    # ── Stats ──
    total_users = db.fetch_one("SELECT COUNT(*) as cnt FROM users")
    active_users = db.fetch_one("SELECT COUNT(*) as cnt FROM users WHERE active = 1")

    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.metric("👤 Total User", total_users["cnt"] if total_users else 0)
    with col_s2:
        st.metric("✅ Aktif", active_users["cnt"] if active_users else 0)
    with col_s3:
        st.metric("🛑 Nonaktif", (total_users["cnt"] or 0) - (active_users["cnt"] or 0))

    st.markdown("---")

    # ── Add User ──
    with st.expander("➕ Tambah User Baru", expanded=False):
        col_a1, col_a2 = st.columns(2)
        with col_a1:
            new_username = st.text_input("Username", key="new_user_username", placeholder="huruf kecil tanpa spasi")
            new_nama = st.text_input("Nama Lengkap", key="new_user_nama", placeholder="Nama lengkap")
        with col_a2:
            new_password = st.text_input("Password", type="password", key="new_user_password", placeholder="Minimal 4 karakter")
            new_role = st.selectbox("Role", ROLE_CHOICES, format_func=lambda r: f"{ROLES[r]['label']} - {ROLES[r]['desc']}", key="new_user_role")

        if st.button("💾 Simpan User", type="primary"):
            if not new_username.strip() or not new_nama.strip() or len(new_password) < 4:
                st.error("Username, nama, dan password (min 4 karakter) wajib diisi!")
            else:
                existing = db.fetch_one("SELECT id FROM users WHERE username = ?", (new_username.strip().lower(),))
                if existing:
                    st.error(f"Username '{new_username}' sudah digunakan.")
                else:
                    db.execute(
                        "INSERT INTO users (username, password_hash, nama_lengkap, role) VALUES (?, ?, ?, ?)",
                        (new_username.strip().lower(), hash_password(new_password), new_nama.strip(), new_role),
                    )
                    st.success(f"✅ User '{new_username}' berhasil dibuat!")
                    st.rerun()

    st.markdown("---")

    # ── User List ──
    users = db.fetch_all("SELECT id, username, nama_lengkap, role, active, created_at, last_login FROM users ORDER BY role, username")
    if users:
        st.markdown("### 📋 Daftar User")

        # Build table data
        user_data = []
        for u in users:
            role_label = ROLES.get(u["role"], {}).get("label", u["role"])
            status = "✅ Aktif" if u["active"] else "🛑 Nonaktif"
            last_login = u["last_login"] or "Belum pernah"
            created = u["created_at"] or "-"
            user_data.append({
                "Username": u["username"],
                "Nama": u["nama_lengkap"],
                "Role": f"{role_label}",
                "Status": status,
                "Login Terakhir": last_login,
                "Dibuat": created,
                "_id": u["id"],
                "_role": u["role"],
                "_active": u["active"],
            })

        df_users = pd.DataFrame(user_data)
        st.dataframe(
            df_users[["Username", "Nama", "Role", "Status", "Login Terakhir", "Dibuat"]],
            width="stretch",
            hide_index=True,
        )

        # ── Edit / Delete ──
        st.markdown("---")
        st.markdown("### ✏️ Edit / Kelola User")

        user_options = {f"{u['username']} ({ROLES.get(u['role'], {}).get('label', u['role'])})": u for u in users}
        selected_label = st.selectbox("Pilih User", list(user_options.keys()), key="admin_select_user")
        selected_user = user_options[selected_label]

        col_e1, col_e2, col_e3 = st.columns(3)
        with col_e1:
            edit_nama = st.text_input("Nama Lengkap", value=selected_user["nama_lengkap"], key="edit_user_nama")
        with col_e2:
            edit_role = st.selectbox(
                "Role",
                ROLE_CHOICES,
                index=ROLE_CHOICES.index(selected_user["role"]) if selected_user["role"] in ROLE_CHOICES else 0,
                format_func=lambda r: ROLES[r]['label'],
                key="edit_user_role",
            )
        with col_e3:
            edit_active = st.checkbox("Akun Aktif", value=bool(selected_user["active"]), key="edit_user_active")

        col_btn1, col_btn2, col_btn3 = st.columns(3)
        with col_btn1:
            if st.button("💾 Update User", width="stretch", type="primary", key="update_user_btn"):
                if not edit_nama.strip():
                    st.error("Nama tidak boleh kosong!")
                else:
                    db.execute(
                        "UPDATE users SET nama_lengkap = ?, role = ?, active = ? WHERE id = ?",
                        (edit_nama.strip(), edit_role, int(edit_active), selected_user["id"]),
                    )
                    st.success(f"✅ User '{selected_user['username']}' diupdate!")
                    st.rerun()

        with col_btn2:
            new_pass = st.text_input("Password Baru", type="password", placeholder="Kosongkan jika tidak diganti", key="edit_user_pass")
            if st.button("🔑 Reset Password", width="stretch", key="reset_pass_btn"):
                if len(new_pass) < 4:
                    st.error("Password baru minimal 4 karakter!")
                else:
                    db.execute(
                        "UPDATE users SET password_hash = ? WHERE id = ?",
                        (hash_password(new_pass), selected_user["id"]),
                    )
                    st.success(f"✅ Password '{selected_user['username']}' direset!")
                    st.rerun()

        with col_btn3:
            if selected_user["username"] != current_user["username"]:
                if st.button("🗑️ Hapus User", width="stretch", type="secondary", key="delete_user_btn"):
                    db.execute("DELETE FROM users WHERE id = ?", (selected_user["id"],))
                    st.warning(f"User '{selected_user['username']}' dihapus.")
                    st.rerun()
            else:
                st.caption("⚠️ Tidak bisa hapus akun sendiri")

    else:
        st.info("Belum ada user terdaftar.")


# ==================== MASTER DATA PAGE ====================
def render_master_data():
    """Render halaman Master Data dengan tab: SKU, Supplier, Kategori, Toko, Barang Besar, Gudang."""
    db = st.session_state.db

    st.title("📦 Master Data")
    st.caption("Kelola semua data master: barang, supplier, kategori, toko, barang besar & gudang.")

    tabs = st.tabs([
        "🏷️ Database Barang (SKU)",
        "🏪 Supplier",
        "📂 Kategori",
        "🏬 Toko",
        "📦 Barang Besar",
        "🏭 Gudang / Lokasi",
    ])

    # ═══════════════════ TAB 1: DATABASE BARANG (SKU) ═══════════════════
    with tabs[0]:
        st.subheader("🏷️ Manajemen Database Barang (SKU)")
        st.caption("Master data barang: tambah, edit, hapus, update harga, upload massal.")

        # ── Stats Ringkasan ──
        total_sku = db.fetch_one("SELECT COUNT(*) as cnt FROM sku")
        total_stok = db.fetch_one("SELECT COALESCE(SUM(stok), 0) as total FROM sku")
        total_value = db.fetch_one("SELECT COALESCE(SUM(stok * harga_beli), 0) as total FROM sku")
        low_stock = db.fetch_one("SELECT COUNT(*) as cnt FROM sku WHERE stok <= 10 AND stok > 0")
        no_harga = db.fetch_one("SELECT COUNT(*) as cnt FROM sku WHERE harga_beli = 0 OR harga_beli IS NULL")

        col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
        with col_s1:
            st.metric("📦 Total SKU", f"{total_sku['cnt']:,}" if total_sku else "0")
        with col_s2:
            st.metric("📊 Total Stok", f"{total_stok['total']:,}" if total_stok else "0")
        with col_s3:
            st.metric("💰 Nilai Inventaris", f"Rp {total_value['total']:,.0f}" if total_value else "Rp 0")
        with col_s4:
            st.metric("⚠️ Stok Menipis", f"{low_stock['cnt']:,}" if low_stock else "0")
        with col_s5:
            st.metric("❌ Tanpa Harga Beli", f"{no_harga['cnt']:,}" if no_harga else "0")

        # ── Upload Massal SKU ──
        with st.expander("📥 Upload Massal SKU dari Excel", expanded=False):
            st.caption("Upload file Excel (.xlsx/.xls) dengan kolom: Kode SKU, Nama Barang, Kategori, Stok, Satuan, Supplier, Harga Beli, Harga Jual, Keterangan.")
            uploaded_sku = st.file_uploader("Pilih file Excel", type=["xlsx", "xls"], key="master_sku_upload")
            if uploaded_sku:
                try:
                    df_excel = pd.read_excel(uploaded_sku)
                    st.write("📋 Preview data:")
                    st.dataframe(df_excel.head(10), width="stretch", hide_index=True)
                    col_map = {}
                    target_cols = ["Kode SKU", "Nama Barang", "Kategori", "Stok", "Satuan", "Supplier", "Harga Beli", "Harga Jual", "Keterangan"]
                    for col_name, target in [
                        ("kode_sku", "Kode SKU"), ("nama_barang", "Nama Barang"), ("kategori", "Kategori"),
                        ("stok", "Stok"), ("satuan", "Satuan"), ("supplier", "Supplier"),
                        ("harga_beli", "Harga Beli"), ("harga_jual", "Harga Jual"), ("keterangan", "Keterangan"),
                    ]:
                        col_map[col_name] = st.selectbox(
                            f"Kolom untuk '{target}'", ["-- Pilih --"] + list(df_excel.columns),
                            key=f"master_sku_map_{col_name}",
                        )
                    only_filled = st.checkbox("Hanya update field yang terisi (kosongkan field lain yang tidak di-upload)", value=True, key="master_sku_only_filled")
                    if st.button("🚀 Proses Upload SKU", type="primary", key="master_sku_proses"):
                        upserted = 0
                        for _, row in df_excel.iterrows():
                            kode = str(row[col_map["kode_sku"]]).strip() if col_map["kode_sku"] != "-- Pilih --" and pd.notna(row[col_map["kode_sku"]]) else ""
                            if not kode:
                                continue
                            nama = str(row[col_map["nama_barang"]]).strip() if col_map["nama_barang"] != "-- Pilih --" and pd.notna(row[col_map["nama_barang"]]) else ""
                            existing = db.fetch_one("SELECT id FROM sku WHERE kode_sku = ?", (kode,))
                            if existing:
                                updates = []
                                params = []
                                if col_map["nama_barang"] != "-- Pilih --" and nama:
                                    updates.append("nama_barang = ?"); params.append(nama)
                                if col_map["kategori"] != "-- Pilih --" and pd.notna(row[col_map["kategori"]]):
                                    updates.append("kategori = ?"); params.append(str(row[col_map["kategori"]]).strip())
                                if col_map["stok"] != "-- Pilih --" and pd.notna(row[col_map["stok"]]):
                                    updates.append("stok = ?"); params.append(int(float(row[col_map["stok"]])))
                                if col_map["satuan"] != "-- Pilih --" and pd.notna(row[col_map["satuan"]]):
                                    updates.append("satuan = ?"); params.append(str(row[col_map["satuan"]]).strip())
                                if col_map["supplier"] != "-- Pilih --" and pd.notna(row[col_map["supplier"]]):
                                    updates.append("supplier = ?"); params.append(str(row[col_map["supplier"]]).strip())
                                if col_map["harga_beli"] != "-- Pilih --" and pd.notna(row[col_map["harga_beli"]]):
                                    updates.append("harga_beli = ?"); params.append(float(row[col_map["harga_beli"]]))
                                if col_map["harga_jual"] != "-- Pilih --" and pd.notna(row[col_map["harga_jual"]]):
                                    updates.append("harga_jual = ?"); params.append(float(row[col_map["harga_jual"]]))
                                if col_map["keterangan"] != "-- Pilih --" and pd.notna(row[col_map["keterangan"]]):
                                    updates.append("keterangan = ?"); params.append(str(row[col_map["keterangan"]]).strip())
                                if updates:
                                    updates.append("updated_at = CURRENT_TIMESTAMP")
                                    params.append(kode)
                                    db.execute(f"UPDATE sku SET {', '.join(updates)} WHERE kode_sku = ?", params)
                                    upserted += 1
                            else:
                                if not nama:
                                    continue
                                db.execute(
                                    "INSERT INTO sku (kode_sku, nama_barang, kategori, stok, satuan, supplier, harga_beli, harga_jual, keterangan) "
                                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    (
                                        kode, nama,
                                        str(row[col_map["kategori"]]).strip() if col_map["kategori"] != "-- Pilih --" and pd.notna(row[col_map["kategori"]]) else "",
                                        int(float(row[col_map["stok"]])) if col_map["stok"] != "-- Pilih --" and pd.notna(row[col_map["stok"]]) else 0,
                                        str(row[col_map["satuan"]]).strip() if col_map["satuan"] != "-- Pilih --" and pd.notna(row[col_map["satuan"]]) else "pcs",
                                        str(row[col_map["supplier"]]).strip() if col_map["supplier"] != "-- Pilih --" and pd.notna(row[col_map["supplier"]]) else "",
                                        float(row[col_map["harga_beli"]]) if col_map["harga_beli"] != "-- Pilih --" and pd.notna(row[col_map["harga_beli"]]) else 0,
                                        float(row[col_map["harga_jual"]]) if col_map["harga_jual"] != "-- Pilih --" and pd.notna(row[col_map["harga_jual"]]) else 0,
                                        str(row[col_map["keterangan"]]).strip() if col_map["keterangan"] != "-- Pilih --" and pd.notna(row[col_map["keterangan"]]) else "",
                                    ),
                                )
                                upserted += 1
                        st.success(f"✅ {upserted} SKU berhasil diproses!")
                        st.rerun()
                except Exception as e:
                    st.error(f"❌ Gagal membaca file: {e}")

        # ── Tambah SKU Baru ──
        with st.expander("➕ Tambah SKU Baru", expanded=False):
            col_a, col_b = st.columns(2)
            with col_a:
                kode_baru = st.text_input("Kode SKU *", placeholder="SKU-001", key="master_sku_kode")
                nama_baru = st.text_input("Nama Barang *", placeholder="Nama produk", key="master_sku_nama")
                # ── Dropdown dari master kategori ──
                kat_list = db.fetch_all("SELECT nama FROM kategori_produk ORDER BY nama")
                kat_opts = [k["nama"] for k in kat_list] if kat_list else []
                kat_input = st.selectbox(
                    "Kategori", ["-- Pilih Kategori --"] + kat_opts + ["✚ Tambah Baru..."],
                    key="master_sku_kat_select",
                )
                if kat_input == "✚ Tambah Baru...":
                    kat_input = st.text_input("Nama Kategori Baru", placeholder="Contoh: Elektronik", key="master_sku_kat_new")
                stok_awal = st.number_input("Stok Awal", min_value=0, value=0, step=1, key="master_sku_stok")
                satuan = st.selectbox("Satuan", ["pcs", "box", "lusin", "kg", "liter", "meter", "pack", "set", "unit"], key="master_sku_satuan")
            with col_b:
                # ── Dropdown dari master supplier ──
                sup_list = db.fetch_all("SELECT nama FROM supplier ORDER BY nama")
                sup_opts = [s["nama"] for s in sup_list] if sup_list else []
                sup_input = st.selectbox(
                    "Supplier", ["-- Pilih Supplier --"] + sup_opts + ["✚ Tambah Baru..."],
                    key="master_sku_sup_select",
                )
                if sup_input == "✚ Tambah Baru...":
                    sup_input = st.text_input("Nama Supplier Baru", placeholder="Contoh: PT Sumber Jaya", key="master_sku_sup_new")
                harga_beli = st.number_input("Harga Beli (Rp)", min_value=0, value=0, step=1000, key="master_sku_hbeli")
                harga_jual = st.number_input("Harga Jual (Rp)", min_value=0, value=0, step=1000, key="master_sku_hjual")
                keterangan = st.text_area("Keterangan", placeholder="Catatan tambahan...", key="master_sku_ket", height=100)

            if st.button("💾 Simpan SKU Baru", type="primary", key="master_sku_simpan"):
                if not kode_baru.strip() or not nama_baru.strip():
                    st.error("Kode SKU dan Nama Barang wajib diisi!")
                else:
                    existing = db.fetch_one("SELECT id FROM sku WHERE kode_sku = ?", (kode_baru.strip(),))
                    if existing:
                        st.error(f"Kode SKU '{kode_baru.strip()}' sudah ada!")
                    else:
                        # Auto-save kategori baru
                        final_kat = kat_input if kat_input not in ("-- Pilih Kategori --", "✚ Tambah Baru...") else ""
                        if kat_input and kat_input not in ("-- Pilih Kategori --", "✚ Tambah Baru..."):
                            try:
                                db.execute("INSERT OR IGNORE INTO kategori_produk (nama) VALUES (?)", (kat_input,))
                            except:
                                pass
                        # Auto-save supplier baru
                        final_sup = sup_input if sup_input not in ("-- Pilih Supplier --", "✚ Tambah Baru...") else ""
                        if sup_input and sup_input not in ("-- Pilih Supplier --", "✚ Tambah Baru..."):
                            try:
                                db.execute("INSERT OR IGNORE INTO supplier (nama) VALUES (?)", (sup_input,))
                            except:
                                pass
                        db.execute(
                            "INSERT INTO sku (kode_sku, nama_barang, kategori, stok, satuan, supplier, harga_beli, harga_jual, keterangan) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (kode_baru.strip(), nama_baru.strip(), final_kat, stok_awal, satuan, final_sup, harga_beli, harga_jual, keterangan),
                        )
                        st.success(f"✅ SKU '{kode_baru.strip()}' berhasil ditambahkan!")
                        st.rerun()

        st.markdown("---")

        # ── Daftar SKU dengan filter ──
        st.subheader("📋 Daftar SKU")

        filt_c1, filt_c2, filt_c3, filt_c4 = st.columns(4)
        with filt_c1:
            search_sku = st.text_input("🔍 Cari Kode/Nama", placeholder="Ketik...", key="master_sku_search")
        with filt_c2:
            kat_filter_list = db.fetch_all("SELECT DISTINCT kategori FROM sku WHERE kategori != '' ORDER BY kategori")
            kat_filter_opts = ["Semua"] + [k["kategori"] for k in kat_filter_list]
            kat_filter = st.selectbox("Filter Kategori", kat_filter_opts, key="master_sku_filt_kat")
        with filt_c3:
            sup_filter_list = db.fetch_all("SELECT DISTINCT supplier FROM sku WHERE supplier != '' ORDER BY supplier")
            sup_filter_opts = ["Semua"] + [s["supplier"] for s in sup_filter_list]
            sup_filter = st.selectbox("Filter Supplier", sup_filter_opts, key="master_sku_filt_sup")
        with filt_c4:
            stok_filter = st.selectbox("Filter Stok", ["Semua", "Stok Menipis (≤10)", "Stok Habis (0)", "Tersedia (>0)", "Tanpa Harga Beli"], key="master_sku_filt_stok")

        query = "SELECT * FROM sku WHERE 1=1"
        params = []
        if search_sku:
            query += " AND (kode_sku LIKE ? OR nama_barang LIKE ?)"
            params.extend([f"%{search_sku}%", f"%{search_sku}%"])
        if kat_filter != "Semua":
            query += " AND kategori = ?"
            params.append(kat_filter)
        if sup_filter != "Semua":
            query += " AND supplier = ?"
            params.append(sup_filter)
        if stok_filter == "Stok Menipis (≤10)":
            query += " AND stok <= 10 AND stok > 0"
        elif stok_filter == "Stok Habis (0)":
            query += " AND stok = 0"
        elif stok_filter == "Tersedia (>0)":
            query += " AND stok > 0"
        elif stok_filter == "Tanpa Harga Beli":
            query += " AND (harga_beli = 0 OR harga_beli IS NULL)"
        query += " ORDER BY kode_sku ASC LIMIT 200"

        rows = db.fetch_all(query, params)

        if not rows:
            st.info("📭 Tidak ada SKU ditemukan.")
        else:
            df_sku = pd.DataFrame([dict(r) for r in rows])

            def color_sku_row(row):
                styles = [""] * len(row)
                if row.get("stok", 0) == 0:
                    return ["background-color: #f8d7da; color: #721c24"] * len(row)
                if row.get("stok", 0) <= 10:
                    return ["background-color: #fff3cd; color: #856404"] * len(row)
                if row.get("harga_beli", 0) == 0:
                    styles[df_sku.columns.get_loc("harga_beli") if "harga_beli" in df_sku.columns else 0] = "background-color: #f8d7da; color: #721c24"
                    return styles
                return styles

            df_sku = df_sku.rename(columns={
                "kode_sku": "Kode SKU", "nama_barang": "Nama Barang", "kategori": "Kategori",
                "stok": "Stok", "satuan": "Satuan", "harga_beli": "Harga Beli",
                "harga_jual": "Harga Jual", "supplier": "Supplier", "keterangan": "Ket",
            })
            df_sku["Harga Beli"] = df_sku["Harga Beli"].apply(lambda x: f"Rp {x:,.0f}" if x else "Rp 0")
            df_sku["Harga Jual"] = df_sku["Harga Jual"].apply(lambda x: f"Rp {x:,.0f}" if x else "Rp 0")

            display = ["Kode SKU", "Nama Barang", "Kategori", "Stok", "Satuan", "Harga Beli", "Harga Jual", "Supplier"]
            available = [c for c in display if c in df_sku.columns]
            styled = df_sku[available].style.apply(color_sku_row, axis=1)
            st.dataframe(styled, width="stretch", height=400, hide_index=True, key="master_sku_table")

        # ── Update Harga / Edit SKU ──
        st.markdown("---")
        st.subheader("⚙️ Update Harga & Edit SKU")

        all_sku_list = db.fetch_all("SELECT kode_sku, nama_barang, kategori, stok, satuan, supplier, harga_beli, harga_jual, keterangan, id FROM sku ORDER BY kode_sku")
        sku_options = [f"{s['kode_sku']} - {s['nama_barang'][:40]}" for s in all_sku_list]
        sku_map = {f"{s['kode_sku']} - {s['nama_barang'][:40]}": s for s in all_sku_list}

        edit_col1, edit_col2 = st.columns([3, 1])
        with edit_col1:
            selected_sku_label = st.selectbox("Pilih SKU untuk di-edit", [""] + sku_options, key="master_sku_edit_select")
        with edit_col2:
            st.write("")
            if selected_sku_label and st.button("🗑️ Hapus SKU", type="secondary", key="master_sku_delete"):
                sku_data = sku_map.get(selected_sku_label)
                if sku_data:
                    db.execute("DELETE FROM sku WHERE id = ?", (sku_data["id"],))
                    st.success(f"🗑️ SKU '{sku_data['kode_sku']}' dihapus!")
                    st.rerun()

        if selected_sku_label:
            sku_data = sku_map.get(selected_sku_label)
            if sku_data:
                with st.form("master_sku_edit_form"):
                    st.markdown(f"**Edit: `{sku_data['kode_sku']}` - {sku_data['nama_barang']}**")
                    ec1, ec2, ec3 = st.columns(3)
                    with ec1:
                        new_kode = st.text_input("Kode SKU", value=sku_data["kode_sku"], key="master_sku_ekode")
                        new_nama = st.text_input("Nama Barang", value=sku_data["nama_barang"], key="master_sku_enama")
                        # Kategori dropdown
                        kat_edit_list = db.fetch_all("SELECT nama FROM kategori_produk ORDER BY nama")
                        kat_edit_opts = [k["nama"] for k in kat_edit_list]
                        current_kat = sku_data["kategori"] if sku_data["kategori"] in kat_edit_opts else ""
                        kat_edit_opts_disp = (["-- Pilih --"] if not current_kat else []) + kat_edit_opts + (["✚ Tambah..."] if current_kat not in kat_edit_opts else [])
                        if current_kat and current_kat in kat_edit_opts:
                            kat_idx = kat_edit_opts.index(current_kat) + (1 if not current_kat else 0)
                        else:
                            kat_idx = 0
                        new_kat = st.selectbox("Kategori", kat_edit_opts_disp, key="master_sku_ekat",
                                               index=min(kat_idx, len(kat_edit_opts_disp)-1) if kat_edit_opts_disp else 0)
                        if new_kat == "✚ Tambah...":
                            new_kat = st.text_input("Kategori Baru", value=current_kat, key="master_sku_ekat_new")
                    with ec2:
                        new_stok = st.number_input("Stok", value=int(sku_data["stok"]) if sku_data["stok"] else 0, step=1, key="master_sku_estok")
                        new_satuan = st.selectbox("Satuan", ["pcs", "box", "lusin", "kg", "liter", "meter", "pack", "set", "unit"],
                                                  index=["pcs", "box", "lusin", "kg", "liter", "meter", "pack", "set", "unit"].index(sku_data["satuan"]) if sku_data["satuan"] in ["pcs", "box", "lusin", "kg", "liter", "meter", "pack", "set", "unit"] else 0,
                                                  key="master_sku_esatuan")
                        # Supplier dropdown
                        sup_edit_list = db.fetch_all("SELECT nama FROM supplier ORDER BY nama")
                        sup_edit_opts = [s["nama"] for s in sup_edit_list]
                        current_sup = sku_data["supplier"] if sku_data["supplier"] in sup_edit_opts else ""
                        sup_edit_disp = (["-- Pilih --"] if not current_sup else []) + sup_edit_opts + (["✚ Tambah..."] if current_sup not in sup_edit_opts else [])
                        if current_sup and current_sup in sup_edit_opts:
                            sup_idx = sup_edit_opts.index(current_sup) + (1 if not current_sup else 0)
                        else:
                            sup_idx = 0
                        new_sup = st.selectbox("Supplier", sup_edit_disp, key="master_sku_esup",
                                               index=min(sup_idx, len(sup_edit_disp)-1) if sup_edit_disp else 0)
                        if new_sup == "✚ Tambah...":
                            new_sup = st.text_input("Supplier Baru", value=current_sup, key="master_sku_esup_new")
                    with ec3:
                        new_hbeli = st.number_input("Harga Beli (Rp)", value=int(float(sku_data["harga_beli"] or 0)), step=1000, key="master_sku_ehbeli")
                        new_hjual = st.number_input("Harga Jual (Rp)", value=int(float(sku_data["harga_jual"] or 0)), step=1000, key="master_sku_ehjual")
                        new_ket = st.text_area("Keterangan", value=sku_data["keterangan"] or "", key="master_sku_eket", height=68)

                    # Quick Stock Adjustment
                    adj_col1, adj_col2 = st.columns(2)
                    with adj_col1:
                        st.caption(f"📦 Stok saat ini: **{sku_data['stok']}**")
                    with adj_col2:
                        adj_qty = st.number_input("Tambah (+) / Kurangi (−) Stok", value=0, step=1, key="master_sku_adj")
                    final_stok = max(0, int(new_stok) + int(adj_qty))

                    if st.form_submit_button("💾 Simpan Perubahan", type="primary"):
                        # Auto-save kategori & supplier baru
                        if new_kat and new_kat not in ("-- Pilih --", "✚ Tambah..."):
                            try:
                                db.execute("INSERT OR IGNORE INTO kategori_produk (nama) VALUES (?)", (new_kat,))
                            except:
                                pass
                        if new_sup and new_sup not in ("-- Pilih Supplier --", "-- Pilih --", "✚ Tambah..."):
                            try:
                                db.execute("INSERT OR IGNORE INTO supplier (nama) VALUES (?)", (new_sup,))
                            except:
                                pass
                        db.execute(
                            "UPDATE sku SET kode_sku = ?, nama_barang = ?, kategori = ?, stok = ?, satuan = ?, "
                            "supplier = ?, harga_beli = ?, harga_jual = ?, keterangan = ?, updated_at = CURRENT_TIMESTAMP "
                            "WHERE id = ?",
                            (new_kode.strip(), new_nama.strip(), new_kat if new_kat not in ("-- Pilih --", "✚ Tambah...") else "",
                             final_stok, new_satuan,
                             new_sup if new_sup not in ("-- Pilih Supplier --", "-- Pilih --", "✚ Tambah...") else "",
                             new_hbeli, new_hjual, new_ket, sku_data["id"]),
                        )
                        st.success(f"✅ SKU '{new_kode.strip()}' berhasil diupdate!")
                        st.rerun()

        # ── Update Harga Massal ──
        st.markdown("---")
        with st.expander("💲 Update Harga Massal (Beli / Jual)", expanded=False):
            st.caption("Update harga beli atau harga jual untuk banyak SKU sekaligus berdasarkan filter.")
            mass_c1, mass_c2, mass_c3 = st.columns(3)
            with mass_c1:
                mass_kat = st.selectbox("Filter Kategori", ["Semua"] + kat_filter_opts[1:], key="master_mass_kat")
            with mass_c2:
                mass_sup = st.selectbox("Filter Supplier", ["Semua"] + sup_filter_opts[1:], key="master_mass_sup")
            with mass_c3:
                mass_type = st.radio("Update", ["Harga Beli", "Harga Jual"], key="master_mass_type", horizontal=True)
            mass_val = st.number_input(f"{mass_type} Baru (Rp)", min_value=0, value=0, step=1000, key="master_mass_val")
            mass_pct = st.checkbox("Gunakan persentase kenaikan/penurunan (%)", key="master_mass_pct")
            mass_pct_val = st.number_input("Persentase (%)", value=0.0, step=0.5, key="master_mass_pct_val") if mass_pct else None

            if st.button("🚀 Update Harga Massal", type="primary", key="master_mass_btn"):
                mq = "SELECT id, kode_sku, nama_barang, harga_beli, harga_jual FROM sku WHERE 1=1"
                mp = []
                if mass_kat != "Semua":
                    mq += " AND kategori = ?"; mp.append(mass_kat)
                if mass_sup != "Semua":
                    mq += " AND supplier = ?"; mp.append(mass_sup)
                mrows = db.fetch_all(mq, mp)
                updated = 0
                field = "harga_beli" if mass_type == "Harga Beli" else "harga_jual"
                for r in mrows:
                    if mass_pct and mass_pct_val:
                        old_val = r[field] or 0
                        new_val = old_val * (1 + mass_pct_val / 100)
                    else:
                        new_val = mass_val
                    db.execute(f"UPDATE sku SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_val, r["id"]))
                    updated += 1
                st.success(f"✅ {updated} SKU berhasil diupdate {mass_type}-nya!")
                st.rerun()

    # ═══════════════════ TAB 2: SUPPLIER ═══════════════════
    with tabs[1]:
        st.subheader("🏪 Database Supplier")
        st.caption("Kelola daftar supplier/pemasok. Terhubung dengan modul SKU & Pembelian.")

        # ── Form Tambah Supplier ──
        with st.expander("➕ Tambah Supplier Baru", expanded=False):
            s_col1, s_col2 = st.columns(2)
            with s_col1:
                sup_nama = st.text_input("Nama Supplier *", placeholder="PT Sumber Jaya", key="master_sup_nama")
                sup_kontak = st.text_input("Kontak (Telp/WA)", placeholder="0812-xxxx-xxxx", key="master_sup_kontak")
            with s_col2:
                sup_alamat = st.text_area("Alamat", placeholder="Alamat lengkap...", key="master_sup_alamat", height=100)
                sup_ket = st.text_input("Keterangan", placeholder="Catatan...", key="master_sup_ket")
            if st.button("💾 Simpan Supplier", type="primary", key="master_sup_simpan"):
                if not sup_nama.strip():
                    st.error("Nama supplier wajib diisi!")
                else:
                    try:
                        db.execute(
                            "INSERT INTO supplier (nama, kontak, alamat, keterangan) VALUES (?, ?, ?, ?)",
                            (sup_nama.strip(), sup_kontak.strip(), sup_alamat.strip(), sup_ket.strip()),
                        )
                        st.success(f"✅ Supplier '{sup_nama.strip()}' ditambahkan!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal: {e}")

        st.markdown("---")

        # ── Daftar Supplier ──
        st.subheader("📋 Daftar Supplier")
        sup_search = st.text_input("🔍 Cari Supplier", placeholder="Ketik nama...", key="master_sup_search2")
        sup_query = "SELECT s.*, (SELECT COUNT(*) FROM sku WHERE supplier = s.nama) as jml_sku, (SELECT COUNT(DISTINCT no_faktur) FROM pembelian WHERE supplier = s.nama) as jml_pembelian FROM supplier s WHERE 1=1"
        sup_params = []
        if sup_search:
            sup_query += " AND s.nama LIKE ?"
            sup_params.append(f"%{sup_search}%")
        sup_query += " ORDER BY s.nama"

        sup_rows = db.fetch_all(sup_query, sup_params)

        if not sup_rows:
            st.info("📭 Belum ada supplier. Tambahkan di atas.")
        else:
            for s in sup_rows:
                with st.container(border=True):
                    sc1, sc2, sc3, sc4 = st.columns([3, 1, 1, 1])
                    with sc1:
                        st.markdown(f"**🏪 {s['nama']}**")
                        details = []
                        if s["kontak"]:
                            details.append(f"📞 {s['kontak']}")
                        if s["alamat"]:
                            details.append(f"📍 {s['alamat'][:60]}")
                        if details:
                            st.caption(" | ".join(details))
                    with sc2:
                        st.metric("SKU", s["jml_sku"] or 0)
                    with sc3:
                        st.metric("Pembelian", s["jml_pembelian"] or 0)
                    with sc4:
                        if st.button("✏️ Edit", key=f"master_sup_edit_{s['id']}"):
                            st.session_state[f"edit_sup_{s['id']}"] = True
                        if st.button("🗑️", key=f"master_sup_del_{s['id']}", help="Hapus supplier"):
                            db.execute("DELETE FROM supplier WHERE id = ?", (s["id"],))
                            st.success(f"🗑️ Supplier '{s['nama']}' dihapus.")
                            st.rerun()
                    if st.session_state.get(f"edit_sup_{s['id']}"):
                        with st.form(f"master_sup_edit_form_{s['id']}"):
                            ec1, ec2 = st.columns(2)
                            with ec1:
                                e_nama = st.text_input("Nama", value=s["nama"], key=f"master_sup_en_{s['id']}")
                                e_kontak = st.text_input("Kontak", value=s["kontak"] or "", key=f"master_sup_ek_{s['id']}")
                            with ec2:
                                e_alamat = st.text_area("Alamat", value=s["alamat"] or "", key=f"master_sup_ea_{s['id']}")
                                e_ket = st.text_input("Keterangan", value=s["keterangan"] or "", key=f"master_sup_ekt_{s['id']}")
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.form_submit_button("💾 Simpan"):
                                    db.execute(
                                        "UPDATE supplier SET nama = ?, kontak = ?, alamat = ?, keterangan = ? WHERE id = ?",
                                        (e_nama.strip(), e_kontak.strip(), e_alamat.strip(), e_ket.strip(), s["id"]),
                                    )
                                    st.session_state[f"edit_sup_{s['id']}"] = False
                                    st.success("✅ Supplier diupdate!")
                                    st.rerun()
                            with c2:
                                if st.form_submit_button("❌ Batal"):
                                    st.session_state[f"edit_sup_{s['id']}"] = False
                                    st.rerun()

    # ═══════════════════ TAB 3: KATEGORI ═══════════════════
    with tabs[2]:
        st.subheader("📂 Database Kategori")
        st.caption("Kelola kategori produk. Terhubung dengan modul SKU & inventaris.")

        with st.expander("➕ Tambah Kategori Baru", expanded=False):
            kat_nama = st.text_input("Nama Kategori *", placeholder="Elektronik, Pakaian, dll.", key="master_kat_nama")
            kat_ket = st.text_input("Keterangan", placeholder="Deskripsi kategori...", key="master_kat_ket")
            if st.button("💾 Simpan Kategori", type="primary", key="master_kat_simpan"):
                if not kat_nama.strip():
                    st.error("Nama kategori wajib diisi!")
                else:
                    try:
                        db.execute("INSERT INTO kategori_produk (nama, keterangan) VALUES (?, ?)", (kat_nama.strip(), kat_ket.strip()))
                        st.success(f"✅ Kategori '{kat_nama.strip()}' ditambahkan!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal: {e}")

        st.markdown("---")
        kat_rows = db.fetch_all(
            "SELECT k.*, (SELECT COUNT(*) FROM sku WHERE kategori = k.nama) as jml_sku, "
            "(SELECT COALESCE(SUM(stok), 0) FROM sku WHERE kategori = k.nama) as total_stok "
            "FROM kategori_produk k ORDER BY k.nama"
        )

        if not kat_rows:
            st.info("📭 Belum ada kategori. Tambahkan di atas.")
        else:
            total_sku_all = sum(k["jml_sku"] or 0 for k in kat_rows)
            st.caption(f"📊 Total: {len(kat_rows)} kategori | {total_sku_all} SKU terhubung")

            for k in kat_rows:
                with st.container(border=True):
                    kc1, kc2, kc3, kc4 = st.columns([3, 1, 1, 1])
                    with kc1:
                        st.markdown(f"**📂 {k['nama']}**")
                        if k["keterangan"]:
                            st.caption(f"📝 {k['keterangan']}")
                    with kc2:
                        st.metric("SKU", k["jml_sku"] or 0)
                    with kc3:
                        st.metric("Total Stok", f"{k['total_stok'] or 0:,}")
                    with kc4:
                        if st.button("✏️ Edit", key=f"master_kat_edit_{k['id']}"):
                            st.session_state[f"edit_kat_{k['id']}"] = True
                        if st.button("🗑️", key=f"master_kat_del_{k['id']}", help="Hapus kategori"):
                            db.execute("DELETE FROM kategori_produk WHERE id = ?", (k["id"],))
                            st.success(f"🗑️ Kategori '{k['nama']}' dihapus.")
                            st.rerun()
                    if st.session_state.get(f"edit_kat_{k['id']}"):
                        with st.form(f"master_kat_edit_form_{k['id']}"):
                            e_nama = st.text_input("Nama", value=k["nama"], key=f"master_kat_en_{k['id']}")
                            e_ket = st.text_input("Keterangan", value=k["keterangan"] or "", key=f"master_kat_ekt_{k['id']}")
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.form_submit_button("💾 Simpan"):
                                    db.execute("UPDATE kategori_produk SET nama = ?, keterangan = ? WHERE id = ?", (e_nama.strip(), e_ket.strip(), k["id"]))
                                    st.session_state[f"edit_kat_{k['id']}"] = False
                                    st.success("✅ Kategori diupdate!")
                                    st.rerun()
                            with c2:
                                if st.form_submit_button("❌ Batal"):
                                    st.session_state[f"edit_kat_{k['id']}"] = False
                                    st.rerun()

    # ═══════════════════ TAB 4: TOKO ═══════════════════
    with tabs[3]:
        st.subheader("🏬 Database Toko Marketplace")
        st.caption("Kelola daftar toko di marketplace. Terhubung dengan scan operasional & penjualan.")

        with st.expander("➕ Tambah Toko Baru", expanded=False):
            toko_baru = st.text_input("Nama Toko", placeholder="Contoh: MMA Official Store", key="master_toko_nama")
            if st.button("💾 Simpan Toko", type="primary", key="master_toko_simpan"):
                if toko_baru.strip():
                    try:
                        db.execute("INSERT INTO toko (nama) VALUES (?)", (toko_baru.strip(),))
                        st.success(f"✅ Toko '{toko_baru.strip()}' ditambahkan!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal: {e}")
                else:
                    st.warning("Nama toko tidak boleh kosong.")

        st.markdown("---")
        all_toko = db.fetch_all("SELECT * FROM toko ORDER BY nama")

        if not all_toko:
            st.info("📭 Belum ada toko.")
        else:
            for t in all_toko:
                packed_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE toko = ? AND status = 'PACKED' AND kategori = 'REGULER'", (t["nama"],))
                instant_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE toko = ? AND status = 'PACKED' AND tipe_kiriman = 'INSTANT'", (t["nama"],))
                pending_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE toko = ? AND status = 'PENDING'", (t["nama"],))
                cancel_cnt = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE toko = ? AND status = 'CANCEL'", (t["nama"],))
                penj_cnt = db.fetch_one("SELECT COUNT(DISTINCT no_pesanan) as cnt FROM penjualan WHERE nama_toko = ?", (t["nama"],))

                with st.container(border=True):
                    tc1, tc2, tc3 = st.columns([3, 1, 1])
                    with tc1:
                        st.markdown(f"**🏪 {t['nama']}**")
                        p = packed_cnt["cnt"] if packed_cnt else 0
                        i = instant_cnt["cnt"] if instant_cnt else 0
                        pe = pending_cnt["cnt"] if pending_cnt else 0
                        c = cancel_cnt["cnt"] if cancel_cnt else 0
                        pj = penj_cnt["cnt"] if penj_cnt else 0
                        st.caption(f"📦 Packed: {p} | 🚀 Instant: {i} | ⏳ Pending: {pe} | ❌ Cancel: {c} | 🛒 Orders: {pj}")
                    with tc2:
                        if st.button("✏️ Edit", key=f"master_toko_edit_{t['id']}"):
                            st.session_state[f"edit_toko_{t['id']}"] = True
                    with tc3:
                        if t["nama"] != "Mitra Mulia Abadi":
                            if st.button("🗑️", key=f"master_toko_del_{t['id']}", help="Hapus toko"):
                                has_scans = db.fetch_one("SELECT COUNT(*) as cnt FROM scan_aktif WHERE toko = ?", (t["nama"],))
                                if has_scans and has_scans["cnt"] > 0:
                                    st.warning(f"⚠️ Toko '{t['nama']}' punya {has_scans['cnt']} data scan. Tidak bisa dihapus.")
                                else:
                                    db.execute("DELETE FROM toko WHERE id = ?", (t["id"],))
                                    st.success(f"🗑️ Toko '{t['nama']}' dihapus.")
                                    st.rerun()
                    if st.session_state.get(f"edit_toko_{t['id']}"):
                        with st.form(f"master_toko_edit_form_{t['id']}"):
                            e_nama = st.text_input("Nama Toko", value=t["nama"], key=f"master_toko_en_{t['id']}")
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.form_submit_button("💾 Simpan"):
                                    db.execute("UPDATE toko SET nama = ? WHERE id = ?", (e_nama.strip(), t["id"]))
                                    st.session_state[f"edit_toko_{t['id']}"] = False
                                    if st.session_state.get("selected_store") == t["nama"]:
                                        st.session_state.selected_store = e_nama.strip()
                                    st.success("✅ Toko diupdate!")
                                    st.rerun()
                            with c2:
                                if st.form_submit_button("❌ Batal"):
                                    st.session_state[f"edit_toko_{t['id']}"] = False
                                    st.rerun()

    # ═══════════════════ TAB 5: BARANG BESAR ═══════════════════
    with tabs[4]:
        st.subheader("📦 Daftar Barang Besar")
        st.caption("Kelola daftar barang besar untuk keperluan scan packing (bak cuci, wastafel, gerobak, dll).")

        with st.expander("➕ Tambah Barang Besar Baru", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                nama_baru = st.text_input("Nama Barang", placeholder="Contoh: Bak Cuci Piring", key="master_bb_nama")
            with col2:
                ket_baru = st.text_input("Keterangan (opsional)", placeholder="Ukuran, bahan, dll", key="master_bb_ket")
            if st.button("💾 Simpan", type="primary", key="master_bb_simpan"):
                if nama_baru.strip():
                    try:
                        db.execute("INSERT INTO daftar_barang_besar (nama_barang, keterangan) VALUES (?, ?)", (nama_baru.strip(), ket_baru.strip()))
                        st.success(f"✅ '{nama_baru.strip()}' ditambahkan!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal: {e}")
                else:
                    st.warning("Nama barang tidak boleh kosong.")

        st.markdown("---")
        daftar = db.fetch_all("SELECT id, nama_barang, keterangan, created_at FROM daftar_barang_besar ORDER BY nama_barang")

        if not daftar:
            st.info("📭 Belum ada daftar barang besar.")
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
                    if st.button("🗑️", key=f"master_del_besar_{item['id']}", help=f"Hapus {item['nama_barang']}"):
                        db.execute("DELETE FROM daftar_barang_besar WHERE id = ?", (item["id"],))
                        st.success(f"🗑️ '{item['nama_barang']}' dihapus.")
                        st.rerun()

        st.markdown("---")
        st.subheader("📊 Statistik Scan Barang Besar")
        besar_scans = db.fetch_all(
            "SELECT s.keterangan_barang, s.kategori, COUNT(*) as cnt "
            "FROM scan_aktif s WHERE s.kategori = 'BESAR' AND s.keterangan_barang != '' "
            "GROUP BY s.keterangan_barang ORDER BY cnt DESC"
        )
        if besar_scans:
            df_bs = pd.DataFrame([dict(r) for r in besar_scans])
            df_bs = df_bs.rename(columns={"keterangan_barang": "Nama Barang", "kategori": "Kategori", "cnt": "Jumlah Scan"})
            st.dataframe(df_bs, width="stretch", hide_index=True)
        else:
            st.caption("Belum ada data scan barang besar.")

    # ═══════════════════ TAB 6: GUDANG / LOKASI ═══════════════════
    with tabs[5]:
        st.subheader("🏭 Database Gudang / Lokasi Stok")
        st.caption("Kelola lokasi gudang penyimpanan barang. Untuk tracking stok per lokasi.")

        with st.expander("➕ Tambah Gudang Baru", expanded=False):
            g_col1, g_col2 = st.columns(2)
            with g_col1:
                gud_nama = st.text_input("Nama Gudang *", placeholder="Gudang Utama", key="master_gud_nama")
            with g_col2:
                gud_lokasi = st.text_input("Lokasi / Alamat", placeholder="Jl. Raya...", key="master_gud_lokasi")
            gud_ket = st.text_area("Keterangan", placeholder="Kapasitas, jenis barang, dll.", key="master_gud_ket", height=68)
            if st.button("💾 Simpan Gudang", type="primary", key="master_gud_simpan"):
                if not gud_nama.strip():
                    st.error("Nama gudang wajib diisi!")
                else:
                    try:
                        db.execute("INSERT INTO gudang (nama, lokasi, keterangan) VALUES (?, ?, ?)", (gud_nama.strip(), gud_lokasi.strip(), gud_ket.strip()))
                        st.success(f"✅ Gudang '{gud_nama.strip()}' ditambahkan!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal: {e}")

        st.markdown("---")
        gud_rows = db.fetch_all("SELECT * FROM gudang ORDER BY nama")

        if not gud_rows:
            st.info("📭 Belum ada data gudang. Tambahkan di atas.")
        else:
            for g in gud_rows:
                with st.container(border=True):
                    gc1, gc2, gc3 = st.columns([3, 1, 1])
                    with gc1:
                        st.markdown(f"**🏭 {g['nama']}**")
                        details = []
                        if g["lokasi"]:
                            details.append(f"📍 {g['lokasi']}")
                        if g["keterangan"]:
                            details.append(f"📝 {g['keterangan']}")
                        if details:
                            st.caption(" | ".join(details))
                    with gc2:
                        st.caption(f"🕐 {g['created_at'][:10] if g['created_at'] else '-'}")
                    with gc3:
                        if st.button("✏️ Edit", key=f"master_gud_edit_{g['id']}"):
                            st.session_state[f"edit_gud_{g['id']}"] = True
                        if st.button("🗑️", key=f"master_gud_del_{g['id']}", help="Hapus gudang"):
                            db.execute("DELETE FROM gudang WHERE id = ?", (g["id"],))
                            st.success(f"🗑️ Gudang '{g['nama']}' dihapus.")
                            st.rerun()
                    if st.session_state.get(f"edit_gud_{g['id']}"):
                        with st.form(f"master_gud_edit_form_{g['id']}"):
                            e_nama = st.text_input("Nama Gudang", value=g["nama"], key=f"master_gud_en_{g['id']}")
                            e_lokasi = st.text_input("Lokasi", value=g["lokasi"] or "", key=f"master_gud_el_{g['id']}")
                            e_ket = st.text_area("Keterangan", value=g["keterangan"] or "", key=f"master_gud_ekt_{g['id']}")
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.form_submit_button("💾 Simpan"):
                                    db.execute("UPDATE gudang SET nama = ?, lokasi = ?, keterangan = ? WHERE id = ?", (e_nama.strip(), e_lokasi.strip(), e_ket.strip(), g["id"]))
                                    st.session_state[f"edit_gud_{g['id']}"] = False
                                    st.success("✅ Gudang diupdate!")
                                    st.rerun()
                            with c2:
                                if st.form_submit_button("❌ Batal"):
                                    st.session_state[f"edit_gud_{g['id']}"] = False
                                    st.rerun()


# ==================== AKUNTANSI: REKONSILIASI & LABA RUGI NERACA ====================
def render_rekonsiliasi():
    """Halaman Rekonsiliasi Marketplace - cocokkan penjualan dengan settlement file."""
    db = st.session_state.db

    st.title("📋 Rekonsiliasi Marketplace")
    st.caption("Upload file settlement dari Shopee/TikTok/Lazada, cocokkan dengan data penjualan, dan update potongan marketplace.")

    # ── Pilih Marketplace ──
    mp = st.selectbox("Pilih Marketplace", ["Shopee", "TikTok", "Lazada"], key="rek_mp")

    # ── Upload File Settlement ──
    with st.expander("📤 Upload File Settlement (CSV/Excel)", expanded=True):
        st.caption(f"Upload file settlement dari **{mp}**. Kolom harus berisi: No Pesanan, Tanggal, Jumlah, Potongan, Biaya Layanan, dll.")
        uploaded_file = st.file_uploader("Pilih file", type=["csv", "xlsx", "xls"], key="rek_file")

        if uploaded_file:
            try:
                if uploaded_file.name.endswith(".csv"):
                    df_raw = pd.read_csv(uploaded_file)
                else:
                    df_raw = pd.read_excel(uploaded_file)

                st.write("📋 Preview data:")
                st.dataframe(df_raw.head(10), width="stretch", hide_index=True)

                # ── Column Mapping ──
                st.markdown("### 🔗 Mapping Kolom")
                col_names = list(df_raw.columns)
                map_no_pesanan = st.selectbox("Kolom No Pesanan *", ["-- Pilih --"] + col_names, key="rek_map_order")
                map_tanggal = st.selectbox("Kolom Tanggal", ["-- Pilih --"] + col_names, key="rek_map_tgl")
                map_jumlah = st.selectbox("Kolom Jumlah (Rp)", ["-- Pilih --"] + col_names, key="rek_map_jml")
                map_potongan = st.selectbox("Kolom Potongan (Rp)", ["-- Pilih --"] + col_names, key="rek_map_pot")
                map_biaya = st.selectbox("Kolom Biaya Layanan (opsional)", ["-- Pilih --"] + col_names, key="rek_map_biaya")

                if st.button("🚀 Proses Rekonsiliasi", type="primary", key="rek_proses"):
                    if map_no_pesanan == "-- Pilih --":
                        st.error("Kolom No Pesanan wajib dipilih!")
                    else:
                        matched = []
                        unmatched = []
                        updated = 0
                        total_potongan = 0.0

                        for _, row in df_raw.iterrows():
                            no_pesanan = str(row[map_no_pesanan]).strip() if pd.notna(row[map_no_pesanan]) else ""
                            if not no_pesanan:
                                continue

                            # Parse numeric values safely
                            def _parse_num(val):
                                if val is None or (isinstance(val, float) and pd.isna(val)):
                                    return 0.0
                                try:
                                    s = str(val).replace("Rp", "").replace(".", "").replace(",", ".").strip()
                                    return float(s)
                                except:
                                    return 0.0

                            jumlah = _parse_num(row[map_jumlah]) if map_jumlah != "-- Pilih --" else 0
                            potongan = _parse_num(row[map_potongan]) if map_potongan != "-- Pilih --" else 0
                            biaya = _parse_num(row[map_biaya]) if map_biaya != "-- Pilih --" else 0
                            total_pot = potongan + biaya

                            # Cari di penjualan
                            found = db.fetch_one(
                                "SELECT id, no_pesanan, total_harga, marketplace, nama_produk, potongan_marketplace, status_settlement "
                                "FROM penjualan WHERE no_pesanan = ? LIMIT 1",
                                (no_pesanan,),
                            )

                            if found:
                                # Update potongan & settlement status
                                db.execute(
                                    "UPDATE penjualan SET potongan_marketplace = ?, status_settlement = 'SETTLED' WHERE id = ?",
                                    (total_pot, found["id"]),
                                )
                                total_potongan += total_pot
                                updated += 1
                                matched.append({
                                    "No Pesanan": no_pesanan,
                                    "Produk": found["nama_produk"][:50] if found["nama_produk"] else "-",
                                    "Total Penjualan": found["total_harga"] or 0,
                                    "Potongan (File)": total_pot,
                                    "Status": "✓ Matched & Updated",
                                })
                            else:
                                unmatched.append({
                                    "No Pesanan": no_pesanan,
                                    "Jumlah (File)": jumlah,
                                    "Potongan (File)": total_pot,
                                    "Status": "✗ Tidak Ditemukan",
                                })

                        # ── Results ──
                        st.markdown("---")
                        st.markdown("### 📊 Hasil Rekonsiliasi")
                        res_col1, res_col2, res_col3 = st.columns(3)
                        with res_col1:
                            st.metric("✓ Matched & Updated", updated)
                        with res_col2:
                            st.metric("✗ Unmatched", len(unmatched))
                        with res_col3:
                            st.metric("💰 Total Potongan", f"Rp {total_potongan:,.0f}")

                        if matched:
                            st.markdown("#### ✅ Data Matched")
                            df_m = pd.DataFrame(matched)
                            st.dataframe(df_m, width="stretch", height=300, hide_index=True)

                        if unmatched:
                            st.markdown("#### ⚠️ Unmatched - Perlu Investigasi")
                            st.warning(f"{len(unmatched)} pesanan dari file settlement tidak ditemukan di database penjualan.")
                            df_u = pd.DataFrame(unmatched)
                            st.dataframe(df_u, width="stretch", height=250, hide_index=True)

                if st.button("🔄 Reset Form", key="rek_reset"):
                    st.rerun()

            except Exception as e:
                st.error(f"❌ Gagal membaca file: {e}")

    # ── Status Rekonsiliasi Saat Ini ──
    st.markdown("---")
    st.markdown("### 📊 Status Settlement Saat Ini")

    settled = db.fetch_one("SELECT COUNT(*) as cnt FROM penjualan WHERE status_settlement = 'SETTLED'")
    unsettled = db.fetch_one("SELECT COUNT(*) as cnt FROM penjualan WHERE status_settlement = 'UNSETTLED'")
    total_pot = db.fetch_one("SELECT COALESCE(SUM(potongan_marketplace), 0) as tot FROM penjualan WHERE status_settlement = 'SETTLED'")

    s_col1, s_col2, s_col3 = st.columns(3)
    with s_col1:
        st.metric("✅ Settled", f"{settled['cnt']:,}" if settled else "0")
    with s_col2:
        st.metric("⏳ Unsettled", f"{unsettled['cnt']:,}" if unsettled else "0")
    with s_col3:
        st.metric("💰 Total Potongan MP", f"Rp {total_pot['tot']:,.0f}" if total_pot else "Rp 0")

    # ── Rekap: Penjualan vs Pencairan vs Potongan ──
    st.markdown("---")
    st.markdown("### 📋 Rekap: Penjualan vs Pencairan vs Potongan")

    total_penj = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM penjualan "
        "INNER JOIN scan_aktif ON penjualan.no_resi = scan_aktif.resi "
        "WHERE scan_aktif.status = 'PACKED'"
    )
    total_cair = db.fetch_one("SELECT COALESCE(SUM(jumlah), 0) as tot FROM pencairan")
    total_pot_all = db.fetch_one("SELECT COALESCE(SUM(potongan_marketplace), 0) as tot FROM penjualan")
    selisih = (total_penj["tot"] if total_penj else 0) - (total_cair["tot"] if total_cair else 0) - (total_pot_all["tot"] if total_pot_all else 0)

    rec_col1, rec_col2, rec_col3, rec_col4 = st.columns(4)
    with rec_col1:
        st.metric("📦 Total Penjualan PACKED", f"Rp {total_penj['tot']:,.0f}" if total_penj else "Rp 0")
    with rec_col2:
        st.metric("💵 Total Pencairan", f"Rp {total_cair['tot']:,.0f}" if total_cair else "Rp 0")
    with rec_col3:
        st.metric("🔻 Total Potongan", f"Rp {total_pot_all['tot']:,.0f}" if total_pot_all else "Rp 0")
    with rec_col4:
        st.metric("📊 Selisih", f"Rp {selisih:,.0f}",
                 delta="✅ Seimbang" if abs(selisih) < 100 else "⚠️ Perlu Cek",
                 delta_color="normal" if abs(selisih) < 100 else "inverse")


def render_laba_rugi_neraca():
    """Halaman Laba Rugi & Neraca - dashboard akuntansi terintegrasi."""
    db = st.session_state.db

    st.title("📊 Laba Rugi & Neraca")
    st.caption("Dashboard akuntansi ringkas - menggabungkan data penjualan, OPEX, pencairan, dan inventaris.")

    # ── Filter Tanggal ──
    st.markdown("### 📅 Periode Laporan")
    today = datetime.now()
    f_col1, f_col2, f_col3 = st.columns([2, 2, 1])
    with f_col1:
        start_date = st.date_input("Dari Tanggal", value=today.replace(day=1).date(), key="lr_start")
    with f_col2:
        end_date = st.date_input("Sampai Tanggal", value=today.date(), key="lr_end")
    with f_col3:
        st.write("")
        if st.button("🔄 Refresh", width="stretch", key="lr_refresh"):
            st.rerun()

    start_str = start_date.strftime("%d-%m-%Y") if start_date else today.replace(day=1).strftime("%d-%m-%Y")
    end_str = end_date.strftime("%d-%m-%Y") if end_date else today.strftime("%d-%m-%Y")

    # ═══════════════════ LABA RUGI (INCOME STATEMENT) ═══════════════════
    st.markdown("---")
    st.markdown("## 💰 Laporan Laba Rugi")
    st.caption(f"Periode: {start_str} - {end_str}")

    # ── Pendapatan: Penjualan PACKED ──
    pendapatan_rows = db.fetch_all(
        "SELECT p.id, p.no_pesanan, p.total_harga, p.qty, p.sku_terdeteksi, p.potongan_marketplace "
        "FROM penjualan p INNER JOIN scan_aktif s ON p.no_resi = s.resi "
        "WHERE s.status = 'PACKED' AND s.tanggal >= ? AND s.tanggal <= ?",
        (start_str, end_str),
    )
    total_pendapatan = sum(r["total_harga"] or 0 for r in pendapatan_rows)
    total_potongan = sum(r["potongan_marketplace"] or 0 for r in pendapatan_rows)
    pendapatan_bersih = total_pendapatan - total_potongan

    # ── HPP (Harga Pokok Penjualan) ──
    sku_codes = list(set(r["sku_terdeteksi"] for r in pendapatan_rows if r["sku_terdeteksi"]))
    sku_harga = {}
    if sku_codes:
        ph = ",".join(["?" for _ in sku_codes])
        for sr in db.fetch_all(f"SELECT kode_sku, harga_beli FROM sku WHERE kode_sku IN ({ph})", sku_codes):
            sku_harga[sr["kode_sku"]] = sr["harga_beli"] or 0

    total_hpp = 0.0
    hpp_fallback_count = 0
    for r in pendapatan_rows:
        sku = r["sku_terdeteksi"]
        qty = r["qty"] or 1
        if sku and sku in sku_harga and sku_harga[sku] > 0:
            total_hpp += sku_harga[sku] * qty
        else:
            # Fallback: 40% dari total_harga
            total_hpp += (r["total_harga"] or 0) * 0.4
            if sku:
                hpp_fallback_count += 1

    # ── OPEX Variable (LUNAS) ──
    opex_var = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex "
        "WHERE tipe = 'VARIABLE' AND status_bayar = 'LUNAS' AND tanggal >= ? AND tanggal <= ?",
        (start_str, end_str),
    )
    total_opex_var = opex_var["tot"] if opex_var else 0

    # ── OPEX Tetap (LUNAS) - proporsional ──
    opex_tetap = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex "
        "WHERE tipe = 'TETAP' AND status_bayar = 'LUNAS' AND tanggal >= ? AND tanggal <= ?",
        (start_str, end_str),
    )
    total_opex_tetap = opex_tetap["tot"] if opex_tetap else 0

    # ── Beban Depresiasi Aset Tetap ──
    depr_data = db.fetch_all("SELECT akumulasi_depresiasi FROM aset_tetap")
    total_depresiasi_akum = sum(d["akumulasi_depresiasi"] or 0 for d in depr_data) if depr_data else 0
    # Depresiasi dalam periode = akumulasi saat ini (sudah termasuk bulan ini via tombol Hitung)

    # ── Beban Bunga Pinjaman (dari OPEX kategori Beban Bunga, LUNAS) ──
    beban_bunga = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex "
        "WHERE kategori = 'Beban Bunga' AND status_bayar = 'LUNAS' AND tanggal >= ? AND tanggal <= ?",
        (start_str, end_str),
    )
    total_beban_bunga = beban_bunga["tot"] if beban_bunga else 0

    # ── Biaya Kirim / Retur ──
    biaya_kirim = db.fetch_one(
        "SELECT COALESCE(SUM(nominal_klaim), 0) as tot FROM retur_klaim "
        "WHERE status = 'KLAIM' AND status_klaim = 'BERHASIL' AND tanggal >= ? AND tanggal <= ?",
        (start_str, end_str),
    )
    total_biaya_kirim = biaya_kirim["tot"] if biaya_kirim else 0

    total_biaya = total_hpp + total_opex_var + total_opex_tetap + total_biaya_kirim + total_depresiasi_akum + total_beban_bunga

    # ── Laba Bersih ──
    laba_bersih = pendapatan_bersih - total_biaya
    margin_pct = (laba_bersih / pendapatan_bersih * 100) if pendapatan_bersih > 0 else 0

    # ═══════════ DISPLAY LABA RUGI ═══════════
    lr_col1, lr_col2, lr_col3 = st.columns(3)

    with lr_col1:
        st.markdown("### 📈 Pendapatan")
        st.metric("Total Pendapatan (Gross)", f"Rp {total_pendapatan:,.0f}")
        st.metric("Potongan Marketplace", f"Rp {total_potongan:,.0f}")
        st.metric("✅ Pendapatan Bersih", f"Rp {pendapatan_bersih:,.0f}")

    with lr_col2:
        st.markdown("### 📉 Biaya")
        st.metric("HPP (Harga Pokok)", f"Rp {total_hpp:,.0f}",
                 help=f"{hpp_fallback_count} item pakai estimasi 40%" if hpp_fallback_count > 0 else "Semua dari SKU")
        st.metric("OPEX Variable (Packing)", f"Rp {total_opex_var:,.0f}")
        st.metric("OPEX Tetap (Bulanan)", f"Rp {total_opex_tetap:,.0f}")
        st.metric("Biaya Kirim/Retur", f"Rp {total_biaya_kirim:,.0f}")
        st.metric("Beban Depresiasi", f"Rp {total_depresiasi_akum:,.0f}",
                 help="Akumulasi depresiasi aset tetap (garis lurus)")
        st.metric("Beban Bunga Pinjaman", f"Rp {total_beban_bunga:,.0f}",
                 help="Bunga pinjaman bank bulanan (dari amortisasi otomatis)")
        st.metric("📊 Total Biaya", f"Rp {total_biaya:,.0f}")

    with lr_col3:
        st.markdown("### 💎 Hasil")
        st.metric("💰 Laba Bersih", f"Rp {laba_bersih:,.0f}",
                 delta=f"{margin_pct:.1f}% margin",
                 delta_color="normal" if laba_bersih >= 0 else "inverse")

    # Progress bar: expense ratio
    if pendapatan_bersih > 0:
        exp_ratio = total_biaya / pendapatan_bersih
        ratio_pct = exp_ratio * 100
        st.progress(min(exp_ratio, 1.0),
                    text=f"📊 Expense Ratio: {ratio_pct:.1f}% (Biaya / Pendapatan Bersih)")
        if ratio_pct > 90:
            st.warning("⚠️ Expense ratio di atas 90% - margin sangat tipis!")
        elif ratio_pct < 50:
            st.success("✅ Expense ratio sehat di bawah 50%.")

    # ═══════════════════ NERACA (BALANCE SHEET) LENGKAP ═══════════════════
    st.markdown("---")
    st.markdown("## 📊 Neraca Keuangan Lengkap")
    st.caption(f"Posisi per: {end_str} - mencakup Aset Lancar, Aset Tetap, Kewajiban, dan Ekuitas.")

    # ── ASET LANCAR ──
    # Inventaris (stok)
    inv_val = db.fetch_one("SELECT COALESCE(SUM(stok * harga_beli), 0) as tot FROM sku")
    total_inventaris = inv_val["tot"] if inv_val else 0

    # Kas = Total Pencairan (all-time)
    all_kas = db.fetch_one("SELECT COALESCE(SUM(jumlah), 0) as tot FROM pencairan")
    # Kas periode
    kas_periode = db.fetch_one(
        "SELECT COALESCE(SUM(jumlah), 0) as tot FROM pencairan WHERE tanggal >= ? AND tanggal <= ?",
        (start_str, end_str),
    )
    total_kas = all_kas["tot"] if all_kas else 0  # All-time for neraca position

    # Piutang Marketplace = Penjualan PACKED - Pencairan - Potongan
    all_packed_val = db.fetch_one(
        "SELECT COALESCE(SUM(p.total_harga), 0) as tot FROM penjualan p "
        "INNER JOIN scan_aktif s ON p.no_resi = s.resi WHERE s.status = 'PACKED'"
    )
    all_pot_val = db.fetch_one("SELECT COALESCE(SUM(potongan_marketplace), 0) as tot FROM penjualan")
    piutang = (all_packed_val["tot"] if all_packed_val else 0) - (all_kas["tot"] if all_kas else 0) - (all_pot_val["tot"] if all_pot_val else 0)
    piutang = max(0, piutang)

    # Sewa Dibayar di Muka (aset lancar)
    sewa_dimuka = db.fetch_one("SELECT COALESCE(SUM(sisa_belum_diakui), 0) as tot FROM biaya_dibayar_dimuka WHERE status = 'AKTIF'")
    total_sewa_dimuka = sewa_dimuka["tot"] if sewa_dimuka else 0

    total_aset_lancar = total_inventaris + total_kas + piutang + total_sewa_dimuka

    # ── ASET TETAP ──
    aset_data = db.fetch_all("SELECT harga_perolehan, akumulasi_depresiasi FROM aset_tetap")
    total_harga_aset = sum(a["harga_perolehan"] or 0 for a in aset_data) if aset_data else 0
    total_akum_depr = sum(a["akumulasi_depresiasi"] or 0 for a in aset_data) if aset_data else 0
    nilai_buku_aset = total_harga_aset - total_akum_depr

    # ── TOTAL ASET ──
    total_aset = total_aset_lancar + nilai_buku_aset

    # ── KEWAJIBAN ──
    utang_pemb = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM pembelian "
        "WHERE status_bayar IN ('PENDING', 'KONTRA BON')"
    )
    utang_opex = db.fetch_one(
        "SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE status_bayar = 'PENDING'"
    )
    # Utang Bank (sisa pokok pinjaman AKTIF)
    utang_bank = db.fetch_one("SELECT COALESCE(SUM(sisa_pokok), 0) as tot FROM pinjaman WHERE status = 'AKTIF'")
    total_utang = (utang_pemb["tot"] if utang_pemb else 0) + (utang_opex["tot"] if utang_opex else 0) + (utang_bank["tot"] if utang_bank else 0)

    # ── EKUITAS ──
    # Modal awal + tambahan
    modal_awal = db.fetch_one("SELECT COALESCE(SUM(jumlah), 0) as tot FROM modal WHERE jenis = 'AWAL'")
    modal_tambahan = db.fetch_one("SELECT COALESCE(SUM(jumlah), 0) as tot FROM modal WHERE jenis = 'TAMBAHAN'")
    total_modal_disetor = (modal_awal["tot"] if modal_awal else 0) + (modal_tambahan["tot"] if modal_tambahan else 0)

    # Laba Ditahan = Laba Bersih Kumulatif (all-time)
    # Hitung all-time net profit dari penjualan PACKED
    all_packed_alltime = db.fetch_one(
        "SELECT COALESCE(SUM(p.total_harga), 0) as tot FROM penjualan p "
        "INNER JOIN scan_aktif s ON p.no_resi = s.resi WHERE s.status = 'PACKED'"
    )
    all_gross_alltime = all_packed_alltime["tot"] if all_packed_alltime else 0

    all_pot_alltime = db.fetch_one("SELECT COALESCE(SUM(potongan_marketplace), 0) as tot FROM penjualan")
    all_pot_val_alltime = all_pot_alltime["tot"] if all_pot_alltime else 0

    all_opex_alltime = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM opex WHERE status_bayar = 'LUNAS'")
    all_opex_val_alltime = all_opex_alltime["tot"] if all_opex_alltime else 0

    all_pemb_lunas_alltime = db.fetch_one("SELECT COALESCE(SUM(total_harga), 0) as tot FROM pembelian WHERE status_bayar = 'LUNAS'")
    all_pemb_val_alltime = all_pemb_lunas_alltime["tot"] if all_pemb_lunas_alltime else 0

    # HPP all-time (estimasi)
    all_hpp_alltime = all_gross_alltime * 0.4  # rough estimate

    all_klaim_alltime = db.fetch_one(
        "SELECT COALESCE(SUM(nominal_klaim), 0) as tot FROM retur_klaim WHERE status_klaim = 'BERHASIL'"
    )
    all_klaim_val_alltime = all_klaim_alltime["tot"] if all_klaim_alltime else 0

    laba_ditahan = all_gross_alltime - all_pot_val_alltime - all_hpp_alltime - all_opex_val_alltime - all_pemb_val_alltime + all_klaim_val_alltime - total_akum_depr

    total_ekuitas = total_modal_disetor + laba_ditahan

    # ── Keseimbangan Neraca ──
    total_pasiva = total_utang + total_ekuitas
    selisih_neraca = total_aset - total_pasiva

    # ═══════════ DISPLAY NERACA ═══════════
    ner_col1, ner_col2 = st.columns(2)

    with ner_col1:
        st.markdown("### 🏦 ASET")
        st.markdown("#### 💵 Aset Lancar")
        st.metric("📦 Nilai Inventaris", f"Rp {total_inventaris:,.0f}")
        st.metric("💵 Kas (Pencairan All-Time)", f"Rp {total_kas:,.0f}")
        st.metric("🪙 Piutang Marketplace", f"Rp {piutang:,.0f}")
        st.metric("📅 Sewa Dibayar di Muka", f"Rp {total_sewa_dimuka:,.0f}",
                 help="Biaya yang sudah dibayar di muka, diamortisasi per bulan")
        st.caption(f"Aset Lancar: Rp {total_aset_lancar:,.0f}")

        st.markdown("#### 🏭 Aset Tetap")
        st.metric("🏗️ Harga Perolehan", f"Rp {total_harga_aset:,.0f}")
        st.metric("📉 Akum. Depresiasi", f"Rp {total_akum_depr:,.0f}")
        st.metric("📊 Nilai Buku", f"Rp {nilai_buku_aset:,.0f}")

        st.markdown("---")
        st.metric("### 📊 TOTAL ASET", f"Rp {total_aset:,.0f}",
                 help="Aset Lancar + Aset Tetap")

    with ner_col2:
        st.markdown("### 📋 KEWAJIBAN")
        st.metric("🛒 Utang Pembelian SKU", f"Rp {utang_pemb['tot']:,.0f}" if utang_pemb else "Rp 0")
        st.metric("📝 Utang OPEX", f"Rp {utang_opex['tot']:,.0f}" if utang_opex else "Rp 0")
        st.metric("🏦 Utang Bank / Pinjaman", f"Rp {utang_bank['tot']:,.0f}" if utang_bank else "Rp 0",
                 help="Sisa pokok pinjaman yang masih AKTIF")
        st.markdown("---")
        st.metric("### 📊 TOTAL KEWAJIBAN", f"Rp {total_utang:,.0f}")

        st.markdown("---")
        st.markdown("### 💎 EKUITAS")
        st.metric("🏁 Modal Disetor", f"Rp {total_modal_disetor:,.0f}",
                 help=f"Awal: Rp {modal_awal['tot']:,.0f} | Tambahan: Rp {modal_tambahan['tot']:,.0f}" if modal_awal and modal_tambahan else "")
        st.metric("📈 Laba Ditahan (All-Time)", f"Rp {laba_ditahan:,.0f}",
                 help="Akumulasi laba bersih semua periode (estimasi HPP 40%)")
        st.markdown("---")
        st.metric("### 💰 TOTAL EKUITAS", f"Rp {total_ekuitas:,.0f}")

    # ── NERACA BALANCE CHECK ──
    st.markdown("---")
    bal_col1, bal_col2, bal_col3 = st.columns(3)
    with bal_col1:
        st.metric("📊 Total Aset", f"Rp {total_aset:,.0f}")
    with bal_col2:
        st.metric("📋 Total Kewajiban + Ekuitas", f"Rp {total_pasiva:,.0f}")
    with bal_col3:
        if abs(selisih_neraca) < 100:
            st.success(f"✅ Neraca Seimbang (selisih Rp {selisih_neraca:,.0f})")
        else:
            st.error(f"❌ Ada Selisih Rp {selisih_neraca:,.0f} - Perlu audit!")
            st.caption("Selisih bisa disebabkan: HPP estimasi 40%, data pencairan belum lengkap, atau transaksi belum direkonsiliasi.")

    # ── Quick Ratio ──
    if total_utang > 0:
        quick_ratio = (total_kas + piutang) / total_utang
        ratio_color = "🟢" if quick_ratio >= 1.5 else ("🟡" if quick_ratio >= 1.0 else "🔴")
        st.info(
            f"{ratio_color} **Quick Ratio: {quick_ratio:.2f}** "
            f"(Kas + Piutang / Utang). "
            f"{'Sehat - mampu bayar kewajiban jangka pendek.' if quick_ratio >= 1.5 else ('Cukup - perhatikan cashflow.' if quick_ratio >= 1.0 else '⚠️ Risiko likuiditas - kas & piutang tidak cukup menutup utang.')}"
        )

    # ── Export ──
    st.markdown("---")
    if st.button("📊 Export Laporan Laba Rugi & Neraca (Excel)", type="primary", key="lr_export"):
        data = {
            "Komponen": [
                "Pendapatan Gross", "Potongan Marketplace", "Pendapatan Bersih",
                "HPP", "OPEX Variable", "OPEX Tetap", "Biaya Kirim/Retur", "Beban Depresiasi", "Total Biaya",
                "LABA BERSIH", "",
                "ASET LANCAR", "Nilai Inventaris", "Kas (Pencairan)", "Piutang Marketplace",
                "ASET TETAP", "Harga Perolehan", "Akum. Depresiasi", "Nilai Buku",
                "TOTAL ASET", "",
                "KEWAJIBAN", "Utang Pembelian", "Utang OPEX",
                "EKUITAS", "Modal Disetor", "Laba Ditahan",
                "TOTAL KEWAJIBAN + EKUITAS", "SELISIH NERACA",
            ],
            "Jumlah (Rp)": [
                total_pendapatan, total_potongan, pendapatan_bersih,
                total_hpp, total_opex_var, total_opex_tetap, total_biaya_kirim, total_depresiasi_akum, total_biaya,
                laba_bersih, "",
                total_aset_lancar, total_inventaris, total_kas, piutang,
                nilai_buku_aset, total_harga_aset, total_akum_depr, nilai_buku_aset,
                total_aset, "",
                total_utang, utang_pemb["tot"] if utang_pemb else 0, utang_opex["tot"] if utang_opex else 0,
                total_ekuitas, total_modal_disetor, laba_ditahan,
                total_pasiva, selisih_neraca,
            ],
        }
        df_export = pd.DataFrame(data)
        filename = f"Laba_Rugi_Neraca_{start_str}_sd_{end_str}.xlsx"
        filepath = os.path.join(Config.SALES_FOLDER, filename)
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            df_export.to_excel(writer, index=False, sheet_name="Laba Rugi & Neraca")
        with open(filepath, "rb") as fp:
            st.download_button(
                "⬇️ Download Laporan",
                fp,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        st.success(f"✅ Laporan tersimpan: {filename}")


# ═══════════════════════════════════════════
# ── AKUNTANSI AKRUAL: Jurnal & Auto-Posting ──
# ═══════════════════════════════════════════

def post_jurnal(db, tanggal, no_ref, deskripsi, entries, sumber="", id_sumber=0):
    """Catat double-entry journal. entries = [(kode_akun, nama, debit, kredit), ...]"""
    for kode, nama, deb, kred in entries:
        db.execute(
            "INSERT INTO jurnal_umum (tanggal, no_ref, kode_akun, nama_akun, deskripsi, debit, kredit, sumber, id_sumber) VALUES (?,?,?,?,?,?,?,?,?)",
            (tanggal, no_ref, kode, nama, deskripsi, deb, kred, sumber, id_sumber),
        )


def auto_post_penjualan(db, penjualan_id, no_pesanan, tanggal, marketplace, total_harga, hpp, fee_mp, ppn=0):
    """Auto-posting jurnal saat pesanan di-PACKED (akrual)."""
    # Debit: Piutang Usaha / Kas, Kredit: Pendapatan Penjualan
    post_jurnal(db, tanggal, f"INV-{no_pesanan}", f"Penjualan {marketplace}",
        [("1-1100", "Piutang Usaha", total_harga, 0),
         ("4-1000", "Pendapatan Penjualan", 0, total_harga)], "penjualan", penjualan_id)
    # HPP
    if hpp > 0:
        post_jurnal(db, tanggal, f"INV-{no_pesanan}", f"HPP {marketplace}",
            [("5-1000", "Harga Pokok Penjualan", hpp, 0),
             ("1-1200", "Persediaan Barang", 0, hpp)], "penjualan", penjualan_id)
    # Fee Marketplace
    if fee_mp > 0:
        post_jurnal(db, tanggal, f"INV-{no_pesanan}", f"Fee {marketplace}",
            [("5-1100", "Beban Fee Marketplace", fee_mp, 0),
             ("1-1100", "Piutang Usaha", 0, fee_mp)], "penjualan", penjualan_id)


def auto_post_opex(db, opex_id, tanggal, kategori, total, tipe="VARIABLE"):
    """Auto-posting jurnal untuk beban operasional (akrual)."""
    akun_map = {
        "Bubble Wrap": "5-1200", "Kardus": "5-1200", "Lakban / Selotip": "5-1200",
        "Bensin / Transport Harian": "5-1800", "Packing Lainnya": "5-1200",
        "Gaji / Upah": "5-1400", "Internet": "5-2000", "Listrik": "5-1900",
        "Air": "5-1900", "Sewa Tempat": "5-2100", "Maintenance": "5-1300",
        "ATK": "5-1300", "Depresiasi": "5-1500", "Beban Bunga": "5-1600",
        "Amortisasi Sewa": "5-2100", "Iklan": "5-2300", "Lainnya": "5-1300",
    }
    kode = akun_map.get(kategori, "5-1300")
    nama = f"Beban {kategori}"
    post_jurnal(db, tanggal, f"OPEX-{opex_id}", f"{kategori} - {tipe}",
        [(kode, nama, total, 0), ("1-1000", "Kas & Bank", 0, total)], "opex", opex_id)


def auto_post_pembelian(db, pembelian_id, no_faktur, tanggal, supplier, total, ppn=0):
    """Auto-posting jurnal untuk pembelian SKU (akrual)."""
    post_jurnal(db, tanggal, f"PO-{no_faktur}", f"Pembelian dari {supplier}",
        [("1-1200", "Persediaan Barang", total, 0),
         ("2-1000", "Hutang Usaha", 0, total)], "pembelian", pembelian_id)


def post_packed_to_accounting(db, resi, tanggal=None):
    """Auto-posting jurnal saat resi di-PACKED. Dipanggil setelah INSERT scan_aktif PACKED."""
    if not tanggal:
        tanggal = datetime.now().strftime("%d-%m-%Y")
    # Cari data penjualan
    orders = db.fetch_all(
        "SELECT id, no_pesanan, marketplace, total_harga, nama_produk, qty, sku_terdeteksi, ppn "
        "FROM penjualan WHERE no_resi = ?",
        (resi,),
    )
    if not orders:
        return
    for o in orders:
        # Cek jurnal sudah ada? Hindari double posting
        existing = db.fetch_one(
            "SELECT COUNT(*) as cnt FROM jurnal_umum WHERE sumber='penjualan' AND id_sumber=?",
            (o["id"],),
        )
        if existing and existing["cnt"] > 0:
            continue
        # Hitung HPP
        hpp = 0
        if o["sku_terdeteksi"]:
            sku_row = db.fetch_one("SELECT harga_beli FROM sku WHERE kode_sku = ?", (o["sku_terdeteksi"].split(",")[0].strip(),))
            if sku_row and sku_row["harga_beli"]:
                hpp = sku_row["harga_beli"] * (o["qty"] or 1)
        if hpp == 0:
            hpp = (o["total_harga"] or 0) * 0.4  # fallback 40%
        # Fee marketplace (% dari pengaturan)
        fee_pct = 0
        mp = (o["marketplace"] or "").upper()
        settings = db.fetch_one("SELECT fee_shopee, fee_tiktok, fee_lazada FROM pengaturan LIMIT 1")
        if settings:
            if "SHOPEE" in mp: fee_pct = settings["fee_shopee"] or 0
            elif "TIKTOK" in mp: fee_pct = settings["fee_tiktok"] or 0
            elif "LAZADA" in mp: fee_pct = settings["fee_lazada"] or 0
        fee_mp = (o["total_harga"] or 0) * fee_pct / 100
        total = o["total_harga"] or 0
        ppn = o["ppn"] or 0
        # PPh Final 0.5% dari gross
        pph_pct = float(_get_setting(db, "pph_persen", "0.5"))
        pph = total * pph_pct / 100

        auto_post_penjualan(db, o["id"], o["no_pesanan"], tanggal, o["marketplace"] or "Unknown", total, hpp, fee_mp, ppn)
        # Post PPh Final
        if pph > 0:
            post_jurnal(db, tanggal, f"INV-{o['no_pesanan']}", f"PPh Final {pph_pct}% {o['marketplace']}",
                [("5-1700", "Beban Pajak", pph, 0),
                 ("1-1100", "Piutang Usaha", 0, pph)], "penjualan", o["id"])


def get_laba_rugi_akrual(db, tanggal=None, bulan=None):
    """Laba Rugi berbasis akrual dari jurnal (bukan cash basis)."""
    if bulan:
        where = f"WHERE strftime('%Y-%m', tanggal) = '{bulan}'"
    elif tanggal:
        where = f"WHERE tanggal = '{tanggal}'"
    else:
        where = ""

    # Pendapatan
    pendapatan = db.fetch_one(
        f"SELECT SUM(kredit) - SUM(debit) as total FROM jurnal_umum {where} AND kode_akun LIKE '4-%'"
    )
    # HPP
    hpp = db.fetch_one(
        f"SELECT SUM(debit) - SUM(kredit) as total FROM jurnal_umum {where} AND kode_akun = '5-1000'"
    )
    # Total Beban
    beban = db.fetch_one(
        f"SELECT SUM(debit) - SUM(kredit) as total FROM jurnal_umum {where} AND kode_akun LIKE '5-%' AND kode_akun != '5-1000'"
    )

    rev = (pendapatan["total"] or 0) if pendapatan else 0
    cogs = (hpp["total"] or 0) if hpp else 0
    opex = (beban["total"] or 0) if beban else 0

    gross = rev - cogs
    net = gross - opex
    return {"pendapatan": rev, "hpp": cogs, "gross_profit": gross, "total_beban": opex, "net_profit": net}


def get_neraca_akrual(db):
    """Neraca berbasis akrual dari jurnal + data operasional."""
    # Aset = SUM(debit) - SUM(kredit) untuk akun 1-xxxx
    aset = db.fetch_one(
        "SELECT SUM(debit) - SUM(kredit) as total FROM jurnal_umum WHERE kode_akun LIKE '1-%'"
    )
    # Liabilitas = SUM(kredit) - SUM(debit) untuk akun 2-xxxx
    liab = db.fetch_one(
        "SELECT SUM(kredit) - SUM(debit) as total FROM jurnal_umum WHERE kode_akun LIKE '2-%'"
    )
    # Ekuitas = SUM(kredit) - SUM(debit) untuk akun 3-xxxx + Laba Ditahan
    ekuitas = db.fetch_one(
        "SELECT SUM(kredit) - SUM(debit) as total FROM jurnal_umum WHERE kode_akun LIKE '3-%'"
    )
    # Laba dari jurnal (4-xxxx kredit - 5-xxxx debit)
    laba = db.fetch_one("""
        SELECT (SELECT SUM(kredit) - SUM(debit) FROM jurnal_umum WHERE kode_akun LIKE '4-%') -
               (SELECT SUM(debit) - SUM(kredit) FROM jurnal_umum WHERE kode_akun LIKE '5-%') as total
    """)

    total_aset = (aset["total"] or 0) if aset else 0
    total_liab = (liab["total"] or 0) if liab else 0
    total_ekuitas = (ekuitas["total"] or 0) if ekuitas else 0
    net_income = (laba["total"] or 0) if laba else 0

    return {
        "total_aset": total_aset,
        "total_liabilitas": total_liab,
        "total_ekuitas": total_ekuitas + net_income,
        "laba_berjalan": net_income,
        "balance": total_aset - (total_liab + total_ekuitas + net_income),
    }


def render_settlement_daily_import():
    """Halaman import settlement harian marketplace - update jurnal dengan angka AKTUAL."""
    st.subheader("📥 Import Settlement Harian Marketplace")
    st.caption("Upload CSV settlement dari marketplace. Sistem akan update jurnal estimasi → angka AKTUAL per pesanan.")
    db = st.session_state.db

    mp = st.selectbox("Marketplace", ["Shopee", "TikTok", "Lazada", "Tokopedia"])
    tgl = st.date_input("Tanggal Settlement", datetime.now())

    # Column mapping
    st.markdown("**Mapping Kolom CSV:** (sesuaikan dengan format settlement marketplace)")
    map_col1, map_col2, map_col3 = st.columns(3)
    with map_col1:
        col_pesanan = st.text_input("Kolom No Pesanan", "No Pesanan")
        col_gross = st.text_input("Kolom Gross (Rp)", "Total Penjualan")
    with map_col2:
        col_fee = st.text_input("Kolom Fee/Potongan (Rp)", "Total Fee")
        col_pph = st.text_input("Kolom PPh (Rp)", "PPh")
    with map_col3:
        col_cair = st.text_input("Kolom Pencairan (Rp)", "Pencairan")
        col_lain = st.text_input("Kolom Biaya Lain (Rp)", "Biaya Lain")

    uploaded = st.file_uploader("Upload CSV Settlement", type=["csv", "xlsx"])

    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                df = pd.read_csv(uploaded)
            else:
                df = pd.read_excel(uploaded)

            # Rename columns based on mapping
            rename_map = {}
            if col_pesanan in df.columns: rename_map[col_pesanan] = "no_pesanan"
            if col_gross in df.columns: rename_map[col_gross] = "gross"
            if col_fee in df.columns: rename_map[col_fee] = "fee"
            if col_pph in df.columns: rename_map[col_pph] = "pph"
            if col_cair in df.columns: rename_map[col_cair] = "pencairan"
            if col_lain in df.columns: rename_map[col_lain] = "biaya_lain"
            df = df.rename(columns=rename_map)

            st.dataframe(df.head(10), width="stretch")

            # Summary
            total_gross = df["gross"].sum() if "gross" in df.columns else 0
            total_fee = df["fee"].sum() if "fee" in df.columns else 0
            total_pph = df["pph"].sum() if "pph" in df.columns else 0
            total_biaya = df["biaya_lain"].sum() if "biaya_lain" in df.columns else 0
            total_cair = df["pencairan"].sum() if "pencairan" in df.columns else 0

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Gross", f"Rp {total_gross:,.0f}")
            c2.metric("Fee", f"Rp {total_fee:,.0f}")
            c3.metric("PPh", f"Rp {total_pph:,.0f}")
            c4.metric("Biaya Lain", f"Rp {total_biaya:,.0f}")
            c5.metric("Pencairan", f"Rp {total_cair:,.0f}")

            if st.button("💾 Import & Update Jurnal (AKTUAL)", type="primary"):
                tanggal_str = tgl.strftime("%d-%m-%Y")
                updated = 0
                for _, row in df.iterrows():
                    no_pes = str(row.get("no_pesanan", "")).strip()
                    if not no_pes or no_pes == "nan":
                        continue
                    gross = float(row.get("gross", 0) or 0)
                    fee = float(row.get("fee", 0) or 0)
                    pph = float(row.get("pph", 0) or 0)
                    biaya = float(row.get("biaya_lain", 0) or 0)

                    # Update penjualan with actual fee
                    db.execute(
                        "UPDATE penjualan SET potongan_marketplace = ?, status_settlement = 'SETTLED' WHERE no_pesanan = ?",
                        (fee, no_pes),
                    )

                    # Void old estimate jurnal for this order
                    db.execute(
                        "DELETE FROM jurnal_umum WHERE sumber = 'penjualan' AND no_ref LIKE ? AND deskripsi LIKE '%Fee%'",
                        (f"INV-{no_pes}%",),
                    )
                    db.execute(
                        "DELETE FROM jurnal_umum WHERE sumber = 'penjualan' AND no_ref LIKE ? AND deskripsi LIKE '%PPh%'",
                        (f"INV-{no_pes}%",),
                    )

                    # Post ACTUAL fee
                    if fee > 0:
                        post_jurnal(db, tanggal_str, f"INV-{no_pes}-AKTUAL",
                            f"Fee {mp} (AKTUAL)", [("5-1100", "Beban Fee Marketplace", fee, 0),
                            ("1-1100", "Piutang Usaha", 0, fee)], "settlement", 0)

                    # Post ACTUAL PPh
                    if pph > 0:
                        post_jurnal(db, tanggal_str, f"INV-{no_pes}-AKTUAL",
                            f"PPh Final {mp} (AKTUAL)", [("5-1700", "Beban Pajak", pph, 0),
                            ("1-1100", "Piutang Usaha", 0, pph)], "settlement", 0)

                    # Post biaya lain
                    if biaya > 0:
                        post_jurnal(db, tanggal_str, f"INV-{no_pes}-AKTUAL",
                            f"Biaya Lain {mp} (AKTUAL)", [("5-1300", "Beban Operasional Tetap", biaya, 0),
                            ("1-1100", "Piutang Usaha", 0, biaya)], "settlement", 0)

                    updated += 1

                # Save settlement summary
                db.execute(
                    "INSERT INTO settlement_harian (tanggal, marketplace, total_penjualan, total_fee, total_pencairan, total_biaya_lain) VALUES (?,?,?,?,?,?)",
                    (tanggal_str, mp, total_gross, total_fee, total_cair, total_biaya),
                )
                # Post pencairan to jurnal
                if total_cair > 0:
                    post_jurnal(db, tanggal_str, f"STL-{mp}-{tanggal_str}",
                        f"Pencairan {mp}", [("1-1000", "Kas & Bank", total_cair, 0),
                        ("1-1100", "Piutang Usaha", 0, total_cair)], "settlement", 0)

                st.success(f"✅ {updated} pesanan di-update dengan angka AKTUAL! Laba Rugi sekarang akurat.")
                st.rerun()

        except Exception as e:
            st.error(f"Error: {e}")

    # History
    st.divider()
    st.caption("Riwayat Settlement")
    rows = db.fetch_all("SELECT * FROM settlement_harian ORDER BY tanggal DESC LIMIT 30")
    if rows:
        df_hist = pd.DataFrame([dict(r) for r in rows])
        st.dataframe(df_hist, width="stretch", hide_index=True)


def render_iklan_harian():
    """Input biaya iklan harian per marketplace - bisa di-update kapan saja."""
    st.subheader("📢 Biaya Iklan Harian Marketplace")


# ═══════════════════════════════════════════
# ── GUDANG INVENTORY ──
# ═══════════════════════════════════════════

def _render_opname_by_sku(db, kode_sku):
    """Tampilkan form opname setelah SKU terdeteksi dari scan."""
    sku_info = db.fetch_one("SELECT * FROM sku WHERE kode_sku = ?", (kode_sku,))
    if not sku_info:
        st.error(f"❌ SKU `{kode_sku}` tidak ditemukan di database!")
        return

    stok_sistem = sku_info["stok"]
    st.markdown(f"""
    <div style="background:#1C1C1E;padding:16px;border-radius:12px;margin:10px 0;">
        <h3 style="margin:0;color:#0A84FF;">{sku_info['nama_barang']}</h3>
        <p style="margin:4px 0;color:#AEAEB2;">SKU: {kode_sku} | Kategori: {sku_info['kategori']} | Rak: {sku_info['posisi_rak'] or '-'}</p>
        <p style="margin:4px 0;">Stok Sistem: <b>{stok_sistem}</b> | Modal: Rp {sku_info['harga_beli']:,.0f} | Jual: Rp {sku_info['harga_jual']:,.0f}</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        stok_fisik = st.number_input("Stok Fisik (hitung manual)", min_value=0, value=stok_sistem, key=f"opname_scan_{kode_sku}")
    with col2:
        selisih = stok_fisik - stok_sistem
        if selisih != 0:
            st.metric("Selisih", f"{selisih:+d}", delta=f"{'Surplus' if selisih > 0 else 'Defisit'}")
        else:
            st.success("✅ Stok cocok!")

    ket = st.text_input("Keterangan", placeholder="Rusak, Hilang, Expired...", key=f"opname_scan_ket_{kode_sku}")

    if st.button("💾 Simpan Opname", type="primary", key=f"opname_scan_save_{kode_sku}"):
        db.execute(
            "INSERT INTO stock_opname (kode_sku, stok_sistem, stok_fisik, selisih, keterangan, operator, tanggal) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kode_sku, stok_sistem, stok_fisik, selisih, ket,
             st.session_state.user["username"] if st.session_state.user else "mobile", datetime.now().strftime("%d-%m-%Y %H:%M")),
        )
        db.execute("UPDATE sku SET stok = ?, updated_at = CURRENT_TIMESTAMP WHERE kode_sku = ?",
                   (stok_fisik, kode_sku))
        st.success(f"✅ Opname {kode_sku}: {stok_sistem} → {stok_fisik}")
        st.rerun()


# ═══════════════════════════════════════════


def render_gudang_inventory():
    """Halaman Gudang Inventory - Stok, Opname, Rak."""
    st.title("📦 Gudang Inventory SKU")
    db = st.session_state.db

    tab1, tab2, tab3, tab4 = st.tabs(["📊 Stok & Persediaan", "🔍 Stock Opname", "📸 Scan Opname (HP)", "🗄️ Rak & Posisi"])

    # ═══════════ TAB 1: STOK ═══════════
    with tab1:
        st.subheader("📊 Monitoring Stok SKU")

        # Filter
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filter_kategori = st.selectbox("Kategori", ["Semua"] + _get_kategori_list(db), key="gudang_kat")
        with col_f2:
            filter_rak = st.selectbox("Rak", ["Semua"] + _get_rak_list(db), key="gudang_rak")
        with col_f3:
            search_sku = st.text_input("Cari SKU/Nama", key="gudang_search")

        where = []
        if filter_kategori != "Semua":
            where.append(f"kategori = '{filter_kategori}'")
        if filter_rak != "Semua":
            where.append(f"posisi_rak = '{filter_rak}'")
        if search_sku:
            where.append(f"(kode_sku LIKE '%{search_sku}%' OR nama_barang LIKE '%{search_sku}%')")
        where_clause = " AND ".join(where) if where else "1=1"

        rows = db.fetch_all(
            f"SELECT kode_sku, nama_barang, kategori, stok, satuan, harga_beli, harga_jual, posisi_rak FROM sku WHERE {where_clause} ORDER BY kategori, nama_barang"
        )

        if rows:
            df = pd.DataFrame([dict(r) for r in rows])
            # Color-code stock levels
            def stok_color(val):
                if val <= 0: return 'background-color: #3D0000; color: #FF453A'
                elif val <= 5: return 'background-color: #3D2E00; color: #FF9F0A'
                return ''
            styled = df.style.map(stok_color, subset=['stok'])
            st.dataframe(styled, width="stretch", height=500, hide_index=True,
                         column_config={
                             "kode_sku": "Kode SKU", "nama_barang": "Nama Barang",
                             "kategori": "Kategori", "stok": st.column_config.NumberColumn("Stok"),
                             "satuan": "Satuan", "harga_beli": st.column_config.NumberColumn("Modal", format="Rp %.0f"),
                             "harga_jual": st.column_config.NumberColumn("Jual", format="Rp %.0f"),
                             "posisi_rak": "Rak",
                         })

            # Quick stats
            total_sku = len(df)
            total_stok = df["stok"].sum()
            total_value = (df["stok"] * df["harga_beli"]).sum()
            low_stock = len(df[df["stok"] <= 5])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total SKU", total_sku)
            c2.metric("Total Stok", f"{total_stok:,}")
            c3.metric("Nilai Inventory", f"Rp {total_value:,.0f}")
            c4.metric("Stok Menipis (≤5)", low_stock)
        else:
            st.info("Belum ada data SKU.")

    # ═══════════ TAB 2: STOCK OPNAME ═══════════
    with tab2:
        st.subheader("🔍 Stock Opname")
        st.caption("Hitung fisik stok & bandingkan dengan sistem. Selisih otomatis tercatat.")

        opname_sku = st.selectbox("Pilih SKU", [r["kode_sku"] for r in db.fetch_all("SELECT kode_sku FROM sku ORDER BY kode_sku")], key="opname_sku")

        if opname_sku:
            sku_info = db.fetch_one("SELECT * FROM sku WHERE kode_sku = ?", (opname_sku,))
            if sku_info:
                stok_sistem = sku_info["stok"]
                st.info(f"📦 **{sku_info['nama_barang']}** | Stok Sistem: **{stok_sistem}** | Rak: {sku_info['posisi_rak'] or '-'}")

                col_o1, col_o2 = st.columns(2)
                with col_o1:
                    stok_fisik = st.number_input("Stok Fisik (hitung manual)", min_value=0, value=stok_sistem, key="opname_fisik")
                with col_o2:
                    selisih = stok_fisik - stok_sistem
                    if selisih != 0:
                        st.metric("Selisih", f"{selisih:+d}", delta=f"{'Surplus' if selisih > 0 else 'Defisit'}")
                    else:
                        st.success("✅ Stok cocok!")

                ket = st.text_input("Keterangan", placeholder="Contoh: Rusak, Hilang, Salah hitung...", key="opname_ket")

                if st.button("💾 Simpan Opname", type="primary", key="opname_save"):
                    db.execute(
                        "INSERT INTO stock_opname (kode_sku, stok_sistem, stok_fisik, selisih, keterangan, operator, tanggal) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (opname_sku, stok_sistem, stok_fisik, selisih, ket,
                         st.session_state.user["username"], datetime.now().strftime("%d-%m-%Y %H:%M")),
                    )
                    # Update stok
                    db.execute("UPDATE sku SET stok = ?, updated_at = CURRENT_TIMESTAMP WHERE kode_sku = ?",
                               (stok_fisik, opname_sku))
                    st.success(f"✅ Opname berhasil! Stok {opname_sku} diupdate: {stok_sistem} → {stok_fisik}")
                    st.rerun()

        # History opname
        st.divider()
        opname_history = db.fetch_all(
            "SELECT * FROM stock_opname ORDER BY created_at DESC LIMIT 50"
        )
        if opname_history:
            df_op = pd.DataFrame([dict(r) for r in opname_history])
            st.dataframe(df_op, width="stretch", hide_index=True)

    # ═══════════ TAB 3: SCAN OPNAME (HP) ═══════════
    with tab3:
        st.subheader("📸 Scan Opname via HP")
        st.caption("Scan barcode SKU langsung dari kamera HP atau scanner external. Tanpa foto - langsung decode.")

        scan_mode = st.radio("Mode Scan", ["📷 Kamera HP (decode otomatis)", "⌨️ Scan Text (scanner external)"], horizontal=True, key="opname_scan_mode")

        if scan_mode == "📷 Kamera HP (decode otomatis)":
            img_file = st.camera_input("Arahkan kamera ke barcode SKU", key="opname_camera", help="Pastikan barcode terlihat jelas")
            if img_file:
                try:
                    from pyzbar.pyzbar import decode as barcode_decode
                    from PIL import Image
                    image = Image.open(img_file)
                    decoded = barcode_decode(image)
                    if decoded:
                        scanned_sku = decoded[0].data.decode("utf-8").strip()
                        st.success(f"✅ Barcode terdeteksi: **{scanned_sku}**")
                        # Auto-fill & proceed
                        _render_opname_by_sku(db, scanned_sku)
                    else:
                        st.error("❌ Barcode tidak terdeteksi. Coba lagi dengan pencahayaan cukup.")
                except ImportError:
                    st.error("⚠️ Library pyzbar belum terinstall. Jalankan: pip install pyzbar pillow")
                except Exception as e:
                    st.error(f"Error: {e}")
        else:
            scan_text = st.text_input("Scan/ketik kode SKU", placeholder="Tempel hasil scan barcode...", key="opname_scan_text")
            if scan_text:
                _render_opname_by_sku(db, scan_text.strip())
                if st.button("🔄 Scan Lagi", key="opname_scan_again"):
                    st.session_state.opname_scan_text = ""
                    st.rerun()

    # ═══════════ TAB 4: RAK ═══════════
    with tab4:
        st.subheader("🗄️ Manajemen Rak & Posisi")

        # Add new rak
        col_r1, col_r2 = st.columns([2, 1])
        with col_r1:
            new_kode = st.text_input("Kode Rak", placeholder="A-01", key="rak_kode")
            new_nama = st.text_input("Nama Rak", placeholder="Rak A - Elektronik", key="rak_nama")
            new_lokasi = st.text_input("Lokasi", placeholder="Gudang Utama Lt.1", key="rak_lokasi")
        with col_r2:
            if st.button("➕ Tambah Rak", key="rak_add") and new_kode and new_nama:
                try:
                    db.execute("INSERT INTO rak_gudang (kode, nama, lokasi) VALUES (?, ?, ?)",
                               (new_kode.upper(), new_nama, new_lokasi))
                    st.success(f"✅ Rak {new_kode} ditambahkan!")
                    st.rerun()
                except:
                    st.error("Kode rak sudah ada!")

        # List rak
        rak_list = db.fetch_all("SELECT * FROM rak_gudang ORDER BY kode")
        if rak_list:
            for rak in rak_list:
                with st.expander(f"🗄️ {rak['kode']} - {rak['nama']} ({rak['lokasi']})"):
                    # Show SKU in this rak
                    sku_in_rak = db.fetch_all(
                        "SELECT kode_sku, nama_barang, stok, kategori FROM sku WHERE posisi_rak = ? ORDER BY nama_barang",
                        (rak["kode"],),
                    )
                    if sku_in_rak:
                        df_rak = pd.DataFrame([dict(r) for r in sku_in_rak])
                        st.dataframe(df_rak, width="stretch", hide_index=True)
                    else:
                        st.caption("Belum ada SKU di rak ini.")

                    # Assign SKU to this rak
                    sku_tanpa_rak = db.fetch_all(
                        "SELECT kode_sku, nama_barang FROM sku WHERE posisi_rak != ? OR posisi_rak = '' OR posisi_rak IS NULL ORDER BY nama_barang LIMIT 50",
                        (rak["kode"],),
                    )
                    if sku_tanpa_rak:
                        pindah_sku = st.selectbox(
                            f"Pindahkan SKU ke {rak['kode']}",
                            ["-- Pilih SKU --"] + [f"{s['kode_sku']} - {s['nama_barang']}" for s in sku_tanpa_rak],
                            key=f"pindah_{rak['id']}",
                        )
                        if pindah_sku != "-- Pilih SKU --" and st.button(f"✅ Pindahkan", key=f"btn_pindah_{rak['id']}"):
                            kode = pindah_sku.split(" - ")[0]
                            db.execute("UPDATE sku SET posisi_rak = ? WHERE kode_sku = ?", (rak["kode"], kode))
                            st.success(f"✅ {kode} dipindahkan ke {rak['kode']}!")
                            st.rerun()

        # Quick assign: all unassigned SKU
        st.divider()
        unassigned = db.fetch_all(
            "SELECT kode_sku, nama_barang, kategori FROM sku WHERE posisi_rak = '' OR posisi_rak IS NULL ORDER BY kategori, nama_barang"
        )
        if unassigned:
            st.warning(f"⚠️ {len(unassigned)} SKU belum punya rak!")
            df_un = pd.DataFrame([dict(r) for r in unassigned])
            st.dataframe(df_un, width="stretch", hide_index=True)


def _get_kategori_list(db):
    rows = db.fetch_all("SELECT DISTINCT kategori FROM sku WHERE kategori != '' ORDER BY kategori")
    return [r["kategori"] for r in rows]


def _get_rak_list(db):
    rows = db.fetch_all("SELECT kode FROM rak_gudang ORDER BY kode")
    return [r["kode"] for r in rows]


# ═══════════════════════════════════════════


def render_iklan_harian():
    """Input biaya iklan harian per marketplace - bisa di-update kapan saja."""
    st.caption("Input biaya iklan harian. Bisa upload sore (sebagian hari) & update lagi nanti. Sistem akan void jurnal lama & ganti baru.")
    db = st.session_state.db

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        mp_iklan = st.selectbox("Marketplace", ["Shopee", "TikTok", "Lazada", "Tokopedia"], key="iklan_mp")
    with col2:
        tgl_iklan = st.date_input("Tanggal Iklan", datetime.now(), key="iklan_tgl")
    with col3:
        st.write("")
        st.write("")

    biaya = st.number_input("Biaya Iklan (Rp)", min_value=0, step=10000, value=0, key="iklan_biaya",
                            help="Masukkan total biaya iklan hari ini. Bisa sebagian — update lagi nanti kalau ada tambahan.")

    if st.button("💾 Simpan Biaya Iklan", type="primary", key="iklan_save") and biaya > 0:
        tgl_str = tgl_iklan.strftime("%d-%m-%Y")
        ref = f"ADS-{mp_iklan}-{tgl_str}"

        # Void jurnal iklan lama untuk tanggal & marketplace yang sama
        db.execute(
            "DELETE FROM jurnal_umum WHERE sumber = 'iklan' AND no_ref = ?",
            (ref,),
        )

        # Post jurnal baru (replace)
        post_jurnal(db, tgl_str, ref, f"Biaya Iklan {mp_iklan}",
            [("5-1100", "Beban Fee Marketplace", biaya, 0),
             ("1-1000", "Kas & Bank", 0, biaya)], "iklan", 0)

        # Simpan/update di tabel ringkasan
        existing = db.fetch_one(
            "SELECT id FROM iklan_harian WHERE tanggal = ? AND marketplace = ?",
            (tgl_str, mp_iklan),
        )
        if existing:
            db.execute("UPDATE iklan_harian SET biaya = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                       (biaya, existing["id"]))
        else:
            db.execute("INSERT INTO iklan_harian (tanggal, marketplace, biaya) VALUES (?, ?, ?)",
                       (tgl_str, mp_iklan, biaya))

        st.success(f"✅ Biaya Iklan {mp_iklan} {tgl_str}: Rp {biaya:,.0f}")
        st.rerun()

    # History iklan
    st.divider()
    st.caption("Riwayat Biaya Iklan (30 hari terakhir)")
    iklan_rows = db.fetch_all(
        "SELECT tanggal, marketplace, biaya FROM iklan_harian ORDER BY tanggal DESC, marketplace LIMIT 60"
    )
    if iklan_rows:
        df_iklan = pd.DataFrame([dict(r) for r in iklan_rows])
        # Pivot: tanggal vs marketplace
        pivot = df_iklan.pivot_table(
            index="tanggal", columns="marketplace", values="biaya", aggfunc="sum", fill_value=0
        )
        pivot["Total"] = pivot.sum(axis=1)
        st.dataframe(pivot, width="stretch")


# ═══════════════════════════════════════════


def _post_amortisasi_to_jurnal(db, tgl_str, bln_ini):
    """Post amortisasi entries to jurnal umum."""
    rows = db.fetch_all(
        "SELECT * FROM amortisasi WHERE periode_bulan = ? AND id NOT IN (SELECT id_sumber FROM jurnal_umum WHERE sumber='amortisasi')",
        (bln_ini,),
    )
    for r in rows:
        if r["jenis"] == "PINJAMAN":
            # Debit: Beban Bunga, Kredit: Kas
            post_jurnal(db, tgl_str, f"AMORT-{r['id']}", f"Amortisasi Bunga {bln_ini}",
                [("5-1600", "Beban Bunga", r["jumlah"], 0),
                 ("1-1000", "Kas & Bank", 0, r["jumlah"])], "amortisasi", r["id"])
        elif r["jenis"] == "SEWA_DIMUKA":
            # Debit: Beban Sewa, Kredit: Biaya Dibayar di Muka
            post_jurnal(db, tgl_str, f"AMORT-{r['id']}", f"Amortisasi Sewa {bln_ini}",
                [("5-2100", "Beban Sewa", r["jumlah"], 0),
                 ("1-1300", "Biaya Dibayar di Muka", 0, r["jumlah"])], "amortisasi", r["id"])


def auto_amortisasi_bulanan(db):
    """Auto-proses amortisasi pinjaman & biaya dibayar di muka setiap bulan baru.
    Dijalankan sekali saat app startup. Gunakan tabel pengaturan untuk tracking."""
    today = datetime.now()
    bln_ini = today.strftime("%m-%Y")
    last_run = _get_setting(db, "last_amortisasi", "")

    # Already processed this month
    if last_run == bln_ini:
        return

    tgl_str = today.strftime("%d-%m-%Y")
    processed_loans = 0
    processed_prepaid = 0

    # ── Proses semua pinjaman AKTIF ──
    pinj_rows = db.fetch_all("SELECT * FROM pinjaman WHERE status = 'AKTIF' AND sisa_pokok > 0")
    for p in pinj_rows:
        existing = db.fetch_one(
            "SELECT id FROM amortisasi WHERE jenis = 'PINJAMAN' AND id_ref = ? AND periode_bulan = ?",
            (p["id"], bln_ini),
        )
        if existing:
            continue
        bunga_bln_pct = (p["bunga_persen"] or 0) / 100 / 12
        bunga_bln_ini = p["sisa_pokok"] * bunga_bln_pct
        cicilan_pokok_bln = min((p["cicilan_per_bulan"] or 0) - bunga_bln_ini, p["sisa_pokok"])
        if cicilan_pokok_bln <= 0:
            cicilan_pokok_bln = p["sisa_pokok"]
        total_bayar = cicilan_pokok_bln + bunga_bln_ini

        db.execute(
            "INSERT INTO amortisasi (jenis, id_ref, periode_bulan, jumlah, keterangan) VALUES (?, ?, ?, ?, ?)",
            ("PINJAMAN", p["id"], bln_ini, round(total_bayar, 2),
             f"Auto: Cicilan {p['nama_bank']} - Pokok Rp {cicilan_pokok_bln:,.0f} + Bunga Rp {bunga_bln_ini:,.0f}"),
        )
        new_sisa = max(0, p["sisa_pokok"] - cicilan_pokok_bln)
        new_status = "LUNAS" if new_sisa <= 0 else "AKTIF"
        db.execute(
            "UPDATE pinjaman SET sisa_pokok = ?, total_bunga_dibayar = total_bunga_dibayar + ?, status = ? WHERE id = ?",
            (round(new_sisa, 2), round(bunga_bln_ini, 2), new_status, p["id"]),
        )
        if bunga_bln_ini > 0:
            faktur = f"BUNGA-{today.strftime('%Y%m%d')}-{p['id']:03d}"
            if not db.fetch_one("SELECT id FROM opex WHERE no_faktur = ?", (faktur,)):
                db.execute(
                    "INSERT INTO opex (kategori, deskripsi, qty, satuan, harga_satuan, total_harga, tanggal, no_faktur, metode_bayar, status_bayar, tipe) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("Beban Bunga", f"Auto: Bunga {p['nama_bank']} ({bln_ini})",
                     1, "bulan", round(bunga_bln_ini, 2), round(bunga_bln_ini, 2),
                     tgl_str, faktur, "Transfer", "LUNAS", "TETAP"),
                )
        processed_loans += 1

    # ── Proses semua biaya dibayar di muka AKTIF ──
    bdm_rows = db.fetch_all("SELECT * FROM biaya_dibayar_dimuka WHERE status = 'AKTIF' AND sisa_belum_diakui > 0")
    for b in bdm_rows:
        existing = db.fetch_one(
            "SELECT id FROM amortisasi WHERE jenis = 'SEWA_DIMUKA' AND id_ref = ? AND periode_bulan = ?",
            (b["id"], bln_ini),
        )
        if existing:
            continue
        beban_bln = min(b["jumlah_per_bulan"], b["sisa_belum_diakui"])
        new_sisa = b["sisa_belum_diakui"] - beban_bln
        new_status = "AKTIF" if new_sisa > 0 else "SELESAI"

        db.execute(
            "INSERT INTO amortisasi (jenis, id_ref, periode_bulan, jumlah, keterangan) VALUES (?, ?, ?, ?, ?)",
            ("SEWA_DIMUKA", b["id"], bln_ini, round(beban_bln, 2),
             f"Auto: Amortisasi {b['deskripsi']} ({bln_ini})"),
        )
        db.execute(
            "UPDATE biaya_dibayar_dimuka SET sisa_belum_diakui = ?, status = ? WHERE id = ?",
            (round(new_sisa, 2), new_status, b["id"]),
        )
        faktur = f"AMORT-{today.strftime('%Y%m%d')}-{b['id']:03d}"
        if not db.fetch_one("SELECT id FROM opex WHERE no_faktur = ?", (faktur,)):
            db.execute(
                "INSERT INTO opex (kategori, deskripsi, qty, satuan, harga_satuan, total_harga, tanggal, no_faktur, metode_bayar, status_bayar, tipe) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"Amortisasi {b['kategori']}", f"Auto: Amortisasi {b['deskripsi']} ({bln_ini})",
                 1, "bulan", round(beban_bln, 2), round(beban_bln, 2),
                 tgl_str, faktur, "Transfer", "LUNAS", "TETAP"),
            )
        processed_prepaid += 1

    # ── Simpan tracking ──
    _save_setting(db, "last_amortisasi", bln_ini)

    if processed_loans > 0 or processed_prepaid > 0:
        logging.info(f"[AMORT] Processed {processed_loans} loans, {processed_prepaid} prepaid for {bln_ini}")
        # Post to jurnal for accrual accounting
        _post_amortisasi_to_jurnal(db, tgl_str, bln_ini)
        pass  # No toast needed on startup, just process


def render_aset_modal():
    """Halaman Manajemen Aset Tetap & Modal - neraca lengkap."""
    db = st.session_state.db

    st.title("🏗️ Aset & Modal")
    st.caption("Kelola aset tetap, modal, pinjaman bank, dan biaya dibayar di muka untuk laporan keuangan profesional.")

    tab1, tab2, tab3, tab4 = st.tabs(["🏭 Aset Tetap", "💰 Modal Usaha", "🏦 Pinjaman / Utang Bank", "📅 Biaya Dibayar di Muka"])

    # ═══════════════════ TAB 1: ASET TETAP ═══════════════════
    with tab1:
        st.subheader("🏭 Manajemen Aset Tetap")
        st.caption("Catat aset tetap (kendaraan, peralatan, bangunan) dan hitung depresiasi otomatis.")

        # ── Form Tambah Aset ──
        with st.expander("➕ Tambah Aset Baru", expanded=False):
            a_col1, a_col2 = st.columns(2)
            with a_col1:
                nama_aset = st.text_input("Nama Aset *", placeholder="Motor Operasional, Laptop, Printer...", key="aset_nama")
                kategori = st.selectbox("Kategori", ["Kendaraan", "Peralatan", "Elektronik", "Bangunan", "Lainnya"], key="aset_kat")
                tgl_perolehan = st.date_input("Tanggal Perolehan", value=datetime.now().date(), key="aset_tgl")
            with a_col2:
                harga = st.number_input("Harga Perolehan (Rp) *", min_value=0, value=0, step=100000, key="aset_harga")
                masa = st.number_input("Masa Manfaat (Tahun)", min_value=1, value=4, step=1, key="aset_masa")
                nilai_sisa = st.number_input("Nilai Sisa (Rp)", min_value=0, value=0, step=10000, key="aset_sisa",
                                             help="Nilai aset di akhir masa manfaat")

            if st.button("💾 Simpan Aset", type="primary", key="aset_simpan"):
                if not nama_aset.strip():
                    st.error("Nama aset wajib diisi!")
                elif harga <= 0:
                    st.error("Harga perolehan harus > 0!")
                else:
                    db.execute(
                        "INSERT INTO aset_tetap (nama_aset, kategori, tanggal_perolehan, harga_perolehan, masa_manfaat, nilai_sisa) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (nama_aset.strip(), kategori, tgl_perolehan.strftime("%d-%m-%Y"), harga, masa, nilai_sisa),
                    )
                    st.success(f"✅ Aset '{nama_aset.strip()}' ditambahkan!")
                    st.rerun()

        st.markdown("---")

        # ── Daftar Aset ──
        aset_rows = db.fetch_all("SELECT * FROM aset_tetap ORDER BY created_at DESC")
        if not aset_rows:
            st.info("📭 Belum ada aset tetap terdaftar.")
        else:
            st.subheader(f"📋 Daftar Aset Tetap ({len(aset_rows)} aset)")

            total_harga = sum(a["harga_perolehan"] or 0 for a in aset_rows)
            total_akum = sum(a["akumulasi_depresiasi"] or 0 for a in aset_rows)
            total_buku = total_harga - total_akum

            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                st.metric("💰 Total Harga Perolehan", f"Rp {total_harga:,.0f}")
            with sc2:
                st.metric("📉 Total Akum. Depresiasi", f"Rp {total_akum:,.0f}")
            with sc3:
                st.metric("📊 Total Nilai Buku", f"Rp {total_buku:,.0f}")

            for a in aset_rows:
                nilai_buku = (a["harga_perolehan"] or 0) - (a["akumulasi_depresiasi"] or 0)
                with st.container(border=True):
                    ac1, ac2, ac3, ac4 = st.columns([3, 1, 1, 1])
                    with ac1:
                        st.markdown(f"**🏭 {a['nama_aset']}**")
                        st.caption(f"📂 {a['kategori']} | 📅 Perolehan: {a['tanggal_perolehan']} | ⏳ {a['masa_manfaat']} thn | Nilai Sisa: Rp {a['nilai_sisa']:,.0f}")
                    with ac2:
                        st.metric("Harga", f"Rp {a['harga_perolehan']:,.0f}")
                    with ac3:
                        st.metric("Akum. Depr.", f"Rp {a['akumulasi_depresiasi']:,.0f}")
                    with ac4:
                        st.metric("Nilai Buku", f"Rp {nilai_buku:,.0f}")
                        if st.button("🗑️", key=f"aset_del_{a['id']}", help="Hapus aset"):
                            db.execute("DELETE FROM aset_tetap WHERE id = ?", (a["id"],))
                            st.success(f"🗑️ '{a['nama_aset']}' dihapus.")
                            st.rerun()

        # ── Hitung Depresiasi Otomatis ──
        st.markdown("---")
        st.subheader("💾 Hitung Depresiasi Otomatis")
        st.caption("Hitung beban depresiasi bulanan untuk semua aset (Garis Lurus). Update akumulasi depresiasi dan catat di jurnal OPEX.")

        if st.button("🔢 Hitung Depresiasi Bulan Ini", type="primary", key="aset_depr"):
            today_dt = datetime.now()
            bulan_ini = today_dt.strftime("%m-%Y")
            updated = 0
            total_beban = 0.0

            for a in aset_rows:
                if a["harga_perolehan"] <= 0 or a["masa_manfaat"] <= 0:
                    continue
                # Depresiasi per tahun = (harga - nilai_sisa) / masa_manfaat
                depr_tahunan = (a["harga_perolehan"] - (a["nilai_sisa"] or 0)) / a["masa_manfaat"]
                depr_bulanan = depr_tahunan / 12
                # Cek sudah berapa bulan sejak perolehan
                try:
                    tgl_perolehan = datetime.strptime(a["tanggal_perolehan"], "%d-%m-%Y")
                    bulan_berlalu = (today_dt.year - tgl_perolehan.year) * 12 + (today_dt.month - tgl_perolehan.month)
                except:
                    bulan_berlalu = 0
                bulan_berlalu = max(0, bulan_berlalu)
                # Akumulasi yang seharusnya = depr_bulanan * bulan_berlalu (capped di harga - nilai_sisa)
                max_depr = a["harga_perolehan"] - (a["nilai_sisa"] or 0)
                akum_seharusnya = min(depr_bulanan * bulan_berlalu, max_depr)
                # Beban bulan ini yang belum dicatat
                beban_bln_ini = max(0, akum_seharusnya - (a["akumulasi_depresiasi"] or 0))

                if beban_bln_ini > 0:
                    # Update akumulasi
                    db.execute(
                        "UPDATE aset_tetap SET akumulasi_depresiasi = ? WHERE id = ?",
                        (round(akum_seharusnya, 2), a["id"]),
                    )
                    # Catat sebagai beban depresiasi di OPEX (TETAP)
                    tgl_str = today_dt.strftime("%d-%m-%Y")
                    faktur = f"DEPR-{today_dt.strftime('%Y%m%d')}-{a['id']:03d}"
                    # Cek belum ada entry depresiasi bulan ini untuk aset ini
                    existing_depr = db.fetch_one(
                        "SELECT id FROM opex WHERE no_faktur = ? AND kategori = 'Depresiasi'",
                        (faktur,),
                    )
                    if not existing_depr:
                        db.execute(
                            "INSERT INTO opex (kategori, deskripsi, qty, satuan, harga_satuan, total_harga, tanggal, no_faktur, metode_bayar, status_bayar, tipe) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            ("Depresiasi", f"Depresiasi: {a['nama_aset']} ({bulan_ini})",
                             1, "bulan", round(beban_bln_ini, 2), round(beban_bln_ini, 2),
                             tgl_str, faktur, "Transfer", "LUNAS", "TETAP"),
                        )
                    total_beban += beban_bln_ini
                    updated += 1

            if updated > 0:
                st.success(f"✅ {updated} aset dihitung depresiasinya. Total beban depresiasi bulan ini: **Rp {total_beban:,.0f}** (tercatat di OPEX Tetap -> Laba Rugi).")
            else:
                st.info("✅ Semua aset sudah up-to-date. Tidak ada beban depresiasi baru bulan ini.")

    # ═══════════════════ TAB 2: MODAL ═══════════════════
    with tab2:
        st.subheader("💰 Modal Usaha")
        st.caption("Catat modal awal dan tambahan modal usaha.")

        # ── Form Tambah Modal ──
        with st.expander("➕ Catat Modal", expanded=False):
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                jenis_modal = st.selectbox("Jenis Modal", ["AWAL", "TAMBAHAN"], key="modal_jenis",
                                           help="AWAL = modal pertama saat memulai | TAMBAHAN = setoran tambahan")
                tgl_modal = st.date_input("Tanggal", value=datetime.now().date(), key="modal_tgl")
            with m_col2:
                jumlah_modal = st.number_input("Jumlah (Rp) *", min_value=0, value=0, step=1000000, key="modal_jml")
                ket_modal = st.text_area("Keterangan", placeholder="Sumber dana...", key="modal_ket", height=100)

            if st.button("💾 Simpan Modal", type="primary", key="modal_simpan"):
                if jumlah_modal <= 0:
                    st.error("Jumlah modal harus > 0!")
                else:
                    db.execute(
                        "INSERT INTO modal (jenis, tanggal, jumlah, keterangan) VALUES (?, ?, ?, ?)",
                        (jenis_modal, tgl_modal.strftime("%d-%m-%Y"), jumlah_modal, ket_modal.strip()),
                    )
                    st.success(f"✅ Modal {jenis_modal} sebesar Rp {jumlah_modal:,.0f} dicatat!")
                    st.rerun()

        st.markdown("---")

        # ── Ringkasan Modal ──
        modal_awal = db.fetch_one("SELECT COALESCE(SUM(jumlah), 0) as tot FROM modal WHERE jenis = 'AWAL'")
        modal_tambahan = db.fetch_one("SELECT COALESCE(SUM(jumlah), 0) as tot FROM modal WHERE jenis = 'TAMBAHAN'")
        total_modal = (modal_awal["tot"] if modal_awal else 0) + (modal_tambahan["tot"] if modal_tambahan else 0)

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            st.metric("🏁 Modal Awal", f"Rp {modal_awal['tot']:,.0f}" if modal_awal else "Rp 0")
        with mc2:
            st.metric("➕ Modal Tambahan", f"Rp {modal_tambahan['tot']:,.0f}" if modal_tambahan else "Rp 0")
        with mc3:
            st.metric("💰 Total Modal Disetor", f"Rp {total_modal:,.0f}")

        # ── Riwayat Modal ──
        st.markdown("---")
        st.subheader("📋 Riwayat Modal")
        modal_rows = db.fetch_all("SELECT * FROM modal ORDER BY created_at DESC")
        if modal_rows:
            df_modal = pd.DataFrame([dict(m) for m in modal_rows])
            df_modal["Jumlah"] = df_modal["jumlah"].apply(lambda x: f"Rp {x:,.0f}")
            df_modal["Jenis"] = df_modal["jenis"].apply(lambda x: "🏁 Awal" if x == "AWAL" else "➕ Tambahan")
            df_modal = df_modal.rename(columns={"tanggal": "Tanggal", "keterangan": "Keterangan"})
            st.dataframe(df_modal[["Tanggal", "Jenis", "Jumlah", "Keterangan"]], width="stretch", hide_index=True)

            # Delete
            with st.expander("🗑️ Hapus Data Modal", expanded=False):
                del_id = st.number_input("ID Modal", min_value=1, step=1, key="modal_del_id")
                if st.button("🗑️ Hapus", key="modal_del_btn"):
                    db.execute("DELETE FROM modal WHERE id = ?", (del_id,))
                    st.success(f"✅ Modal ID {del_id} dihapus.")
                    st.rerun()
        else:
            st.info("📭 Belum ada catatan modal.")

    # ═══════════════════ TAB 3: PINJAMAN / UTANG BANK ═══════════════════
    with tab3:
        st.subheader("🏦 Pinjaman / Utang Bank")
        st.caption("Catat pinjaman usaha, auto-hitung bunga & cicilan per bulan. Bunga masuk Laba Rugi, pokok di Neraca.")

        # ── Form Tambah Pinjaman ──
        with st.expander("➕ Catat Pinjaman Baru", expanded=False):
            p_col1, p_col2 = st.columns(2)
            with p_col1:
                bank = st.text_input("Nama Bank / Pemberi Pinjaman *", placeholder="BCA, BRI, KUR...", key="pinj_bank")
                pokok = st.number_input("Pokok Pinjaman (Rp) *", min_value=0, value=0, step=1000000, key="pinj_pokok")
                bunga_pct = st.number_input("Bunga per Tahun (%)", min_value=0.0, value=0.0, step=0.5, key="pinj_bunga",
                                            help="Misal 20% -> beban bunga = pokok × 20% / 12 per bulan")
            with p_col2:
                tenor = st.number_input("Tenor (Bulan)", min_value=1, value=12, step=1, key="pinj_tenor")
                tgl_mulai = st.date_input("Tanggal Mulai", value=datetime.now().date(), key="pinj_tgl")
                ket_pinj = st.text_area("Keterangan", placeholder="KUR Mikro, Modal Kerja...", key="pinj_ket", height=100)

            # Auto-hitung cicilan
            if pokok > 0 and tenor > 0:
                bunga_bulanan_pct = bunga_pct / 100 / 12
                if bunga_pct > 0:
                    # Cicilan flat = pokok/tenor + bunga per bulan
                    cicilan_pokok = pokok / tenor
                    cicilan_bunga = pokok * bunga_bulanan_pct
                    cicilan_total = cicilan_pokok + cicilan_bunga
                else:
                    cicilan_pokok = pokok / tenor
                    cicilan_total = cicilan_pokok
                st.info(f"📊 **Estimasi Cicilan**: Rp {cicilan_total:,.0f}/bulan (Pokok: Rp {cicilan_pokok:,.0f} + Bunga: Rp {cicilan_bunga if bunga_pct > 0 else 0:,.0f}) selama {tenor} bulan.")
                cicilan_est = cicilian_total
            else:
                cicilan_est = 0

            if st.button("💾 Simpan Pinjaman", type="primary", key="pinj_simpan"):
                if not bank.strip():
                    st.error("Nama bank wajib diisi!")
                elif pokok <= 0:
                    st.error("Pokok pinjaman harus > 0!")
                else:
                    bunga_bln_pct = bunga_pct / 100 / 12
                    cicilan_pokok_val = pokok / tenor if tenor > 0 else 0
                    cicilan_bunga_val = pokok * bunga_bln_pct
                    cicilan_val = cicilan_pokok_val + cicilan_bunga_val
                    db.execute(
                        "INSERT INTO pinjaman (nama_bank, pokok, bunga_persen, tenor_bulan, cicilan_per_bulan, tanggal_mulai, sisa_pokok, status, keterangan) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'AKTIF', ?)",
                        (bank.strip(), pokok, bunga_pct, tenor, round(cicilan_val, 2),
                         tgl_mulai.strftime("%d-%m-%Y"), pokok, ket_pinj.strip()),
                    )
                    st.success(f"✅ Pinjaman '{bank.strip()}' Rp {pokok:,.0f} dicatat!")
                    st.rerun()

        st.markdown("---")

        # ── Daftar Pinjaman ──
        pinj_rows = db.fetch_all("SELECT * FROM pinjaman ORDER BY created_at DESC")
        if not pinj_rows:
            st.info("📭 Belum ada pinjaman terdaftar.")
        else:
            total_pokok_awal = sum(p["pokok"] or 0 for p in pinj_rows)
            total_sisa = sum(p["sisa_pokok"] or 0 for p in pinj_rows)
            total_bunga = sum(p["total_bunga_dibayar"] or 0 for p in pinj_rows)

            sc1, sc2, sc3 = st.columns(3)
            with sc1: st.metric("🏦 Total Pokok Awal", f"Rp {total_pokok_awal:,.0f}")
            with sc2: st.metric("📉 Sisa Pokok (Utang)", f"Rp {total_sisa:,.0f}")
            with sc3: st.metric("💸 Total Bunga Dibayar", f"Rp {total_bunga:,.0f}")

            for p in pinj_rows:
                progress_val = (1 - (p["sisa_pokok"] / p["pokok"])) if p["pokok"] > 0 else 0
                with st.container(border=True):
                    pc1, pc2, pc3, pc4 = st.columns([3, 1, 1, 1])
                    with pc1:
                        status_icon = "🟢" if p["status"] == "AKTIF" else "🔴"
                        st.markdown(f"**{status_icon} {p['nama_bank']}**")
                        st.caption(f"Pokok: Rp {p['pokok']:,.0f} | Bunga: {p['bunga_persen']}%/thn | Tenor: {p['tenor_bulan']} bln | Mulai: {p['tanggal_mulai']}")
                        st.progress(min(progress_val, 1.0), text=f"Terbayar: {progress_val*100:.0f}%")
                    with pc2:
                        st.metric("Sisa Pokok", f"Rp {p['sisa_pokok']:,.0f}")
                    with pc3:
                        st.metric("Cicilan/Bln", f"Rp {p['cicilan_per_bulan']:,.0f}")
                    with pc4:
                        st.metric("Bunga Dibayar", f"Rp {p['total_bunga_dibayar']:,.0f}")
                        if st.button("🗑️", key=f"pinj_del_{p['id']}", help="Hapus pinjaman"):
                            db.execute("DELETE FROM pinjaman WHERE id = ?", (p["id"],))
                            db.execute("DELETE FROM amortisasi WHERE jenis = 'PINJAMAN' AND id_ref = ?", (p["id"],))
                            st.success(f"🗑️ Pinjaman dihapus.")
                            st.rerun()

        # ── Auto-Amortisasi Bunga + Cicilan ──
        st.markdown("---")
        st.subheader("🔢 Proses Amortisasi Bulanan (Bunga & Cicilan)")
        st.caption("Catat beban bunga bulan ini + kurangi sisa pokok secara otomatis. Beban bunga masuk OPEX Tetap -> Laba Rugi.")

        if st.button("🔢 Proses Amortisasi Bulan Ini", type="primary", key="pinj_amor"):
            today_dt = datetime.now()
            bln_ini_label = today_dt.strftime("%m-%Y")
            tgl_str = today_dt.strftime("%d-%m-%Y")
            processed = 0

            for p in pinj_rows:
                if p["status"] != "AKTIF" or p["sisa_pokok"] <= 0:
                    continue
                # Cek sudah diproses bulan ini
                existing = db.fetch_one(
                    "SELECT id FROM amortisasi WHERE jenis = 'PINJAMAN' AND id_ref = ? AND periode_bulan = ?",
                    (p["id"], bln_ini_label),
                )
                if existing:
                    continue
                # Hitung bunga bulan ini
                bunga_bln_pct = (p["bunga_persen"] or 0) / 100 / 12
                bunga_bln_ini = p["sisa_pokok"] * bunga_bln_pct
                cicilan_pokok_bln = min(p["cicilan_per_bulan"] - bunga_bln_ini, p["sisa_pokok"])
                if cicilan_pokok_bln <= 0:
                    cicilan_pokok_bln = p["sisa_pokok"]  # lunasi sisa
                total_bayar = cicilan_pokok_bln + bunga_bln_ini

                # Catat amortisasi
                db.execute(
                    "INSERT INTO amortisasi (jenis, id_ref, periode_bulan, jumlah, keterangan) VALUES (?, ?, ?, ?, ?)",
                    ("PINJAMAN", p["id"], bln_ini_label, round(total_bayar, 2),
                     f"Cicilan {p['nama_bank']}: Pokok Rp {cicilan_pokok_bln:,.0f} + Bunga Rp {bunga_bln_ini:,.0f}"),
                )
                # Update sisa pokok & bunga
                new_sisa = max(0, p["sisa_pokok"] - cicilan_pokok_bln)
                new_status = "LUNAS" if new_sisa <= 0 else "AKTIF"
                db.execute(
                    "UPDATE pinjaman SET sisa_pokok = ?, total_bunga_dibayar = total_bunga_dibayar + ?, status = ? WHERE id = ?",
                    (round(new_sisa, 2), round(bunga_bln_ini, 2), new_status, p["id"]),
                )
                # Catat beban bunga ke OPEX
                if bunga_bln_ini > 0:
                    faktur = f"BUNGA-{today_dt.strftime('%Y%m%d')}-{p['id']:03d}"
                    existing_opex = db.fetch_one("SELECT id FROM opex WHERE no_faktur = ?", (faktur,))
                    if not existing_opex:
                        db.execute(
                            "INSERT INTO opex (kategori, deskripsi, qty, satuan, harga_satuan, total_harga, tanggal, no_faktur, metode_bayar, status_bayar, tipe) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            ("Beban Bunga", f"Bunga pinjaman {p['nama_bank']} ({bln_ini_label})",
                             1, "bulan", round(bunga_bln_ini, 2), round(bunga_bln_ini, 2),
                             tgl_str, faktur, "Transfer", "LUNAS", "TETAP"),
                        )
                processed += 1

            if processed > 0:
                st.success(f"✅ {processed} pinjaman diproses amortisasinya. Beban bunga & cicilan pokok tercatat.")
            else:
                st.info("✅ Semua pinjaman sudah up-to-date bulan ini.")
            st.rerun()

    # ═══════════════════ TAB 4: BIAYA DIBAYAR DI MUKA ═══════════════════
    with tab4:
        st.subheader("📅 Biaya Dibayar di Muka (Prepaid Expenses)")
        st.caption("Catat biaya yang dibayar sekaligus di awal (sewa, asuransi) dan diakui sebagai beban per bulan.")

        # ── Form Tambah ──
        with st.expander("➕ Catat Biaya Dibayar di Muka", expanded=False):
            b_col1, b_col2 = st.columns(2)
            with b_col1:
                desc = st.text_input("Deskripsi *", placeholder="Sewa Gudang 1 Tahun, Asuransi Kendaraan...", key="bdm_desc")
                kat = st.selectbox("Kategori", ["Sewa", "Asuransi", "Lisensi/Software", "Pemeliharaan", "Lainnya"], key="bdm_kat")
                total = st.number_input("Jumlah Total (Rp) *", min_value=0, value=0, step=100000, key="bdm_total")
            with b_col2:
                bln_mulai = st.date_input("Bulan Mulai", value=datetime.now().date(), key="bdm_mulai")
                jml_bulan = st.number_input("Jumlah Bulan", min_value=1, value=12, step=1, key="bdm_bln",
                                            help="Berapa bulan biaya ini mencakup?")
                ket_bdm = st.text_area("Keterangan", key="bdm_ket", height=68)

            if total > 0 and jml_bulan > 0:
                per_bulan = total / jml_bulan
                bln_selesai = (bln_mulai + timedelta(days=jml_bulan * 30)).replace(day=1)
                st.info(f"📊 **Amortisasi**: Rp {per_bulan:,.0f}/bulan selama {jml_bulan} bulan. Akan diakui sebagai beban per bulan di Laba Rugi.")

            if st.button("💾 Simpan Biaya Dibayar di Muka", type="primary", key="bdm_simpan"):
                if not desc.strip():
                    st.error("Deskripsi wajib diisi!")
                elif total <= 0 or jml_bulan <= 0:
                    st.error("Jumlah total dan jumlah bulan harus > 0!")
                else:
                    per_bulan = total / jml_bulan
                    bln_selesai = (bln_mulai + timedelta(days=jml_bulan * 30)).replace(day=1)
                    db.execute(
                        "INSERT INTO biaya_dibayar_dimuka (deskripsi, kategori, jumlah_total, jumlah_per_bulan, bulan_mulai, bulan_selesai, sisa_belum_diakui, keterangan) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (desc.strip(), kat, total, round(per_bulan, 2),
                         bln_mulai.strftime("%m-%Y"), bln_selesai.strftime("%m-%Y"), total, ket_bdm.strip()),
                    )
                    st.success(f"✅ '{desc.strip()}' Rp {total:,.0f} dicatat (Rp {per_bulan:,.0f}/bulan).")
                    st.rerun()

        st.markdown("---")

        # ── Daftar ──
        bdm_rows = db.fetch_all("SELECT * FROM biaya_dibayar_dimuka ORDER BY created_at DESC")
        if not bdm_rows:
            st.info("📭 Belum ada biaya dibayar di muka.")
        else:
            total_bdm = sum(b["jumlah_total"] or 0 for b in bdm_rows)
            total_sisa_bdm = sum(b["sisa_belum_diakui"] or 0 for b in bdm_rows)

            sc1, sc2 = st.columns(2)
            with sc1: st.metric("💰 Total Dibayar di Muka", f"Rp {total_bdm:,.0f}")
            with sc2: st.metric("📅 Sisa Belum Diakui", f"Rp {total_sisa_bdm:,.0f}")

            for b in bdm_rows:
                progress_bdm = (1 - (b["sisa_belum_diakui"] / b["jumlah_total"])) if b["jumlah_total"] > 0 else 0
                with st.container(border=True):
                    bc1, bc2, bc3, bc4 = st.columns([3, 1, 1, 1])
                    with bc1:
                        status_icon = "🟢" if b["status"] == "AKTIF" else "🔴"
                        st.markdown(f"**{status_icon} {b['deskripsi']}**")
                        st.caption(f"📂 {b['kategori']} | {b['bulan_mulai']} -> {b['bulan_selesai']} | Rp {b['jumlah_per_bulan']:,.0f}/bulan")
                        st.progress(min(progress_bdm, 1.0), text=f"Terpakai: {progress_bdm*100:.0f}%")
                    with bc2:
                        st.metric("Total", f"Rp {b['jumlah_total']:,.0f}")
                    with bc3:
                        st.metric("Sisa", f"Rp {b['sisa_belum_diakui']:,.0f}")
                    with bc4:
                        if st.button("🗑️", key=f"bdm_del_{b['id']}", help="Hapus"):
                            db.execute("DELETE FROM biaya_dibayar_dimuka WHERE id = ?", (b['id'],))
                            db.execute("DELETE FROM amortisasi WHERE jenis = 'SEWA_DIMUKA' AND id_ref = ?", (b["id"],))
                            st.success(f"🗑️ Dihapus.")
                            st.rerun()

        # ── Auto-Amortisasi per Bulan ──
        st.markdown("---")
        st.subheader("🔢 Proses Amortisasi Bulanan (Akui Beban)")
        st.caption("Akui beban per bulan untuk semua biaya dibayar di muka yang masih aktif. Masuk OPEX Tetap -> Laba Rugi.")

        if st.button("🔢 Akui Beban Bulan Ini", type="primary", key="bdm_amor"):
            today_dt = datetime.now()
            bln_ini_label = today_dt.strftime("%m-%Y")
            tgl_str = today_dt.strftime("%d-%m-%Y")
            processed = 0

            for b in bdm_rows:
                if b["status"] != "AKTIF" or b["sisa_belum_diakui"] <= 0:
                    continue
                # Cek sudah diproses bulan ini
                existing = db.fetch_one(
                    "SELECT id FROM amortisasi WHERE jenis = 'SEWA_DIMUKA' AND id_ref = ? AND periode_bulan = ?",
                    (b["id"], bln_ini_label),
                )
                if existing:
                    continue
                # Akui beban bulan ini (sebesar jumlah_per_bulan, capped sisa)
                beban_bln = min(b["jumlah_per_bulan"], b["sisa_belum_diakui"])
                new_sisa = b["sisa_belum_diakui"] - beban_bln
                new_status = "AKTIF" if new_sisa > 0 else "SELESAI"

                db.execute(
                    "INSERT INTO amortisasi (jenis, id_ref, periode_bulan, jumlah, keterangan) VALUES (?, ?, ?, ?, ?)",
                    ("SEWA_DIMUKA", b["id"], bln_ini_label, round(beban_bln, 2),
                     f"Amortisasi {b['deskripsi']} - bln {bln_ini_label}"),
                )
                db.execute(
                    "UPDATE biaya_dibayar_dimuka SET sisa_belum_diakui = ?, status = ? WHERE id = ?",
                    (round(new_sisa, 2), new_status, b["id"]),
                )
                # Catat beban ke OPEX
                faktur = f"AMORT-{today_dt.strftime('%Y%m%d')}-{b['id']:03d}"
                existing_opex = db.fetch_one("SELECT id FROM opex WHERE no_faktur = ?", (faktur,))
                if not existing_opex:
                    db.execute(
                        "INSERT INTO opex (kategori, deskripsi, qty, satuan, harga_satuan, total_harga, tanggal, no_faktur, metode_bayar, status_bayar, tipe) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (f"Amortisasi {b['kategori']}", f"Amortisasi: {b['deskripsi']} ({bln_ini_label})",
                         1, "bulan", round(beban_bln, 2), round(beban_bln, 2),
                         tgl_str, faktur, "Transfer", "LUNAS", "TETAP"),
                    )
                processed += 1

            if processed > 0:
                st.success(f"✅ {processed} biaya diamortisasi. Beban bulanan tercatat di OPEX -> Laba Rugi.")
            else:
                st.info("✅ Semua biaya dibayar di muka sudah up-to-date bulan ini.")
            st.rerun()


# ==================== SIDEBAR NAVIGATION ====================
# Sub-menu definitions per main menu
OPERATIONAL_SUB_MENUS = {
    "📊 Dashboard": "Dashboard",
    "📷 SCAN Operasional": "Scan_Operasional",
    "📦 Gudang Inventory": "Gudang_Inventory",
    "📋 Input Resi & Pesanan": "Sales_Input",
    "🔄 Retur & Klaim": "Retur_Klaim",
    "🤖 AI Supervisor": "AI_Supervisor",
    "📋 Handover": "Handover",
    "🚚 Ekspedisi": "Ekspedisi",
    "📈 Reports": "Reports",
}

SALES_SUB_MENUS = {
    "📊 Dashboard Penjualan": "Sales_Dashboard",
    "📋 Riwayat Penjualan": "Sales_History",
    "📁 Arsip Penjualan": "Sales_Archive",
}

PURCHASE_SUB_MENUS = {
    "📊 Dashboard Pembelian": "Purchase_Dashboard",
    "🛒 Input Pembelian SKU": "Purchase_Input",
    "📋 Riwayat Pembelian SKU": "Purchase_History",
    "📁 Arsip Pembelian": "Purchase_Archive",
}

MASTER_DATA_SUB_MENUS = {
    "🏷️ Database Barang (SKU)": "Master_SKU",
    "🏪 Database Supplier": "Master_Supplier",
    "📂 Database Kategori": "Master_Kategori",
    "🏬 Database Toko": "Master_Toko",
    "📦 Daftar Barang Besar": "Master_Barang_Besar",
    "🏭 Gudang / Lokasi": "Master_Gudang",
}

OPEX_SUB_MENUS = {
    "📊 Dashboard OPEX": "Opex_Dashboard",
    "📝 Input Biaya OPEX": "Opex_Input",
    "📋 Riwayat OPEX": "Opex_History",
}

FINANCE_SUB_MENUS = {
    "📊 Dashboard Finance": "Finance_Dashboard",
    "💰 Laba Rugi Harian": "Laba_Rugi",
    "💵 Cashflow & Pencairan": "Cashflow",
    "✅ Konfirmasi Bayar SKU": "Finance_SKU",
    "✅ Konfirmasi Bayar OPEX": "Finance_OPEX",
    "📋 Riwayat Pembayaran": "Finance_History",
}

AKUNTANSI_SUB_MENUS = {
    "📋 Rekonsiliasi": "Rekonsiliasi",
    "📊 Laba Rugi & Neraca": "Laba_Rugi_Neraca",
    "🏗️ Aset & Modal": "Aset_Modal",
    "📥 Settlement Harian": "Settlement_Harian",
    "📢 Biaya Iklan": "Iklan_Harian",
}

ADMIN_SUB_MENUS = {
    "👥 Manajemen User": "Admin_Users",
}


def render_sidebar():
    """Render the sidebar navigation with main-menu -> sub-menu hierarchy + role-based filtering."""
    with st.sidebar:
        # ── Logo ──
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

        # ── User info ──
        user = st.session_state.get("user", {})
        if user:
            role_label = ROLES.get(user.get("role", ""), {}).get("label", user.get("role", "?"))
            st.markdown(f"""
            <div style="background:#1C1C1E;border-radius:10px;padding:10px 14px;margin-bottom:12px;">
                <div style="font-size:14px;font-weight:600;color:#FFFFFF;">👤 {user.get('nama_lengkap', 'User')}</div>
                <div style="font-size:12px;color:#AEAEB2;">🔑 Role: <strong style="color:#0A84FF;">{role_label}</strong></div>
            </div>
            """, unsafe_allow_html=True)

        # ── Main Menu (filtered by role) ──
        user_role = user.get("role", "operator") if user else "operator"
        allowed_menus = get_user_menus(user_role)

        MAIN_MENU_OPTIONS = ["📦 Operasional", "💰 Penjualan", "🛒 Pembelian SKU", "📋 Pembelian OPEX", "💳 Finance", "📊 Akuntansi", "📦 Master Data", "⚙️ Admin"]
        MAIN_MENU_MAP = {
            "📦 Operasional": "Operasional",
            "💰 Penjualan": "Penjualan",
            "🛒 Pembelian SKU": "Pembelian",
            "📋 Pembelian OPEX": "OPEX",
            "💳 Finance": "Finance",
            "📊 Akuntansi": "Akuntansi",
            "📦 Master Data": "Master_Data",
            "⚙️ Admin": "Admin",
        }

        # Filter menu options based on role
        visible_labels = [lbl for lbl in MAIN_MENU_OPTIONS if MAIN_MENU_MAP[lbl] in allowed_menus]
        visible_map = {lbl: MAIN_MENU_MAP[lbl] for lbl in visible_labels}

        if not visible_labels:
            visible_labels = ["📦 Operasional"]
            visible_map = {"📦 Operasional": "Operasional"}

        # ── Determine current main menu safely ──
        current_main = st.session_state.get("main_menu", "Operasional")
        if current_main not in visible_map.values():
            current_main = list(visible_map.values())[0]
            st.session_state.main_menu = current_main
            # Also reset page to default for the new main menu
            _default_pages = {
                "Operasional": "Dashboard",
                "Penjualan": "Sales_Dashboard",
                "Pembelian": "Purchase_Dashboard",
                "OPEX": "Opex_Dashboard",
                "Finance": "Finance_Dashboard",
                "Admin": "Admin_Users",
            }
            st.session_state.page = _default_pages.get(current_main, "Dashboard")

        # ── Main Menu Selectbox (sync only when invalid) ──
        selectbox_key = "sidebar_main_menu_select"
        current_selectbox_val = st.session_state.get(selectbox_key)

        if current_selectbox_val not in visible_labels:
            desired_main_label = None
            for label, key in visible_map.items():
                if key == current_main:
                    desired_main_label = label
                    break
            if desired_main_label is None:
                desired_main_label = visible_labels[0]
            st.session_state[selectbox_key] = desired_main_label

        selected_main_label = st.selectbox(
            "Pilih Menu Utama",
            visible_labels,
            key=selectbox_key,
            label_visibility="collapsed",
        )
        new_main_menu = visible_map[selected_main_label]

        # ── Detect main menu switch & reset page immediately ──
        if new_main_menu != current_main:
            st.session_state.main_menu = new_main_menu
            # Reset page to the default for the new main menu
            default_pages = {
                "Operasional": "Dashboard",
                "Penjualan": "Sales_Dashboard",
                "Pembelian": "Purchase_Dashboard",
                "OPEX": "Opex_Dashboard",
                "Finance": "Finance_Dashboard",
                "Akuntansi": "Rekonsiliasi",
                "Master_Data": "Master_SKU",
                "Admin": "Admin_Users",
            }
            st.session_state.page = default_pages.get(new_main_menu, "Dashboard")
            st.rerun()  # Rerun so sub-menu renders fresh with correct page

        # ── Sub Menu (depends on main menu) ──
        main_menu = current_main  # Use current_main (before selectbox change)

        if main_menu == "Operasional":
            sub_menus = dict(OPERATIONAL_SUB_MENUS)
            default_page = "Dashboard"
        elif main_menu == "Penjualan":
            sub_menus = dict(SALES_SUB_MENUS)
            default_page = "Sales_Dashboard"
        elif main_menu == "Pembelian":
            sub_menus = dict(PURCHASE_SUB_MENUS)
            default_page = "Purchase_Dashboard"
        elif main_menu == "OPEX":
            sub_menus = dict(OPEX_SUB_MENUS)
            default_page = "Opex_Dashboard"
        elif main_menu == "Finance":
            sub_menus = dict(FINANCE_SUB_MENUS)
            default_page = "Finance_Dashboard"
        elif main_menu == "Akuntansi":
            sub_menus = dict(AKUNTANSI_SUB_MENUS)
            default_page = "Rekonsiliasi"
        elif main_menu == "Master_Data":
            sub_menus = dict(MASTER_DATA_SUB_MENUS)
            default_page = "Master_SKU"
        else:  # Admin
            sub_menus = dict(ADMIN_SUB_MENUS)
            default_page = "Admin_Users"

        st.markdown("---")

        # ── Role-based sub-menu filtering (non-admin) ──
        if user_role != "admin":
            sub_menus = {
                lbl: page_key
                for lbl, page_key in sub_menus.items()
                if user_has_access(user_role, page_key)
            }
            if not sub_menus:
                st.caption("⚠️ Tidak ada menu yang tersedia untuk role ini.")
                st.markdown("---")
                _render_sidebar_footer()
                return

        # ── Ensure page is valid for current sub_menus ──
        current_page = st.session_state.get("page", default_page)
        if current_page not in sub_menus.values():
            current_page = default_page
            st.session_state.page = default_page

        # ── Sub Menu Radio (key-managed, sync only when invalid) ──
        radio_key = "sidebar_sub_menu_radio"
        valid_labels = list(sub_menus.keys())

        # Only sync radio if its current value is NOT in the current sub-menu
        # (e.g. after switching main menu). NEVER override a valid user selection.
        current_radio_val = st.session_state.get(radio_key)
        if current_radio_val not in valid_labels:
            # Find the label matching current page, or default to first
            desired_label = None
            for label, page_key in sub_menus.items():
                if page_key == st.session_state.get("page", default_page):
                    desired_label = label
                    break
            if desired_label is None:
                desired_label = valid_labels[0] if valid_labels else None

            if desired_label is not None:
                st.session_state[radio_key] = desired_label

        if valid_labels:
            selected_sub = st.radio(
                "Sub Menu",
                valid_labels,
                key=radio_key,
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

        _render_sidebar_footer()


def _render_sidebar_footer():
    """Render the sidebar footer: logout + version."""
    if st.button("🔒 Logout", width="stretch", key="sidebar_logout_btn"):
        # Invalidate all auth tokens for this user
        user = st.session_state.get("user")
        if user:
            invalidate_auth_token(st.session_state.db, user_id=user["id"])
        st.session_state.authenticated = False
        st.session_state.user = None
        st.session_state.main_menu = "Operasional"
        st.session_state.page = "Dashboard"
        # Clear all query params (auth, menu, page)
        st.query_params.clear()
        st.rerun()

    st.caption(f"v{APP_VERSION}")


# ==================== MAIN APP ====================
def main():
    """Main Streamlit application."""
    inject_pwa()  # PWA: load pwa-init.js (client-side fallback)
    init_session()

    # ── Auth guard: show login if not authenticated ──
    if not st.session_state.get("authenticated", False):
        logging.info(f"[AUTH] main(): NOT authenticated, showing login")
        render_login()
        # After render_login, auth may have just succeeded (no rerun needed)
        if not st.session_state.get("authenticated", False):
            return  # Still not authenticated - stop here

    logging.info(f"[AUTH] main(): authenticated as {st.session_state.user.get('username','?') if st.session_state.user else '?'}")

    # ── Auto-amortisasi bulanan: pinjaman + biaya dibayar di muka ──
    auto_amortisasi_bulanan(st.session_state.db)

    # ── Render sidebar FIRST (it updates st.session_state.page from widget clicks) ──
    render_sidebar()

    # ── Read page AFTER sidebar (gets the latest value from user click) ──
    user = st.session_state.user
    page = st.session_state.get("page", "Dashboard")

    # ── Role-based page access check ──
    if not user_has_access(user["role"], page):
        st.error(f"⛔ Akses ditolak! Role **{ROLES.get(user['role'], {}).get('label', user['role'])}** tidak memiliki akses ke halaman ini.")
        st.info("Silakan pilih menu yang tersedia di sidebar.")
        return

    # Page title
    if page == "Dashboard":
        st.title("📊 Dashboard Operasional")

        col_title, col_refresh = st.columns([5, 1])
        with col_title:
            st.caption(f"Selamat datang di iScan Pro - {datetime.now().strftime('%d %B %Y, %H:%M')}")
        with col_refresh:
            if st.button("🔄 Refresh", width="stretch", key="dashboard_refresh", help="Klik untuk memperbarui data"):
                st.rerun()

        db = st.session_state.db

        # Stats - selaras dengan Scan Operasional
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

        # Expedition summary chips - dari scan_aktif
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
        st.title("📷 SCAN Operasional - Packing & Verifikasi")
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
                f"📊 **{orders_cnt}** Total Pesanan -> "
                f"**{orders_dengan_resi}** punya Resi ({resi_cnt} unique) + "
                f"**{tanpa_cnt}** tanpa Resi | "
                f"**{belum_scan}** resi belum di-scan | "
                f"**{packed_cnt}** packed | **{cancel_cnt}** cancel"
            )

        # ── Daftar Belum Scan (resi ada, belum diproses) ──
        if belum_scan > 0:
            with st.expander(f"📋 {belum_scan} Resi Belum Di-Scan - Kemungkinan dibatalkan sistem? Klik untuk lihat & intervensi", expanded=False):
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
            with st.expander(f"⚠️ {tanpa_cnt} Pesanan Belum Memiliki No Resi - Klik untuk lihat", expanded=False):
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
            # Barang Besar toggle - hanya aktif saat PACK/INSTANT mode
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
                    # Check duplicate - cek by resi langsung DAN by no_pesanan -> resi
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
                            f"`{cleaned}` -> Resi `{linked_resi}` sudah di-scan:\n"
                            f"• Status: {status_emoji} **{existing_scan['status']}**\n"
                            f"• Waktu: {existing_scan['waktu']} | Tanggal: {existing_scan['tanggal']}\n"
                            f"• Toko: {existing_scan['toko']}\n\n"
                            f"Gunakan mode ❌ CANCEL jika ingin membatalkan."
                        )
                        st.session_state.scan_ops_resi = ""  # auto-clear even on error
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
                                st.error(f"❌ **CANCEL!** `{cleaned}`{extra} - nilai penjualan dikurangi.")
                                st.session_state.scan_ops_resi = ""

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
                                    f"{'No Pesanan' if is_order_scan else 'Resi'} `{cleaned}` -> Resi `{real_resi}` sudah di-scan:\n"
                                    f"• Status: {status_emoji} **{existing['status']}**\n"
                                    f"• Waktu: {existing['waktu']} | Tanggal: {existing['tanggal']}\n"
                                    f"• Toko: {existing['toko']}"
                                )
                            else:
                                scan_toko = match["nama_toko"] or selected_toko
                                db.execute(
                                    "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, status, kategori, keterangan_barang, tipe_kiriman, marketplace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    (waktu, tanggal, real_resi, match["kurir"] or "Unknown", scan_toko, "PACKED", kategori, keterangan_barang, tipe_kiriman, match["marketplace"] if "marketplace" in match.keys() else ""),
                                )
                                # Update penjualan
                                db.execute(
                                    "UPDATE penjualan SET status_pesanan = 'PACKED' WHERE no_resi = ? OR no_pesanan = ?",
                                    (real_resi, match["no_pesanan"]),
                                )
                                # Auto-posting akuntansi akrual
                                post_packed_to_accounting(db, real_resi, tanggal)
                                # Verifikasi update berhasil
                                verify = db.fetch_one(
                                    "SELECT COUNT(*) as cnt FROM penjualan WHERE (no_resi = ? OR no_pesanan = ?) AND status_pesanan = 'PACKED'",
                                    (real_resi, match["no_pesanan"]),
                                )
                                if not verify or verify["cnt"] == 0:
                                    st.warning(f"⚠️ Gagal update status penjualan untuk resi `{real_resi}`. Coba refresh.")

                                scan_type = "No Pesanan -> Resi" if is_order_scan else "Resi"
                                tipe_label = "🚀 INSTANT" if tipe_kiriman == "INSTANT" else "PACKED"
                                st.success(f"✅ **{tipe_label}!** ({scan_type}) `{real_resi}`")
                                st.info(
                                    f"📦 {match['marketplace']} | {match['no_pesanan']}\n"
                                    f"🛍️ {match['nama_produk'][:50]}\n"
                                    f"🏪 {match['nama_toko'] or '-'} | 🚚 {match['kurir'] or '-'} | SKU: {match['sku_terdeteksi'] or '?'}"
                                )
                                # Auto-clear scan input for barcode scanner continuous scanning
                                st.session_state.scan_ops_resi = ""

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
                            st.success(f"'{cleaned_del}' dihapus - status penjualan dikembalikan.")
                            st.rerun()
            with col_a2:
                if st.button("↩️ Undo Terakhir", width="stretch", key="scan_ops_undo"):
                    row = db.fetch_one("SELECT id, resi FROM scan_aktif ORDER BY id DESC LIMIT 1")
                    if row:
                        # Revert penjualan status sebelum hapus scan
                        db.execute("UPDATE penjualan SET status_pesanan = '' WHERE no_resi = ?", (row["resi"],))
                        db.execute("DELETE FROM scan_aktif WHERE id = ?", (row["id"],))
                        st.success("Scan terakhir di-undo - status penjualan dikembalikan.")
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

    elif page == "Gudang_Inventory":
        render_gudang_inventory()

    elif page == "Scan History":
        st.title("📋 Scan History")
        render_scan_history()

    elif page == "Handover":
        st.title("📋 Handover - Serah Terima per Kurir")
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
            st.caption("Kiriman Instant/Prioritas - sudah di-scan, siap diambil kurir. Konfirmasi setelah kurir mengambil paket.")
            _render_handover_tab(db, "INSTANT")

    elif page == "Ekspedisi":
        st.title("🚚 Manajemen Ekspedisi")
        render_ekspedisi()

    elif page == "Toko":
        # Redirect to Master Data
        st.session_state.page = "Master_Toko"
        st.rerun()

    elif page == "Barang_Besar":
        # Redirect to Master Data
        st.session_state.page = "Master_Barang_Besar"
        st.rerun()

    elif page == "Purchase_SKU":
        # Redirect to Master Data
        st.session_state.page = "Master_SKU"
        st.rerun()

    elif page == "Reports":
        st.title("📊 Reports")
        render_reports()

    # ── Master Data Pages (all route to same tabbed page) ──
    elif page in ("Master_SKU", "Master_Supplier", "Master_Kategori", "Master_Toko", "Master_Barang_Besar", "Master_Gudang"):
        render_master_data()

    elif page == "Sales_Input":
        st.title("📦 Input Resi & Pesanan (Marketplace)")
        render_sales_input()

    elif page == "Retur_Klaim":
        st.title("🔄 Retur & Klaim - Proses Paket Kembalian")
        render_retur_klaim()

    elif page == "Sales_Daily_Report":
        st.title("📊 Laporan Penjualan Harian")
        render_sales_daily_report()

    elif page == "AI_Supervisor":
        st.title("🤖 AI Supervisor - Pantauan & Rekomendasi")
        render_ai_supervisor()

    # ── Penjualan Pages ──
    elif page == "Sales_Dashboard":
        st.title("💰 Dashboard Penjualan")

        col_title, col_refresh = st.columns([5, 1])
        with col_title:
            st.caption(f"Ringkasan penjualan marketplace - {datetime.now().strftime('%d %B %Y, %H:%M')}")
        with col_refresh:
            if st.button("🔄 Refresh", width="stretch", key="sales_dash_refresh", help="Klik untuk memperbarui data"):
                st.rerun()

        db = st.session_state.db

        # ── Stats: selaras dengan Scan Operasional ──
        # Unique resi (paket fisik yang harus di-scan) - sama dengan Scan Operasional
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

        # Real Packed: dari scan_aktif (ground truth - unik per resi)
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
            # Format total_harga with proper Indonesian number handling
            def fmt_rupiah(x):
                """Format rupiah: if value is small decimal (likely mis-parsed), show full precision."""
                if x is None or x == 0:
                    return "Rp 0"
                if x < 1000 and x != int(x):
                    # Small decimal - possibly mis-parsed Indonesian thousands (91.25 = 91,250)
                    return f"Rp {x:,.2f}"
                return f"Rp {x:,.0f}"
            df_rec["total_harga"] = df_rec["total_harga"].apply(fmt_rupiah)
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
        st.caption(f"Ringkasan inventaris & pembelian - {datetime.now().strftime('%d %B %Y, %H:%M')}")

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
            st.info("🏷️ **Manajemen SKU** - Tambah, edit, hapus data SKU barang dan update stok secara manual.")
        with col_b:
            st.info("🛒 **Input Pembelian** - Catat pembelian dari supplier, auto-update stok SKU.")
        with col_c:
            st.info("📋 **Riwayat Pembelian** - Lihat & filter history transaksi pembelian.")

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

    elif page == "Purchase_Input":
        st.title("🛒 Input Pembelian ke Supplier")
        render_purchase_input()

    elif page == "Purchase_History":
        st.title("📋 Riwayat Pembelian")
        render_purchase_history()

    elif page == "Purchase_Finance":
        st.title("💳 Finance - Konfirmasi Pembayaran")
        render_purchase_finance()

    elif page == "Purchase_Archive":
        st.title("📁 Arsip Pembelian")
        render_purchase_archive()

    # ── OPEX Pages ──
    elif page == "Opex_Dashboard":
        st.title("📊 Dashboard Biaya Operasional (OPEX)")
        render_opex_dashboard()

    elif page == "Opex_Input":
        st.title("📝 Input Biaya Operasional (OPEX)")
        render_opex_input()

    elif page == "Opex_History":
        st.title("📋 Riwayat Biaya Operasional (OPEX)")
        render_opex_history()

    # ── Finance Pages ──
    elif page == "Finance_Dashboard":
        st.title("💳 Dashboard Finance")
        render_finance_dashboard()

    elif page == "Laba_Rugi":
        st.title("💰 Laba Rugi Harian")
        render_laba_rugi()

    elif page == "Cashflow":
        st.title("💵 Cashflow & Pencairan Marketplace")
        render_cashflow()

    elif page == "Finance_SKU":
        st.title("✅ Konfirmasi Pembayaran - Pembelian SKU")
        render_purchase_finance()  # Reuse existing function

    elif page == "Finance_OPEX":
        st.title("✅ Konfirmasi Pembayaran - Biaya OPEX")
        render_finance_opex()

    elif page == "Finance_History":
        st.title("📋 Riwayat Pembayaran")
        render_finance_history()

    # ── Akuntansi Pages ──
    elif page == "Rekonsiliasi":
        render_rekonsiliasi()

    elif page == "Laba_Rugi_Neraca":
        render_laba_rugi_neraca()

    elif page == "Aset_Modal":
        render_aset_modal()

    elif page == "Settlement_Harian":
        render_settlement_daily_import()

    elif page == "Iklan_Harian":
        render_iklan_harian()

    # ── Admin ──
    elif page == "Admin_Users":
        st.title("⚙️ Admin - Manajemen User & Role")
        render_admin_users()


if __name__ == "__main__":
    main()

