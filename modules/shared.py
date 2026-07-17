"""
iScan Pro - Shared Module
Database, Auth, Helpers, Accounting - NOT page rendering.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3, os, time, re, hashlib, secrets, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from config import Config, Theme
from constants import APP_NAME, APP_VERSION, ScanStatus, DEFAULT_EXPEDITIONS
from validators import Validator, validate_resi_or_raise
from exceptions import DatabaseError, ValidationError

# ═══════════ DATABASE ═══════════
class Database:
    """Thread-safe SQLite database wrapper."""
    def __init__(self):
        self.db_path = Config.DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn
    def execute(self, query, params=None):
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute(query, params or ())
            conn.commit()
            return c
        except sqlite3.Error as e:
            conn.rollback()
            raise DatabaseError(f"Database error: {e}")
        finally:
            conn.close()
    def fetch_all(self, query, params=None):
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute(query, params or ())
            return c.fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Database error: {e}")
        finally:
            conn.close()
    def fetch_one(self, query, params=None):
        conn = self._get_conn()
        try:
            c = conn.cursor()
            c.execute(query, params or ())
            return c.fetchone()
        except sqlite3.Error as e:
            raise DatabaseError(f"Database error: {e}")
        finally:
            conn.close()
    def _init_db(self):
        conn = self._get_conn()
        try:
            c = conn.cursor()
            # Essential tables
            c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, nama_lengkap TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'operator', active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_login TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS auth_tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, token TEXT UNIQUE NOT NULL, expires_at TIMESTAMP NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)")
            c.execute("CREATE TABLE IF NOT EXISTS toko (id INTEGER PRIMARY KEY AUTOINCREMENT, nama TEXT UNIQUE)")
            c.execute("CREATE TABLE IF NOT EXISTS ekspedisi (id INTEGER PRIMARY KEY AUTOINCREMENT, nama TEXT UNIQUE, prefix TEXT, keterangan TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS sku (id INTEGER PRIMARY KEY AUTOINCREMENT, kode_sku TEXT UNIQUE NOT NULL, nama_barang TEXT NOT NULL, kategori TEXT DEFAULT '', stok INTEGER DEFAULT 0, satuan TEXT DEFAULT 'pcs', harga_beli REAL DEFAULT 0, harga_jual REAL DEFAULT 0, supplier TEXT DEFAULT '', keterangan TEXT DEFAULT '', posisi_rak TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS scan_aktif (id INTEGER PRIMARY KEY AUTOINCREMENT, waktu TEXT, tanggal TEXT, resi TEXT UNIQUE, ekspedisi TEXT, toko TEXT, status TEXT DEFAULT 'KIRIM', kategori TEXT DEFAULT 'REGULER', keterangan_barang TEXT DEFAULT '', tipe_kiriman TEXT DEFAULT 'REGULER', marketplace TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS penjualan (id INTEGER PRIMARY KEY AUTOINCREMENT, marketplace TEXT NOT NULL, no_pesanan TEXT NOT NULL, no_resi TEXT DEFAULT '', tanggal_pesanan TEXT DEFAULT '', sku_terdeteksi TEXT DEFAULT '', nama_produk TEXT DEFAULT '', qty INTEGER DEFAULT 1, harga_jual REAL DEFAULT 0, total_harga REAL DEFAULT 0, nama_pembeli TEXT DEFAULT '', nama_toko TEXT DEFAULT '', kurir TEXT DEFAULT '', status_pesanan TEXT DEFAULT '', potongan_marketplace REAL DEFAULT 0, status_settlement TEXT DEFAULT 'UNSETTLED', ppn REAL DEFAULT 0, keterangan TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS pembelian (id INTEGER PRIMARY KEY AUTOINCREMENT, no_faktur TEXT NOT NULL, tanggal TEXT NOT NULL, supplier TEXT NOT NULL, kode_sku TEXT NOT NULL, nama_barang TEXT NOT NULL, qty INTEGER DEFAULT 0, satuan TEXT DEFAULT 'pcs', harga_beli REAL DEFAULT 0, total_harga REAL DEFAULT 0, metode_bayar TEXT DEFAULT 'Transfer', status_bayar TEXT DEFAULT 'PENDING', biaya_operasional REAL DEFAULT 0, biaya_packing REAL DEFAULT 0, ppn REAL DEFAULT 0, tanggal_akrual TEXT DEFAULT '', keterangan TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS opex (id INTEGER PRIMARY KEY AUTOINCREMENT, kategori TEXT NOT NULL, deskripsi TEXT NOT NULL, supplier TEXT DEFAULT '', qty INTEGER DEFAULT 1, satuan TEXT DEFAULT 'pcs', harga_satuan REAL DEFAULT 0, total_harga REAL DEFAULT 0, tanggal TEXT NOT NULL, no_faktur TEXT DEFAULT '', metode_bayar TEXT DEFAULT 'Transfer', status_bayar TEXT DEFAULT 'PENDING', tipe TEXT DEFAULT 'VARIABLE', tanggal_akrual TEXT DEFAULT '', keterangan TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS aset_tetap (id INTEGER PRIMARY KEY AUTOINCREMENT, nama_aset TEXT NOT NULL, kategori TEXT DEFAULT '', tanggal_perolehan TEXT NOT NULL, harga_perolehan REAL DEFAULT 0, masa_manfaat INTEGER DEFAULT 4, metode_depresiasi TEXT DEFAULT 'GARIS_LURUS', nilai_sisa REAL DEFAULT 0, akumulasi_depresiasi REAL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS modal (id INTEGER PRIMARY KEY AUTOINCREMENT, jenis TEXT DEFAULT 'AWAL', tanggal TEXT NOT NULL, jumlah REAL DEFAULT 0, keterangan TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS pinjaman (id INTEGER PRIMARY KEY AUTOINCREMENT, nama_bank TEXT NOT NULL, pokok REAL DEFAULT 0, bunga_persen REAL DEFAULT 0, tenor_bulan INTEGER DEFAULT 12, cicilan_per_bulan REAL DEFAULT 0, tanggal_mulai TEXT NOT NULL, sisa_pokok REAL DEFAULT 0, total_bunga_dibayar REAL DEFAULT 0, status TEXT DEFAULT 'AKTIF', keterangan TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS biaya_dibayar_dimuka (id INTEGER PRIMARY KEY AUTOINCREMENT, deskripsi TEXT NOT NULL, kategori TEXT DEFAULT '', jumlah_total REAL DEFAULT 0, jumlah_per_bulan REAL DEFAULT 0, sisa_belum_diakui REAL DEFAULT 0, bulan_mulai TEXT, bulan_selesai TEXT, status TEXT DEFAULT 'AKTIF', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS amortisasi (id INTEGER PRIMARY KEY AUTOINCREMENT, jenis TEXT NOT NULL, id_ref INTEGER NOT NULL, periode_bulan TEXT NOT NULL, jumlah REAL DEFAULT 0, keterangan TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS coa (id INTEGER PRIMARY KEY AUTOINCREMENT, kode TEXT UNIQUE NOT NULL, nama TEXT NOT NULL, tipe TEXT DEFAULT 'BEBAN', kelompok TEXT DEFAULT '', saldo_normal TEXT DEFAULT 'DEBIT', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS jurnal_umum (id INTEGER PRIMARY KEY AUTOINCREMENT, tanggal TEXT NOT NULL, no_ref TEXT NOT NULL, kode_akun TEXT NOT NULL, nama_akun TEXT NOT NULL, deskripsi TEXT DEFAULT '', debit REAL DEFAULT 0, kredit REAL DEFAULT 0, sumber TEXT DEFAULT '', id_sumber INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS pengaturan (id INTEGER PRIMARY KEY AUTOINCREMENT, kunci TEXT UNIQUE, nilai TEXT DEFAULT '')")
            c.execute("CREATE TABLE IF NOT EXISTS settlement_harian (id INTEGER PRIMARY KEY AUTOINCREMENT, tanggal TEXT NOT NULL, marketplace TEXT NOT NULL, total_penjualan REAL DEFAULT 0, total_fee REAL DEFAULT 0, total_pencairan REAL DEFAULT 0, total_biaya_lain REAL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS iklan_harian (id INTEGER PRIMARY KEY AUTOINCREMENT, tanggal TEXT NOT NULL, marketplace TEXT NOT NULL, biaya REAL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS rak_gudang (id INTEGER PRIMARY KEY AUTOINCREMENT, kode TEXT UNIQUE NOT NULL, nama TEXT NOT NULL, lokasi TEXT DEFAULT '', keterangan TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS stock_opname (id INTEGER PRIMARY KEY AUTOINCREMENT, kode_sku TEXT NOT NULL, stok_sistem INTEGER NOT NULL, stok_fisik INTEGER NOT NULL, selisih INTEGER NOT NULL, keterangan TEXT DEFAULT '', operator TEXT DEFAULT '', tanggal TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS pencairan (id INTEGER PRIMARY KEY AUTOINCREMENT, marketplace TEXT NOT NULL, jumlah REAL NOT NULL, tanggal TEXT NOT NULL, keterangan TEXT DEFAULT '', operator TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS retur_klaim (id INTEGER PRIMARY KEY AUTOINCREMENT, no_resi TEXT DEFAULT '', no_pesanan TEXT DEFAULT '', marketplace TEXT DEFAULT '', nama_toko TEXT DEFAULT '', sku TEXT DEFAULT '', nama_produk TEXT DEFAULT '', qty INTEGER DEFAULT 1, nominal_klaim REAL DEFAULT 0, status_klaim TEXT DEFAULT 'PROSES', keterangan TEXT DEFAULT '', tanggal TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS list_arsip (id INTEGER PRIMARY KEY AUTOINCREMENT, judul TEXT, nama_file TEXT, tanggal TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, user TEXT, action TEXT, details TEXT, resi TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS supplier (id INTEGER PRIMARY KEY AUTOINCREMENT, nama TEXT NOT NULL UNIQUE, kontak TEXT DEFAULT '', alamat TEXT DEFAULT '', keterangan TEXT DEFAULT '')")
            c.execute("CREATE TABLE IF NOT EXISTS kategori_produk (id INTEGER PRIMARY KEY AUTOINCREMENT, nama TEXT NOT NULL UNIQUE, keterangan TEXT DEFAULT '')")
            c.execute("CREATE TABLE IF NOT EXISTS gudang (id INTEGER PRIMARY KEY AUTOINCREMENT, nama TEXT NOT NULL UNIQUE, lokasi TEXT DEFAULT '', keterangan TEXT DEFAULT '')")
            c.execute("CREATE TABLE IF NOT EXISTS daftar_barang_besar (id INTEGER PRIMARY KEY AUTOINCREMENT, nama_barang TEXT NOT NULL, keterangan TEXT DEFAULT '')")
            
            # Default admin
            c.execute("SELECT COUNT(*) FROM users")
            if c.fetchone()[0] == 0:
                c.execute("INSERT INTO users (username, password_hash, nama_lengkap, role) VALUES (?,?,?,?)", ("admin", hash_password("admin123"), "Administrator", "admin"))
            
            # Default settings
            c.execute("SELECT COUNT(*) FROM pengaturan")
            if c.fetchone()[0] == 0:
                for k, v in [("fee_shopee","5.0"),("fee_tiktok","4.0"),("fee_lazada","4.5"),("fee_tokopedia","4.0"),("biaya_per_resi","1250"),("pph_persen","0.5"),("ppn_persen","11.0")]:
                    c.execute("INSERT OR IGNORE INTO pengaturan (kunci, nilai) VALUES (?,?)", (k, v))
            
            # Default COA
            c.execute("SELECT COUNT(*) FROM coa")
            if c.fetchone()[0] == 0:
                default_coa = [
                    ("1-1000","Kas & Bank","ASET","DEBIT"),("1-1100","Piutang Usaha","ASET","DEBIT"),("1-1200","Persediaan Barang","ASET","DEBIT"),
                    ("1-2000","Aset Tetap","ASET","DEBIT"),("1-2100","Akumulasi Depresiasi","ASET","KREDIT"),
                    ("2-1000","Hutang Usaha","LIABILITAS","KREDIT"),("2-1100","Hutang Bank","LIABILITAS","KREDIT"),
                    ("3-1000","Modal Disetor","EKUITAS","KREDIT"),("3-2000","Laba Ditahan","EKUITAS","KREDIT"),
                    ("4-1000","Pendapatan Penjualan","PENDAPATAN","KREDIT"),
                    ("5-1000","HPP","BEBAN","DEBIT"),("5-1100","Beban Fee Marketplace","BEBAN","DEBIT"),("5-1200","Beban Packing","BEBAN","DEBIT"),
                    ("5-1300","Beban Operasional","BEBAN","DEBIT"),("5-1400","Beban Gaji","BEBAN","DEBIT"),("5-1500","Beban Depresiasi","BEBAN","DEBIT"),
                    ("5-1600","Beban Bunga","BEBAN","DEBIT"),("5-1700","Beban Pajak","BEBAN","DEBIT"),("5-2300","Beban Iklan","BEBAN","DEBIT"),
                ]
                for row in default_coa:
                    c.execute("INSERT INTO coa (kode, nama, tipe, saldo_normal) VALUES (?,?,?,?)", row)
            conn.commit()
        finally:
            conn.close()

# ═══════════ AUTH ═══════════
def hash_password(password):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${dk.hex()}"

def verify_password(password, stored_hash):
    try:
        salt, orig = stored_hash.split("$", 1)
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex() == orig
    except:
        return False

def authenticate_user(db, username, password):
    user = db.fetch_one("SELECT id, username, nama_lengkap, role, password_hash, active FROM users WHERE username = ?", (username.strip().lower(),))
    if not user or not user["active"] or not verify_password(password, user["password_hash"]):
        return None
    db.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))
    return {"id": user["id"], "username": user["username"], "nama_lengkap": user["nama_lengkap"], "role": user["role"]}

def generate_auth_token(db, user_id):
    token = secrets.token_hex(32)
    db.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
    db.execute("INSERT INTO auth_tokens (user_id, token, expires_at) VALUES (?,?,?)",
               (user_id, token, (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")))
    return token

def validate_auth_token(db, token):
    row = db.fetch_one("SELECT u.id, u.username, u.nama_lengkap, u.role, u.active FROM auth_tokens t JOIN users u ON t.user_id = u.id WHERE t.token = ? AND t.expires_at > datetime('now','localtime')", (token,))
    if not row or not row["active"]: return None
    return {"id": row["id"], "username": row["username"], "nama_lengkap": row["nama_lengkap"], "role": row["role"]}

def invalidate_auth_token(db, token=None, user_id=None):
    if token: db.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
    if user_id: db.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM auth_tokens WHERE expires_at <= datetime('now','localtime')")

# ═══════════ SETTINGS ═══════════
def _get_setting(db, key, default=""):
    row = db.fetch_one("SELECT nilai FROM pengaturan WHERE kunci = ?", (key,))
    return row["nilai"] if row else default

def _save_setting(db, key, value):
    db.execute("INSERT OR REPLACE INTO pengaturan (kunci, nilai) VALUES (?,?)", (key, str(value)))

# ═══════════ PWA ═══════════
def inject_pwa():
    if st.session_state.get("_pwa_injected"): return
    st.session_state._pwa_injected = True
    st.html('<link rel="manifest" href="/app/static/manifest.json" crossorigin="use-credentials">')

# ═══════════ SESSION INIT ═══════════
def init_session():
    if "db" not in st.session_state:
        st.session_state.db = Database()
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "user" not in st.session_state:
        st.session_state.user = None
    # Auto-login
    if not st.session_state.authenticated:
        auth_token = st.query_params.get("auth")
        if not auth_token:
            try:
                import re
                m = re.search(r'(?:^|;\s*)iscan_sid=([^;]+)', st.context.headers.get("Cookie",""))
                if m: auth_token = m.group(1)
            except: pass
        if auth_token:
            user = validate_auth_token(st.session_state.db, auth_token)
            if user:
                st.session_state.authenticated = True
                st.session_state.user = user
    # Default states
    if "main_menu" not in st.session_state: st.session_state.main_menu = "Operasional"
    if "page" not in st.session_state: st.session_state.page = "Dashboard"
    if "scan_mode" not in st.session_state: st.session_state.scan_mode = "PACK"
    if "selected_store" not in st.session_state: st.session_state.selected_store = "Mitra Mulia Abadi"

# ═══════════ ACCOUNTING ═══════════
def post_jurnal(db, tanggal, no_ref, deskripsi, entries, sumber="", id_sumber=0):
    for kode, nama, deb, kred in entries:
        db.execute("INSERT INTO jurnal_umum (tanggal,no_ref,kode_akun,nama_akun,deskripsi,debit,kredit,sumber,id_sumber) VALUES (?,?,?,?,?,?,?,?,?)",
                   (tanggal, no_ref, kode, nama, deskripsi, deb, kred, sumber, id_sumber))

def auto_post_penjualan(db, pid, no_pesanan, tgl, mp, total, hpp, fee_mp, ppn=0):
    post_jurnal(db, tgl, f"INV-{no_pesanan}", f"Penjualan {mp}", [("1-1100","Piutang Usaha",total,0),("4-1000","Pendapatan Penjualan",0,total)], "penjualan", pid)
    if hpp > 0: post_jurnal(db, tgl, f"INV-{no_pesanan}", f"HPP {mp}", [("5-1000","HPP",hpp,0),("1-1200","Persediaan Barang",0,hpp)], "penjualan", pid)
    if fee_mp > 0: post_jurnal(db, tgl, f"INV-{no_pesanan}", f"Fee {mp}", [("5-1100","Beban Fee Marketplace",fee_mp,0),("1-1100","Piutang Usaha",0,fee_mp)], "penjualan", pid)

def post_packed_to_accounting(db, resi, tanggal=None):
    if not tanggal: tanggal = datetime.now().strftime("%d-%m-%Y")
    orders = db.fetch_all("SELECT id, no_pesanan, marketplace, total_harga, nama_produk, qty, sku_terdeteksi, ppn FROM penjualan WHERE no_resi = ?", (resi,))
    for o in (orders or []):
        ex = db.fetch_one("SELECT COUNT(*) as cnt FROM jurnal_umum WHERE sumber='penjualan' AND id_sumber=?", (o["id"],))
        if ex and ex["cnt"] > 0: continue
        hpp = 0
        if o["sku_terdeteksi"]:
            sr = db.fetch_one("SELECT harga_beli FROM sku WHERE kode_sku = ?", (o["sku_terdeteksi"].split(",")[0].strip(),))
            if sr and sr["harga_beli"]: hpp = sr["harga_beli"] * (o["qty"] or 1)
        if hpp == 0: hpp = (o["total_harga"] or 0) * 0.4
        fee_pct = 0; mp = (o["marketplace"] or "").upper()
        s = db.fetch_one("SELECT fee_shopee, fee_tiktok, fee_lazada FROM pengaturan LIMIT 1")
        if s:
            if "SHOPEE" in mp: fee_pct = s["fee_shopee"] or 0
            elif "TIKTOK" in mp: fee_pct = s["fee_tiktok"] or 0
            elif "LAZADA" in mp: fee_pct = s["fee_lazada"] or 0
        fee_mp = (o["total_harga"] or 0) * float(fee_pct) / 100
        auto_post_penjualan(db, o["id"], o["no_pesanan"], tanggal, o["marketplace"] or "Unknown", o["total_harga"] or 0, hpp, fee_mp, o["ppn"] or 0)

# ═══════════ AUTO AMORTISASI ═══════════
def auto_amortisasi_bulanan(db):
    today = datetime.now(); bln_ini = today.strftime("%m-%Y")
    last = _get_setting(db, "last_amortisasi", "")
    if last == bln_ini: return
    tgl_str = today.strftime("%d-%m-%Y")
    for p in db.fetch_all("SELECT * FROM pinjaman WHERE status='AKTIF' AND sisa_pokok>0") or []:
        ex = db.fetch_one("SELECT id FROM amortisasi WHERE jenis='PINJAMAN' AND id_ref=? AND periode_bulan=?", (p["id"], bln_ini))
        if ex: continue
        bunga = p["sisa_pokok"] * (p["bunga_persen"] or 0) / 100 / 12
        pokok = min((p["cicilan_per_bulan"] or 0) - bunga, p["sisa_pokok"])
        if pokok <= 0: pokok = p["sisa_pokok"]
        db.execute("INSERT INTO amortisasi (jenis,id_ref,periode_bulan,jumlah,keterangan) VALUES (?,?,?,?,?)", ("PINJAMAN", p["id"], bln_ini, round(bunga+pokok,2), f"Auto: {p['nama_bank']}"))
        db.execute("UPDATE pinjaman SET sisa_pokok=MAX(0,sisa_pokok-?), total_bunga_dibayar=total_bunga_dibayar+?, status=CASE WHEN sisa_pokok<=0 THEN 'LUNAS' ELSE 'AKTIF' END WHERE id=?", (round(pokok,2), round(bunga,2), p["id"]))
        if bunga > 0:
            post_jurnal(db, tgl_str, f"AMORT-{p['id']}", f"Bunga {p['nama_bank']}", [("5-1600","Beban Bunga",round(bunga,2),0),("1-1000","Kas & Bank",0,round(bunga,2))], "amortisasi", p["id"])
    _save_setting(db, "last_amortisasi", bln_ini)

# ═══════════ HELPERS ═══════════
def detect_expedition(resi, expeditions_cache):
    for nama, prefix_str in expeditions_cache:
        for prefix in [p.strip() for p in prefix_str.split(",") if p.strip()]:
            if resi.upper().startswith(prefix): return nama
    return "LAINNYA"

class ExpeditionCache:
    def __init__(self, db): self.db = db; self.expeditions = []; self.last_update = 0
    def get_expeditions(self):
        if not self.expeditions or time.time() - self.last_update > 300:
            self.expeditions = [(r["nama"], r["prefix"]) for r in self.db.fetch_all("SELECT nama, prefix FROM ekspedisi WHERE prefix != ''")]
            self.last_update = time.time()
        return self.expeditions
