"""
Constants module for iScan Pro.
"""

# App info
APP_NAME = "iScan Pro By MMA"
APP_VERSION = "2.0.0 (Streamlit Edition)"
APP_GEOMETRY = "1280x800"

# Scan status
class ScanStatus:
    KIRIM = "KIRIM"
    RETUR = "RETUR"
    PENDING = "PENDING"

# Default expedition list
DEFAULT_EXPEDITIONS = [
    ("SHOPEE INSTANT", "260", "Shopee Instant"),
    ("J&T CARGO (SHP)", "2013", "J&T untuk Shopee"),
    ("SICEPAT (SHP)", "4548", "Sicepat untuk Shopee"),
    ("INSTANT TIKTOK", "5819", "TikTok Shop Instant"),
    ("J&T CARGO (TT)", "570", "J&T untuk TikTok"),
    ("ID EXPRESS (TT)", "1000,TKP", "ID Express untuk TikTok"),
    ("LAZADA", "LXAD,NLIDAP", "Lazada"),
    ("SPX STANDAR", "SPXID", "SPX Standard"),
    ("J&T EXPRESS (TT)", "JX", "J&T Express TikTok"),
    ("JNE (SHP)", "CM", "JNE Shopee"),
    ("JNE REGULAR (TT)", "TG00", "JNE TikTok"),
    ("ID EXPRESS", "IDS,IDE", "ID Express"),
    ("J&T REGULAR", "JP,JNA", "J&T Regular"),
    ("SICEPAT", "00,SICE", "Sicepat"),
    ("SPX HEMAT", "NLID", "SPX Hemat"),
    ("LAINNYA", "", "Ekspedisi lain"),
]

# UI Constants
DEFAULT_ROW_HEIGHT = 35
DEFAULT_VISIBLE_ROWS = 20
SCAN_DELAY = 50  # ms
BATCH_SIZE = 100
THROTTLE_TIME = 300  # ms

# Logging
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5
LOG_MONTHLY_FORMAT = "%Y-%m"
