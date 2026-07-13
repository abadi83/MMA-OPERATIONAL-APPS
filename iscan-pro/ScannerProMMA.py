import customtkinter as ctk
from CTkTable import *
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import os
import sys
from tkinter import filedialog, messagebox, simpledialog, Toplevel
import winsound
import cv2
import threading
from PIL import Image, ImageTk
import time
import re
import logging
import logging.handlers
from enum import Enum
import functools
import atexit
import tkinter as tk
from tkinter import font as tkfont
from typing import List, Dict, Optional, Tuple, Any, Callable

# Import custom modules
try:
    from config import Config, Theme
    from constants import (
        APP_NAME, APP_VERSION, APP_GEOMETRY, 
        ScanStatus, DEFAULT_EXPEDITIONS, DEFAULT_ROW_HEIGHT,
        DEFAULT_VISIBLE_ROWS, SCAN_DELAY, BATCH_SIZE, THROTTLE_TIME,
        LOG_FORMAT, LOG_DATE_FORMAT, LOG_MAX_BYTES, LOG_BACKUP_COUNT, LOG_MONTHLY_FORMAT
    )
    from validators import Validator, validate_resi_or_raise, validate_store_or_raise
    from exceptions import (
        IScanException, DatabaseError, ValidationError, ConfigError,
        FileOperationError, CameraError, ReportGenerationError
    )
    from canvas_components import CanvasExpeditionChips, CanvasScanHistory
except ImportError as e:
    print(f"Error importing custom modules: {e}")
    sys.exit(1)

# ============ PATCH UNTUK FIX RECURSION ERROR DI SCROLLBAR ============
original_create_text = tk.Canvas.create_text

def safe_create_text(self, *args, **kwargs):
    try:
        return original_create_text(self, *args, **kwargs)
    except RecursionError:
        return 0
    except Exception:
        return 0

tk.Canvas.create_text = safe_create_text

if hasattr(ctk, 'CTkScrollbar'):
    original_draw = getattr(ctk.CTkScrollbar, '_draw', None)
    
    def safe_draw(self, *args, **kwargs):
        try:
            if original_draw:
                return original_draw(self, *args, **kwargs)
        except RecursionError:
            return
        except Exception:
            return
    
    if original_draw:
        ctk.CTkScrollbar._draw = safe_draw
# ========================================================

# ============ SAFE SCROLLABLE FRAME ============
class SafeScrollableFrame(ctk.CTkFrame):
    def __init__(self, master, orientation="vertical", **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        
        self.orientation = orientation
        self._update_scheduled = False
        
        if orientation == "vertical":
            self.canvas = tk.Canvas(
                self,
                highlightthickness=0,
                bg=Config.get_color("bg_primary", "#0A0A0A")
            )
            
            self.scrollbar = ctk.CTkScrollbar(
                self,
                orientation="vertical",
                command=self.canvas.yview,
                fg_color=Config.get_color("bg_tertiary"),
                button_color=Config.get_color("accent_alt"),
                button_hover_color=Config.get_color("accent")
            )
            
            self.canvas.configure(yscrollcommand=self.scrollbar.set)
            self.scrollable_frame = ctk.CTkFrame(self.canvas, fg_color="transparent")
            
            self.canvas.pack(side="left", fill="both", expand=True)
            self.scrollbar.pack(side="right", fill="y")
            
            self.canvas_window_id = self.canvas.create_window(
                (0, 0),
                window=self.scrollable_frame,
                anchor="nw",
                tags="inner_frame"
            )
            
            self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
            self.canvas.bind("<Configure>", self._on_canvas_configure)
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self.canvas.bind("<Button-4>", self._on_mousewheel)
            self.canvas.bind("<Button-5>", self._on_mousewheel)
        else:
            self.canvas = tk.Canvas(
                self,
                highlightthickness=0,
                bg=Config.get_color("bg_primary", "#0A0A0A")
            )
            
            self.scrollbar = ctk.CTkScrollbar(
                self,
                orientation="horizontal",
                command=self.canvas.xview,
                fg_color=Config.get_color("bg_tertiary"),
                button_color=Config.get_color("accent_alt"),
                button_hover_color=Config.get_color("accent")
            )
            
            self.canvas.configure(xscrollcommand=self.scrollbar.set)
            self.scrollable_frame = ctk.CTkFrame(self.canvas, fg_color="transparent")
            
            self.scrollbar.pack(side="bottom", fill="x")
            self.canvas.pack(side="top", fill="both", expand=True)
            
            self.canvas_window_id = self.canvas.create_window(
                (0, 0),
                window=self.scrollable_frame,
                anchor="nw",
                tags="inner_frame"
            )
            
            self.scrollable_frame.bind("<Configure>", self._on_frame_configure_horizontal)
            self.canvas.bind("<Configure>", self._on_canvas_configure_horizontal)
    
    def _on_frame_configure(self, event):
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)
    
    def _on_frame_configure_horizontal(self, event):
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)
    
    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window_id, width=event.width)
    
    def _on_canvas_configure_horizontal(self, event):
        self.canvas.itemconfig(self.canvas_window_id, height=event.height)
    
    def _on_mousewheel(self, event):
        if self.orientation == "vertical":
            if event.num == 4 or event.delta > 0:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5 or event.delta < 0:
                self.canvas.yview_scroll(1, "units")
        else:
            if event.num == 4 or event.delta > 0:
                self.canvas.xview_scroll(-1, "units")
            elif event.num == 5 or event.delta < 0:
                self.canvas.xview_scroll(1, "units")
    
    def destroy(self):
        try:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")
        except:
            pass
        super().destroy()
    
    def clear(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        self.after(50, self._update_scrollregion)
    
    def _update_scrollregion(self):
        try:
            bbox = self.canvas.bbox("all")
            if bbox:
                self.canvas.configure(scrollregion=bbox)
        except:
            pass

# ============ SF SYMBOLS ============
class Icons:
    dashboard = "􀎞"
    scan = "􀍉"
    reports = "􀈂"
    video = "􀎸"
    edit = "􀣔"
    new_session = "􀆨"
    save = "􀈎"
    archive = "􀈕"
    search = "􀊫"
    delete = "􀈑"
    pending = "􀐛"
    success = "􀁣"
    warning = "􀇾"
    error = "􀇿"
    info = "􀅴"
    settings = "􀣌"
    user = "􀉭"
    clock = "􀐫"
    calendar = "􀉉"
    box = "􀐚"
    truck = "􀐯"
    store = "􀋦"

# ============ LOGGING SETUP ============
def setup_logging() -> None:
    """Setup application logging with rotating file handler."""
    try:
        Config.ensure_folders()
        
        log_file = os.path.join(
            Config.LOGS_FOLDER,
            f"iscan_{datetime.now().strftime(LOG_MONTHLY_FORMAT)}.log"
        )
        
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
        logger.addHandler(console)
    except Exception as e:
        print(f"Logging setup error: {e}")

# ============ CUSTOM DIALOG ============
class CustomDialog:
    @staticmethod
    def _create_dialog(parent, message, title, icon, color_key):
        dialog = ctk.CTkToplevel(parent)
        dialog.title(title)
        dialog.geometry("400x200")
        dialog.configure(fg_color=Config.get_color("bg_secondary"))
        dialog.transient(parent)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (400 // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (200 // 2)
        dialog.geometry(f'+{x}+{y}')
        
        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(
            frame,
            text=icon,
            font=ctk.CTkFont(size=32),
            text_color=Config.get_color(color_key)
        ).pack(pady=(0, 10))
        
        ctk.CTkLabel(
            frame,
            text=message,
            font=ctk.CTkFont(size=14),
            wraplength=350,
            text_color=Config.get_color("text_primary")
        ).pack(expand=True)
        
        btn = ctk.CTkButton(
            frame,
            text="OK",
            width=100,
            height=35,
            fg_color=Config.get_color("accent"),
            hover_color="#0071E3",
            corner_radius=20,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=dialog.destroy
        )
        btn.pack(pady=10)
        btn.focus_set()
        
        dialog.bind("<Return>", lambda e: dialog.destroy())
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        
        parent.wait_window(dialog)
        return dialog
    
    @staticmethod
    def show_info(parent, message, title="Info"):
        CustomDialog._create_dialog(parent, message, title, Icons.info, "accent")
    
    @staticmethod
    def show_warning(parent, message, title="Peringatan"):
        CustomDialog._create_dialog(parent, message, title, Icons.warning, "warning")
    
    @staticmethod
    def show_error(parent, message, title="Error"):
        CustomDialog._create_dialog(parent, message, title, Icons.error, "danger")
    
    @staticmethod
    def show_question(parent, message, title="Konfirmasi"):
        result = [False]
        
        dialog = ctk.CTkToplevel(parent)
        dialog.title(title)
        dialog.geometry("400x220")
        dialog.configure(fg_color=Config.get_color("bg_secondary"))
        dialog.transient(parent)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (400 // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (110 // 2)
        dialog.geometry(f'+{x}+{y}')
        
        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(
            frame,
            text="❓",
            font=ctk.CTkFont(size=32),
            text_color=Config.get_color("accent")
        ).pack(pady=(0, 10))
        
        ctk.CTkLabel(
            frame,
            text=message,
            font=ctk.CTkFont(size=14),
            wraplength=350,
            text_color=Config.get_color("text_primary")
        ).pack(pady=5)
        
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(pady=10)
        
        def yes():
            result[0] = True
            dialog.destroy()
        
        def no():
            result[0] = False
            dialog.destroy()
        
        btn_yes = ctk.CTkButton(
            btn_frame,
            text="Ya",
            width=80,
            height=35,
            fg_color=Config.get_color("success"),
            hover_color="#28A745",
            corner_radius=20,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=yes
        )
        btn_yes.pack(side="left", padx=5)
        
        btn_no = ctk.CTkButton(
            btn_frame,
            text="Tidak",
            width=80,
            height=35,
            fg_color=Config.get_color("bg_tertiary"),
            hover_color=Config.get_color("menu_hover"),
            corner_radius=20,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=no
        )
        btn_no.pack(side="left", padx=5)
        
        btn_yes.focus_set()
        dialog.bind("<Return>", lambda e: yes())
        dialog.bind("<Escape>", lambda e: no())
        
        parent.wait_window(dialog)
        return result[0]

# ============ TOAST NOTIFICATION ============
class Toast:
    @staticmethod
    def show(parent, message, type="info", duration=3):
        try:
            toast = ctk.CTkToplevel(parent)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            toast.configure(bg="#00000000")
            
            colors = {
                "info": Config.get_color("accent"),
                "success": Config.get_color("success"),
                "warning": Config.get_color("warning"),
                "error": Config.get_color("danger")
            }
            bg_color = colors.get(type, Config.get_color("accent"))
            
            toast.geometry("300x60")
            x = parent.winfo_x() + parent.winfo_width() - 320
            y = parent.winfo_y() + parent.winfo_height() - 80
            toast.geometry(f'+{x}+{y}')
            
            frame = ctk.CTkFrame(
                toast,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=12,
                border_width=0.5,
                border_color=bg_color
            )
            frame.pack(fill="both", expand=True)
            
            icon = Icons.info
            if type == "success":
                icon = Icons.success
            elif type == "warning":
                icon = Icons.warning
            elif type == "error":
                icon = Icons.error
            
            inner = ctk.CTkFrame(frame, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=12, pady=10)
            
            ctk.CTkLabel(
                inner,
                text=icon,
                font=ctk.CTkFont(size=16),
                text_color=bg_color
            ).pack(side="left", padx=(0, 8))
            
            ctk.CTkLabel(
                inner,
                text=message,
                font=ctk.CTkFont(size=12),
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            toast.after(duration * 1000, toast.destroy)
        except Exception:
            pass

# ============ LOADING OVERLAY ============
class LoadingOverlay:
    def __init__(self, parent, message="Loading..."):
        self.parent = parent
        self.running = True
        
        self.overlay = ctk.CTkToplevel(parent)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-alpha", 0.95)
        self.overlay.configure(fg_color="#000000")
        
        self.overlay.geometry(f"{parent.winfo_width()}x{parent.winfo_height()}+{parent.winfo_x()}+{parent.winfo_y()}")
        
        parent.bind("<Configure>", self._update_position, add="+")
        
        content = ctk.CTkFrame(
            self.overlay,
            fg_color=Config.get_color("bg_secondary"),
            corner_radius=16,
            border_width=0.5,
            border_color=Config.get_color("border"),
            width=200,
            height=120
        )
        content.place(relx=0.5, rely=0.5, anchor="center")
        
        ctk.CTkLabel(
            content,
            text="⏳",
            font=ctk.CTkFont(size=32)
        ).pack(pady=(20, 5))
        
        self.label = ctk.CTkLabel(
            content,
            text=message,
            font=ctk.CTkFont(size=12),
            text_color=Config.get_color("text_primary")
        )
        self.label.pack()
        
        self.progress = ctk.CTkProgressBar(
            content,
            mode="indeterminate",
            fg_color=Config.get_color("bg_tertiary"),
            progress_color=Config.get_color("accent"),
            corner_radius=4
        )
        self.progress.pack(pady=10, padx=20, fill="x")
        self.progress.start()
        
        self.overlay.focus_force()
        self.overlay.grab_set()
    
    def _update_position(self, event=None):
        if self.running and hasattr(self, 'overlay') and self.overlay.winfo_exists():
            try:
                x = self.parent.winfo_rootx()
                y = self.parent.winfo_rooty()
                width = self.parent.winfo_width()
                height = self.parent.winfo_height()
                self.overlay.geometry(f"{width}x{height}+{x}+{y}")
            except:
                pass
    
    def destroy(self):
        self.running = False
        try:
            self.parent.unbind("<Configure>")
            if hasattr(self, 'overlay') and self.overlay.winfo_exists():
                self.overlay.grab_release()
                self.overlay.destroy()
        except:
            pass

# ============ EMPTY STATE ============
def show_empty_state(parent, message="Belum ada data", suggestion="", icon="📭"):
    try:
        for widget in parent.winfo_children():
            widget.destroy()
        
        empty_frame = ctk.CTkFrame(parent, fg_color="transparent")
        empty_frame.pack(expand=True, fill="both")
        
        ctk.CTkLabel(
            empty_frame,
            text=icon,
            font=ctk.CTkFont(size=64)
        ).pack(expand=True)
        
        ctk.CTkLabel(
            empty_frame,
            text=message,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=Config.get_color("text_secondary")
        ).pack(pady=(10, 5))
        
        if suggestion:
            ctk.CTkLabel(
                empty_frame,
                text=suggestion,
                font=ctk.CTkFont(size=13),
                text_color=Config.get_color("text_tertiary")
            ).pack()
    except Exception:
        pass

# ============ LOG DECORATOR ============
def log_activity(action: str) -> Callable:
    """Decorator to log activity with proper error handling.
    
    Args:
        action: Description of the action being logged
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            logger = logging.getLogger(func.__name__)
            try:
                result = func(self, *args, **kwargs)
                logger.info(f"{action} successful")
                return result
            except IScanException as e:
                logger.warning(f"{action} failed: {e}")
                raise
            except Exception as e:
                logger.error(f"{action} failed: {e}", exc_info=True)
                raise
        return wrapper
    return decorator

# ============ DATABASE ============
class Database:
    """Thread-safe SQLite database wrapper with connection pooling."""
    
    _instance: Optional['Database'] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> 'Database':
        """Singleton pattern with thread safety."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.logger = logging.getLogger("Database")
                cls._instance._initialize()
        return cls._instance
    
    def _initialize(self) -> None:
        """Initialize database connection and schema."""
        self._local = threading.local()
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn'):
            try:
                self._local.conn = sqlite3.connect(
                    Config.DB_PATH,
                    timeout=30,
                    isolation_level=None
                )
                self._local.conn.execute("PRAGMA journal_mode=WAL")
                self._local.conn.execute("PRAGMA foreign_keys=ON")
            except sqlite3.Error as e:
                raise DatabaseError(f"Failed to connect to database: {e}")
        return self._local.conn
    
    def _get_cursor(self) -> sqlite3.Cursor:
        """Get database cursor."""
        return self._get_conn().cursor()
    
    def execute(self, query: str, params: Optional[Tuple] = None, retry: int = 3) -> sqlite3.Cursor:
        """Execute SQL query with retry logic for locked database.
        
        Args:
            query: SQL query string
            params: Query parameters
            retry: Number of retries on database lock
            
        Returns:
            Cursor with results
            
        Raises:
            DatabaseError: If query fails
        """
        for attempt in range(retry):
            try:
                cursor = self._get_cursor()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                return cursor
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < retry - 1:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise DatabaseError(f"Database operational error: {e}")
            except sqlite3.Error as e:
                raise DatabaseError(f"Database error: {e}")
    
    def executemany(self, query: str, params_list: List[Tuple]) -> sqlite3.Cursor:
        """Execute multiple SQL queries in transaction.
        
        Args:
            query: SQL query string with placeholders
            params_list: List of parameter tuples
            
        Returns:
            Cursor with results
            
        Raises:
            DatabaseError: If transaction fails
        """
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
            return cursor
        except Exception as e:
            try:
                conn.rollback()
            except:
                pass
            raise DatabaseError(f"Transaction failed: {e}")
    
    def close_all(self) -> None:
        """Close all database connections."""
        try:
            if hasattr(self._local, 'conn'):
                self._local.conn.close()
        except Exception as e:
            self.logger.warning(f"Error closing connection: {e}")
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        try:
            self.execute("""
                CREATE TABLE IF NOT EXISTS toko (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT UNIQUE
                )
            """)
            
            self.execute("""
                CREATE TABLE IF NOT EXISTS ekspedisi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT UNIQUE,
                    prefix TEXT,
                    keterangan TEXT
                )
            """)
            
            self.execute("""
                CREATE TABLE IF NOT EXISTS list_arsip (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    judul TEXT, 
                    nama_file TEXT, 
                    tanggal TEXT
                )
            """)
            
            self.execute("""
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
            
            self.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user TEXT,
                    action TEXT,
                    details TEXT,
                    resi TEXT
                )
            """)
            
            cursor = self.execute("SELECT COUNT(*) FROM ekspedisi")
            if cursor.fetchone()[0] == 0:
                self._create_default_expedisi()
            
            cursor = self.execute("SELECT COUNT(*) FROM toko")
            if cursor.fetchone()[0] == 0:
                self.execute("INSERT INTO toko (nama) VALUES (?)", ("Mitra Mulia Abadi",))
            
            self.logger.info("Database initialized successfully")
            
        except Exception as e:
            raise DatabaseError(f"Database initialization error: {e}")
    
    def _create_default_expedisi(self) -> None:
        """Create default expedition list."""
        try:
            for nama, prefix, ket in DEFAULT_EXPEDITIONS:
                self.execute(
                    "INSERT OR IGNORE INTO ekspedisi (nama, prefix, keterangan) VALUES (?, ?, ?)",
                    (nama, prefix, ket)
                )
        except Exception as e:
            self.logger.error(f"Failed to create default expeditions: {e}")

# ============ CACHE UNTUK EXPEDISI ============
class ExpeditionCache:
    """Cache for expedition data to reduce database queries."""
    
    def __init__(self, db: Database) -> None:
        """Initialize expedition cache.
        
        Args:
            db: Database instance
        """
        self.db = db
        self.expeditions: List[Tuple[str, str]] = []
        self.last_update: float = 0
        self.cache_duration: int = 300
        self.logger = logging.getLogger("ExpeditionCache")
    
    def get_expeditions(self) -> List[Tuple[str, str]]:
        """Get expeditions list with caching.
        
        Returns:
            List of (name, prefix) tuples
        """
        now = time.time()
        if not self.expeditions or (now - self.last_update) > self.cache_duration:
            try:
                cursor = self.db.execute("SELECT nama, prefix FROM ekspedisi WHERE prefix != ''")
                self.expeditions = cursor.fetchall()
                self.last_update = now
            except DatabaseError as e:
                self.logger.error(f"Failed to fetch expeditions: {e}")
        return self.expeditions
    
    def invalidate(self) -> None:
        """Invalidate cache to force refresh on next access."""
        self.expeditions = []
        self.last_update = 0

# ============ MODERN WINDOW ============
class ModernWindow:
    def __init__(self, parent, title="", width=800, height=600):
        self.parent = parent
        self.width = width
        self.height = height
        self.title_text = title
        
        self.window = ctk.CTkToplevel(parent)
        self.window.title("")
        self.window.configure(fg_color=Config.get_color("bg_primary"))
        self.window.attributes("-topmost", True)
        self.window.transient(parent)
        
        self.window.overrideredirect(True)
        
        self.center_window()
        self.create_title_bar()
        
        self.main_container = ctk.CTkFrame(
            self.window,
            fg_color=Config.get_color("bg_secondary"),
            corner_radius=0
        )
        self.main_container.pack(fill="both", expand=True, padx=0, pady=(30, 0))
        
        self.title_bar.bind("<Button-1>", self.start_move)
        self.title_bar.bind("<B1-Motion>", self.on_move)
        self.title_label.bind("<Button-1>", self.start_move)
        self.title_label.bind("<B1-Motion>", self.on_move)
    
    def create_title_bar(self):
        self.title_bar = ctk.CTkFrame(
            self.window,
            fg_color=Config.get_color("bg_secondary"),
            height=30,
            corner_radius=0
        )
        self.title_bar.pack(fill="x", padx=0, pady=0)
        self.title_bar.pack_propagate(False)
        
        self.title_label = ctk.CTkLabel(
            self.title_bar,
            text=self.title_text,
            font=ctk.CTkFont(size=13),
            text_color=Config.get_color("text_primary")
        )
        self.title_label.pack(side="left", padx=12, pady=5)
        
        controls_frame = ctk.CTkFrame(self.title_bar, fg_color="transparent")
        controls_frame.pack(side="right", padx=8, pady=4)
        
        self.btn_minimize = ctk.CTkButton(
            controls_frame,
            text="─",
            width=30,
            height=22,
            corner_radius=6,
            fg_color=Config.get_color("bg_tertiary"),
            hover_color=Config.get_color("menu_hover"),
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.minimize_window
        )
        self.btn_minimize.pack(side="left", padx=2)
        
        self.btn_maximize = ctk.CTkButton(
            controls_frame,
            text="□",
            width=30,
            height=22,
            corner_radius=6,
            fg_color=Config.get_color("bg_tertiary"),
            hover_color=Config.get_color("menu_hover"),
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.toggle_maximize
        )
        self.btn_maximize.pack(side="left", padx=2)
        
        self.btn_close = ctk.CTkButton(
            controls_frame,
            text="✕",
            width=30,
            height=22,
            corner_radius=6,
            fg_color=Config.get_color("bg_tertiary"),
            hover_color=Config.get_color("danger"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.close_window
        )
        self.btn_close.pack(side="left", padx=2)
        
        self.maximized = False
        self.normal_geometry = None
    
    def start_move(self, event):
        self.x = event.x
        self.y = event.y
    
    def on_move(self, event):
        if not self.maximized:
            deltax = event.x - self.x
            deltay = event.y - self.y
            x = self.window.winfo_x() + deltax
            y = self.window.winfo_y() + deltay
            self.window.geometry(f"+{x}+{y}")
    
    def minimize_window(self):
        self.window.iconify()
    
    def toggle_maximize(self):
        if not self.maximized:
            self.normal_geometry = self.window.geometry()
            screen_width = self.window.winfo_screenwidth()
            screen_height = self.window.winfo_screenheight()
            self.window.geometry(f"{screen_width}x{screen_height}+0+0")
            self.maximized = True
        else:
            if self.normal_geometry:
                self.window.geometry(self.normal_geometry)
            else:
                self.center_window()
            self.maximized = False
    
    def center_window(self):
        self.window.update_idletasks()
        x = (self.window.winfo_screenwidth() // 2) - (self.width // 2)
        y = (self.window.winfo_screenheight() // 2) - (self.height // 2)
        self.window.geometry(f"{self.width}x{self.height}+{x}+{y}")
    
    def close_window(self):
        try:
            self.window.destroy()
        except:
            pass

# ============ MAIN APP ============
class IScanApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        setup_logging()
        self.logger = logging.getLogger("IScanApp")
        
        self.setup_fonts()
        Config.ensure_folders()
        
        self.title("")
        self.geometry(Config.APP_GEOMETRY)
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=Config.get_color("bg_primary"))
        
        if getattr(sys, 'frozen', False):
            self.base_path = os.path.dirname(sys.executable)
        else:
            self.base_path = os.path.dirname(os.path.abspath(__file__))
        
        self.folder_arsip = os.path.join(self.base_path, "Gudang_Arsip_Excel")
        self.folder_handover = os.path.join(self.base_path, "Handover_Reports")
        self.folder_sales = os.path.join(self.base_path, "Sales_Reports")
        self.folder_videos = os.path.join(self.base_path, "Packing_Videos")
        
        for folder in [self.folder_arsip, self.folder_handover, self.folder_sales, self.folder_videos]:
            if not os.path.exists(folder):
                os.makedirs(folder)
        
        self.is_retur_mode = ctk.BooleanVar(value=False)
        self.current_theme = Theme.DARK
        Config.set_theme(Theme.DARK)
        
        self.db = Database()
        self.expedition_cache = ExpeditionCache(self.db)
        
        self.header = [["Waktu", "Tanggal", "Nomor Resi", "Ekspedisi", "Toko", "Status"]]
        self.col_widths = [80, 90, 150, 130, 120, 70]
        
        try:
            cursor = self.db.execute("SELECT waktu, tanggal, resi, ekspedisi, toko, status FROM scan_aktif ORDER BY id DESC")
            self.active_data = [list(row) for row in cursor.fetchall()]
            self.resi_set = set(r[2] for r in self.active_data if len(r) > 2)
        except Exception as e:
            self.logger.error(f"Failed to load active data: {e}")
            self.active_data = []
            self.resi_set = set()
        
        self.pending_rows = []
        self.batch_size = BATCH_SIZE
        
        # Cache untuk performance
        self.expedisi_cache_data = {}
        self.expedisi_widgets = {}
        self._update_scheduled = False
        
        # Anti double scan
        self.scan_lock = threading.Lock()
        self.scan_queue = []
        self.processing_queue = False
        self.scan_delay = SCAN_DELAY
        
        self.setup_ui()
        self.setup_app_icon()
        self.setup_shortcuts()
        
        atexit.register(self.cleanup)
        
        self.logger.info(f"Application started with {len(self.active_data)} existing scans")
    
    def setup_fonts(self):
        self.font_large_title = ctk.CTkFont(family="SF Pro Display", size=34, weight="bold")
        self.font_title_1 = ctk.CTkFont(family="SF Pro Display", size=28, weight="bold")
        self.font_title_2 = ctk.CTkFont(family="SF Pro Display", size=22, weight="bold")
        self.font_title_3 = ctk.CTkFont(family="SF Pro Display", size=20, weight="bold")
        self.font_headline = ctk.CTkFont(family="SF Pro Text", size=15, weight="bold")
        self.font_body = ctk.CTkFont(family="SF Pro Text", size=15, weight="normal")
        self.font_caption = ctk.CTkFont(family="SF Pro Text", size=12, weight="normal")
        self.font_button = ctk.CTkFont(family="SF Pro Text", size=15, weight="bold")
        self.font_button_large = ctk.CTkFont(family="SF Pro Text", size=17, weight="bold")
    
    def cleanup(self):
        try:
            self.flush_pending_rows()
            self.db.close_all()
        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")
    
    def flush_pending_rows(self) -> None:
        """Flush pending rows to database."""
        if self.pending_rows:
            try:
                self.db.executemany(
                    "INSERT INTO scan_aktif (waktu, tanggal, resi, ekspedisi, toko, status) VALUES (?, ?, ?, ?, ?, ?)",
                    self.pending_rows
                )
                self.pending_rows = []
            except DatabaseError as e:
                self.logger.error(f"Failed to flush pending rows: {e}")
                raise
    
    def setup_app_icon(self):
        try:
            icon_path = os.path.join(self.base_path, "logo.png")
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
                img = img.resize((64, 64), Image.Resampling.LANCZOS)
                icon = ImageTk.PhotoImage(img)
                self.iconphoto(True, icon)
                self.app_icon = icon
        except Exception as e:
            self.logger.warning(f"Failed to load icon: {e}")
    
    def setup_shortcuts(self):
        try:
            self.bind_all("<Control-s>", lambda e: self.save_ke_arsip_excel())
            self.bind_all("<Control-z>", lambda e: self.hapus_item_tabel())
            self.bind_all("<Control-n>", lambda e: self.mulai_baru_reset())
            self.bind_all("<Control-f>", lambda e: self.entry_resi.focus())
            self.bind_all("<Escape>", lambda e: self.entry_resi.delete(0, 'end'))
            self.bind_all("<F1>", lambda e: self.show_help())
            self.bind_all("<Control-,>", lambda e: self.buka_edit_ekspedisi())
            self.bind_all("<Control-p>", lambda e: self.buka_pending_report())
        except Exception as e:
            self.logger.error(f"Failed to setup shortcuts: {e}")
    
    def show_help(self):
        help_text = """
        ⌨️ KEYBOARD SHORTCUTS
        ─────────────────────
        Ctrl+S  : Save to Archive
        Ctrl+Z  : Undo (hapus terakhir)
        Ctrl+N  : New Session
        Ctrl+F  : Focus ke scan field
        Ctrl+,  : Edit Ekspedisi
        Ctrl+P  : Pending Report
        Esc     : Clear scan field
        F1      : Bantuan ini
        """
        CustomDialog.show_info(self, help_text, "Keyboard Shortcuts")
    
    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to clipboard with feedback.
        
        Args:
            text: Text to copy
        """
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            Toast.show(self, "Teks disalin!", "success", 1)
        except Exception as e:
            self.logger.warning(f"Failed to copy to clipboard: {e}")
    
    def animate_value(self, label, target, current=None):
        try:
            if current is None:
                try:
                    current = int(label.cget("text"))
                except:
                    current = 0
            
            if current < target:
                new = current + 1
                label.configure(text=str(new))
                self.after(10, lambda: self.animate_value(label, target, new))
            elif current > target:
                new = current - 1
                label.configure(text=str(new))
                self.after(10, lambda: self.animate_value(label, target, new))
        except:
            try:
                label.configure(text=str(target))
            except:
                pass
    
    def toggle_theme(self):
        try:
            if self.current_theme == Theme.DARK:
                ctk.set_appearance_mode("light")
                self.current_theme = Theme.LIGHT
                Config.set_theme(Theme.LIGHT)
                self.theme_btn.configure(text="🌙")
                self.logger.info("Theme switched to light")
            else:
                ctk.set_appearance_mode("dark")
                self.current_theme = Theme.DARK
                Config.set_theme(Theme.DARK)
                self.theme_btn.configure(text="🌓")
                self.logger.info("Theme switched to dark")
            
            self.configure(fg_color=Config.get_color("bg_primary"))
            self.update_theme_colors()
        except Exception as e:
            self.logger.error(f"Theme toggle error: {e}")
    
    def update_theme_colors(self):
        try:
            self.sidebar.configure(fg_color=Config.get_color("bg_secondary"))
            
            for btn in self.sidebar_buttons:
                btn.configure(
                    text_color=Config.get_color("sidebar_text"),
                    hover_color=Config.get_color("menu_hover")
                )
            
            self.update_expedisi_chips()
        except Exception as e:
            self.logger.error(f"Update theme colors error: {e}")
    
    def create_stat_card(self, icon, title, value, color):
        try:
            card = ctk.CTkFrame(
                self.stats_grid,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=16,
                height=70,
                border_width=0.5,
                border_color=Config.get_color("border")
            )
            card.pack_propagate(False)
            
            inner_frame = ctk.CTkFrame(card, fg_color="transparent")
            inner_frame.pack(fill="both", expand=True, padx=15, pady=10)
            
            left_frame = ctk.CTkFrame(inner_frame, fg_color="transparent")
            left_frame.pack(side="left", fill="y")
            
            icon_label = ctk.CTkLabel(
                left_frame,
                text=icon,
                font=ctk.CTkFont(size=24),
                text_color=color
            )
            icon_label.pack(side="left", padx=(0, 8))
            
            title_label = ctk.CTkLabel(
                left_frame,
                text=title,
                font=self.font_headline,
                text_color=Config.get_color("text_secondary")
            )
            title_label.pack(side="left")
            
            value_label = ctk.CTkLabel(
                inner_frame,
                text=value,
                font=self.font_title_2,
                text_color=color
            )
            value_label.pack(side="right")
            
            if "Total Paket" in title:
                self.label_total = value_label
            elif "Total Retur" in title:
                self.label_retur = value_label
            elif "Total Pending" in title:
                self.label_pending = value_label
            
            return card
        except Exception as e:
            self.logger.error(f"Create stat card error: {e}")
            return None
    
    def deteksi_ekspedisi_cepat(self, resi: str) -> str:
        """Detect expedition from resi/tracking number.
        
        Args:
            resi: Tracking number
            
        Returns:
            Expedition name
        """
        try:
            expeditions = self.expedition_cache.get_expeditions()
            r = resi.upper().strip()
            
            for nama, prefix_str in expeditions:
                if not prefix_str:
                    continue
                prefixes = [p.strip() for p in prefix_str.split(',') if p.strip()]
                for prefix in prefixes:
                    if r.startswith(prefix):
                        return nama
        except DatabaseError as e:
            self.logger.error(f"Error detecting expedition: {e}")
        
        return "LAINNYA"
    
    def refresh_stats_from_data(self):
        try:
            total_kirim = len([r for r in self.active_data if len(r) > 5 and r[5] == ScanStatus.KIRIM])
            total_retur = len([r for r in self.active_data if len(r) > 5 and r[5] == ScanStatus.RETUR])
            total_pending = len([r for r in self.active_data if len(r) > 5 and r[5] == ScanStatus.PENDING])
            
            if hasattr(self, 'label_total'):
                self.animate_value(self.label_total, total_kirim)
            if hasattr(self, 'label_retur'):
                self.animate_value(self.label_retur, total_retur)
            if hasattr(self, 'label_pending'):
                self.animate_value(self.label_pending, total_pending)
            if hasattr(self, 'count_label'):
                self.count_label.configure(text=f"{len(self.active_data)} items")
        except Exception as e:
            self.logger.error(f"Refresh stats error: {e}")
    
    def before_critical_operation(self):
        self.flush_pending_rows()
    
    def setup_ui(self):
        try:
            self.main_container = ctk.CTkFrame(self, fg_color="transparent")
            self.main_container.pack(fill="both", expand=True, padx=20, pady=20)
            
            # SIDEBAR
            self.sidebar = ctk.CTkFrame(
                self.main_container,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=20,
                width=220,
                border_width=0.5,
                border_color=Config.get_color("border")
            )
            self.sidebar.pack(side="left", fill="y", padx=(0, 20))
            self.sidebar.pack_propagate(False)
            
            # Logo
            logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
            logo_frame.pack(fill="x", padx=15, pady=(30, 40))
            
            logo_inner = ctk.CTkFrame(logo_frame, fg_color="transparent")
            logo_inner.pack(anchor="w")
            
            ctk.CTkLabel(
                logo_inner,
                text="iScan",
                font=self.font_large_title,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            ctk.CTkLabel(
                logo_inner,
                text="Pro",
                font=self.font_title_2,
                text_color=Config.get_color("accent")
            ).pack(side="left", padx=(5, 0))
            
            ctk.CTkLabel(
                logo_inner,
                text="By MMA",
                font=self.font_caption,
                text_color=Config.get_color("text_secondary")
            ).pack(side="left", padx=(5, 0))
            
            # Menu items
            menu_items = [
                (Icons.dashboard, "Dashboard", self.show_dashboard),
                (Icons.scan, "Scan", self.focus_scan),
                (Icons.reports, "Reports", self.show_reports_menu),
                (Icons.video, "Video Packing", self.buka_video_packing),
                (Icons.edit, "Edit Ekspedisi", self.buka_edit_ekspedisi),
                (Icons.new_session, "New Session", self.mulai_baru_reset),
                (Icons.save, "Save to Archive", self.save_ke_arsip_excel),
                (Icons.archive, "Archive", self.buka_window_arsip),
            ]
            
            self.sidebar_buttons = []
            for icon, text, command in menu_items:
                btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
                btn_frame.pack(fill="x", padx=10, pady=2)
                
                ctk.CTkLabel(
                    btn_frame,
                    text=icon,
                    font=ctk.CTkFont(size=16),
                    text_color=Config.get_color("text_secondary"),
                    width=30
                ).pack(side="left")
                
                btn = ctk.CTkButton(
                    btn_frame,
                    text=text,
                    font=self.font_body,
                    fg_color="transparent",
                    hover_color=Config.get_color("menu_hover"),
                    anchor="w",
                    height=36,
                    corner_radius=8,
                    command=command,
                    text_color=Config.get_color("sidebar_text")
                )
                btn.pack(side="left", fill="x", expand=True)
                self.sidebar_buttons.append(btn)
            
            # Main content
            self.content = ctk.CTkFrame(self.main_container, fg_color="transparent")
            self.content.pack(side="right", fill="both", expand=True)
            
            # Header
            self.header_frame_ui = ctk.CTkFrame(self.content, fg_color="transparent", height=70)
            self.header_frame_ui.pack(fill="x", pady=(0, 20))
            self.header_frame_ui.pack_propagate(False)
            
            title_frame = ctk.CTkFrame(self.header_frame_ui, fg_color="transparent")
            title_frame.pack(side="left")
            
            ctk.CTkLabel(
                title_frame,
                text="Dashboard",
                font=self.font_title_1,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            # Right actions
            action_frame = ctk.CTkFrame(self.header_frame_ui, fg_color="transparent")
            action_frame.pack(side="right")
            
            self.theme_btn = ctk.CTkButton(
                action_frame,
                text="🌓",
                width=40,
                height=36,
                corner_radius=10,
                fg_color=Config.get_color("bg_tertiary"),
                hover_color=Config.get_color("menu_hover"),
                font=ctk.CTkFont(size=16, weight="bold"),
                command=self.toggle_theme
            )
            self.theme_btn.pack(side="right", padx=5)
            
            # Store selector
            store_frame = ctk.CTkFrame(action_frame, fg_color="transparent")
            store_frame.pack(side="left", padx=(0, 15))
            
            ctk.CTkLabel(
                store_frame,
                text=Icons.store,
                font=ctk.CTkFont(size=14),
                text_color=Config.get_color("text_secondary")
            ).pack(side="left", padx=(0, 5))
            
            self.toko_var = ctk.StringVar(value="Mitra Mulia Abadi")
            self.daftar_toko = self.get_stored_stores()
            
            self.toko_menu = ctk.CTkOptionMenu(
                store_frame,
                values=self.daftar_toko,
                variable=self.toko_var,
                width=180,
                height=36,
                corner_radius=10,
                fg_color=Config.get_color("bg_tertiary"),
                button_color=Config.get_color("accent_alt"),
                dropdown_fg_color=Config.get_color("bg_secondary"),
                font=self.font_body
            )
            self.toko_menu.pack(side="left")
            
            self.add_store_btn = ctk.CTkButton(
                store_frame,
                text="+",
                width=36,
                height=36,
                corner_radius=10,
                fg_color=Config.get_color("bg_tertiary"),
                hover_color=Config.get_color("menu_hover"),
                font=ctk.CTkFont(size=16, weight="bold"),
                command=self.tambah_toko_custom
            )
            self.add_store_btn.pack(side="left", padx=2)
            
            self.remove_store_btn = ctk.CTkButton(
                store_frame,
                text="−",
                width=36,
                height=36,
                corner_radius=10,
                fg_color=Config.get_color("bg_tertiary"),
                hover_color=Config.get_color("menu_hover"),
                font=ctk.CTkFont(size=16, weight="bold"),
                command=self.hapus_toko_window
            )
            self.remove_store_btn.pack(side="left", padx=2)
            
            self.retur_switch = ctk.CTkSwitch(
                action_frame,
                text="Mode Retur",
                variable=self.is_retur_mode,
                command=self.update_ui_mode,
                font=self.font_body,
                progress_color=Config.get_color("danger"),
                fg_color=Config.get_color("bg_tertiary"),
                switch_width=46,
                switch_height=24
            )
            self.retur_switch.pack(side="left")
            
            # SCAN CARD
            self.scan_card = ctk.CTkFrame(
                self.content,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=24,
                height=120,
                border_width=0.5,
                border_color=Config.get_color("accent")
            )
            self.scan_card.pack(fill="x", pady=(0, 25))
            self.scan_card.pack_propagate(False)
            
            scan_inner = ctk.CTkFrame(self.scan_card, fg_color="transparent")
            scan_inner.pack(fill="both", expand=True, padx=30, pady=25)
            
            ctk.CTkLabel(
                scan_inner,
                text=Icons.scan,
                font=ctk.CTkFont(size=28),
                text_color=Config.get_color("accent")
            ).pack(side="left", padx=(0, 15))
            
            self.entry_resi = ctk.CTkEntry(
                scan_inner,
                placeholder_text="Scan barcode atau ketik nomor resi",
                height=50,
                font=self.font_body,
                fg_color=Config.get_color("bg_tertiary"),
                border_width=0,
                corner_radius=12,
                placeholder_text_color=Config.get_color("text_tertiary")
            )
            self.entry_resi.pack(side="left", fill="x", expand=True)
            self.entry_resi.bind("<Return>", self.proses_scan_cepat)
            self.entry_resi.focus()
            
            # STATISTICS CARDS
            self.stats_container = ctk.CTkFrame(self.content, fg_color="transparent", height=80)
            self.stats_container.pack(fill="x", pady=(0, 25))
            self.stats_container.pack_propagate(False)
            
            self.stats_grid = ctk.CTkFrame(self.stats_container, fg_color="transparent")
            self.stats_grid.pack(fill="both", expand=True)
            
            total_kirim = len([r for r in self.active_data if len(r) > 5 and r[5] == ScanStatus.KIRIM])
            total_retur = len([r for r in self.active_data if len(r) > 5 and r[5] == ScanStatus.RETUR])
            total_pending = len([r for r in self.active_data if len(r) > 5 and r[5] == ScanStatus.PENDING])
            
            self.total_card = self.create_stat_card(
                "📦", "Total Paket", str(total_kirim), Config.get_color("success")
            )
            if self.total_card:
                self.total_card.pack(side="left", padx=(0, 15), fill="both", expand=True)
            
            self.retur_card = self.create_stat_card(
                "↩️", "Total Retur", str(total_retur), Config.get_color("danger")
            )
            if self.retur_card:
                self.retur_card.pack(side="left", padx=(0, 15), fill="both", expand=True)
            
            self.pending_card = self.create_stat_card(
                "⏳", "Total Pending", str(total_pending), Config.get_color("warning")
            )
            if self.pending_card:
                self.pending_card.pack(side="left", fill="both", expand=True)
            
            # EXPEDISI CHIPS - Canvas Version
            self.expedisi_frame = ctk.CTkFrame(
                self.content,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=20,
                height=150,
                border_width=0.5,
                border_color=Config.get_color("border")
            )
            self.expedisi_frame.pack(fill="x", pady=(0, 25))
            self.expedisi_frame.pack_propagate(False)
            
            header_frame = ctk.CTkFrame(self.expedisi_frame, fg_color="transparent")
            header_frame.pack(fill="x", padx=20, pady=(15, 5))
            
            ctk.CTkLabel(
                header_frame,
                text=Icons.truck + " Ekspedisi",
                font=self.font_headline,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            # Canvas-based expedition chips
            self.canvas_expedisi = CanvasExpeditionChips(self.expedisi_frame, width=1000, height=120)
            self.canvas_expedisi.clicked_callback = self.buka_detail_ekspedisi
            
            # VIRTUAL TABLE untuk SCAN HISTORY
            self.table_card = ctk.CTkFrame(
                self.content,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=20,
                border_width=0.5,
                border_color=Config.get_color("border")
            )
            self.table_card.pack(fill="both", expand=True)
            
            table_header = ctk.CTkFrame(self.table_card, fg_color="transparent", height=50)
            table_header.pack(fill="x", padx=20, pady=(15, 0))
            table_header.pack_propagate(False)
            
            ctk.CTkLabel(
                table_header,
                text="📋 Scan History",
                font=self.font_title_3,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            self.count_label = ctk.CTkLabel(
                table_header,
                text=f"{len(self.active_data)} items",
                font=self.font_caption,
                text_color=Config.get_color("text_secondary")
            )
            self.count_label.pack(side="right")
            
            self.table_container = ctk.CTkFrame(self.table_card, fg_color="transparent")
            self.table_container.pack(fill="both", expand=True, padx=20, pady=(10, 20))
            
            # Canvas-based scan history with copy functionality
            self.canvas_history = CanvasScanHistory(
                self.table_container,
                self.header[0],
                self.col_widths,
                height=400
            )
            self.canvas_history.copy_callback = self.copy_to_clipboard
            
            # DELETE SECTION
            self.delete_section = ctk.CTkFrame(self.content, fg_color="transparent", height=60)
            self.delete_section.pack(fill="x", pady=(0, 25))
            self.delete_section.pack_propagate(False)
            
            entry_frame = ctk.CTkFrame(self.delete_section, fg_color=Config.get_color("bg_secondary"), corner_radius=12)
            entry_frame.pack(side="left", fill="x", expand=True, padx=(0, 15))
            
            ctk.CTkLabel(
                entry_frame,
                text=Icons.delete,
                font=ctk.CTkFont(size=14),
                text_color=Config.get_color("text_secondary")
            ).pack(side="left", padx=(15, 5))
            
            self.entry_hapus_resi = ctk.CTkEntry(
                entry_frame,
                placeholder_text="Nomor resi yang akan dihapus",
                height=44,
                font=self.font_body,
                fg_color="transparent",
                border_width=0,
                placeholder_text_color=Config.get_color("text_tertiary")
            )
            self.entry_hapus_resi.pack(side="left", fill="x", expand=True, padx=5)
            
            self.pending_toggle_btn = ctk.CTkButton(
                self.delete_section,
                text=Icons.pending + " Toggle Pending",
                font=self.font_button,
                fg_color=Config.get_color("warning"),
                hover_color="#D98C0A",
                height=44,
                width=160,
                corner_radius=22,
                command=self.toggle_status_pending
            )
            self.pending_toggle_btn.pack(side="right", padx=(0, 10))
            
            self.delete_btn = ctk.CTkButton(
                self.delete_section,
                text="Remove",
                font=self.font_button,
                fg_color=Config.get_color("danger"),
                hover_color="#D70015",
                height=44,
                width=120,
                corner_radius=22,
                command=self.hapus_resi_spesifik
            )
            self.delete_btn.pack(side="right", padx=(0, 10))
            
            # ACTION BUTTONS
            self.action_buttons = ctk.CTkFrame(self.content, fg_color="transparent", height=70)
            self.action_buttons.pack(fill="x", side="bottom", pady=(0, 10))
            self.action_buttons.pack_propagate(False)
            
            button_container = ctk.CTkFrame(self.action_buttons, fg_color="transparent")
            button_container.pack(side="right")
            
            self.undo_btn = ctk.CTkButton(
                button_container,
                text=Icons.delete + " Undo",
                font=self.font_button_large,
                fg_color=Config.get_color("danger"),
                hover_color="#D70015",
                height=50,
                width=150,
                corner_radius=25,
                command=self.hapus_item_tabel
            )
            self.undo_btn.pack(side="left", padx=(0, 10))
            
            self.new_session_btn = ctk.CTkButton(
                button_container,
                text=Icons.new_session + " New Session",
                font=self.font_button_large,
                fg_color=Config.get_color("accent"),
                hover_color="#0071E3",
                height=50,
                width=180,
                corner_radius=25,
                command=self.mulai_baru_reset
            )
            self.new_session_btn.pack(side="left", padx=(0, 10))
            
            self.save_archive_btn = ctk.CTkButton(
                button_container,
                text=Icons.save + " Save to Archive",
                font=self.font_button_large,
                fg_color=Config.get_color("accent_alt"),
                hover_color="#4A4A9E",
                height=50,
                width=200,
                corner_radius=25,
                command=self.save_ke_arsip_excel
            )
            self.save_archive_btn.pack(side="left", padx=(0, 10))
            
            # Initial update
            self.update_expedisi_chips()
            self.canvas_history.set_data(self.active_data)
        except Exception as e:
            self.logger.error(f"Setup UI error: {e}")

# ============ VIDEO PACKING WINDOW ============
class VideoPackingWindow:
    def __init__(self, parent, callback_resi_scan=None):
        self.parent = parent
        self.callback_resi_scan = callback_resi_scan
        self.logger = logging.getLogger("VideoPacking")
        
        self.window = ModernWindow(
            parent,
            title="Video Packing - iScan Pro By MMA",
            width=1000,
            height=750
        )
        
        self.is_recording = False
        self.current_resi = None
        self.video_writer = None
        self.camera = None
        self.recording_thread = None
        self.preview_active = False
        self.current_filepath = None
        self.frame_count = 0
        
        self.video_folder = os.path.join(Config.BASE_PATH, "Packing_Videos")
        if not os.path.exists(self.video_folder):
            os.makedirs(self.video_folder)
        
        self.setup_ui()
    
    def pilih_folder(self):
        try:
            self.window.window.attributes("-topmost", False)
            folder_selected = filedialog.askdirectory(
                title="Pilih Folder Penyimpanan Video",
                initialdir=self.video_folder
            )
            self.window.window.attributes("-topmost", True)
            
            if folder_selected:
                self.video_folder = folder_selected
                self.folder_label.configure(text=self.video_folder)
                CustomDialog.show_info(
                    self.window.window,
                    f"Folder penyimpanan diubah ke:\n{self.video_folder}"
                )
        except Exception as e:
            self.logger.error(f"Pilih folder error: {e}")
    
    def setup_ui(self):
        try:
            container = self.window.main_container
            
            content = ctk.CTkFrame(container, fg_color="transparent")
            content.pack(fill="both", expand=True, padx=25, pady=25)
            
            left_panel = ctk.CTkFrame(content, fg_color=Config.get_color("bg_element"), corner_radius=12)
            left_panel.pack(side="left", fill="both", expand=True, padx=(0, 15))
            
            ctk.CTkLabel(
                left_panel,
                text="Camera Preview",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=Config.get_color("text_primary")
            ).pack(anchor="w", padx=15, pady=(15, 10))
            
            self.preview_frame = ctk.CTkFrame(
                left_panel,
                fg_color=Config.get_color("bg_dark"),
                corner_radius=8,
                height=300,
                width=400
            )
            self.preview_frame.pack(padx=15, pady=(0, 15))
            self.preview_frame.pack_propagate(False)
            
            self.preview_label = ctk.CTkLabel(
                self.preview_frame,
                text="Camera Off",
                font=ctk.CTkFont(size=16),
                text_color=Config.get_color("text_secondary")
            )
            self.preview_label.pack(expand=True)
            
            camera_controls = ctk.CTkFrame(left_panel, fg_color="transparent")
            camera_controls.pack(fill="x", padx=15, pady=(0, 15))
            
            self.btn_start_camera = ctk.CTkButton(
                camera_controls,
                text="▶ Start Camera",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=Config.get_color("accent"),
                hover_color="#0071E3",
                height=36,
                width=120,
                corner_radius=8,
                command=self.toggle_camera
            )
            self.btn_start_camera.pack(side="left", padx=(0, 10))
            
            self.btn_start_recording = ctk.CTkButton(
                camera_controls,
                text="● Start Recording",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=Config.get_color("danger"),
                hover_color="#D32F2F",
                height=36,
                width=140,
                corner_radius=8,
                state="disabled",
                command=self.toggle_recording
            )
            self.btn_start_recording.pack(side="left")
            
            right_panel = ctk.CTkFrame(content, fg_color=Config.get_color("bg_element"), corner_radius=12)
            right_panel.pack(side="right", fill="both", expand=True)
            
            right_content = ctk.CTkFrame(right_panel, fg_color="transparent")
            right_content.pack(fill="both", expand=True, padx=15, pady=15)
            
            folder_section = ctk.CTkFrame(right_content, fg_color="transparent")
            folder_section.pack(fill="x", pady=(0, 15))
            
            folder_title = ctk.CTkFrame(folder_section, fg_color="transparent")
            folder_title.pack(anchor="w")
            
            ctk.CTkLabel(
                folder_title,
                text="📁",
                font=ctk.CTkFont(size=16),
                text_color=Config.get_color("accent_alt")
            ).pack(side="left", padx=(0, 5))
            
            ctk.CTkLabel(
                folder_title,
                text="Folder Penyimpanan",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            folder_frame = ctk.CTkFrame(folder_section, fg_color="transparent")
            folder_frame.pack(fill="x", pady=(5, 0))
            
            self.folder_label = ctk.CTkLabel(
                folder_frame,
                text=self.video_folder,
                font=ctk.CTkFont(size=12),
                text_color=Config.get_color("text_secondary"),
                anchor="w",
                height=36,
                fg_color=Config.get_color("bg_dark"),
                corner_radius=8,
                padx=10
            )
            self.folder_label.pack(side="left", fill="x", expand=True, padx=(0, 10))
            
            self.btn_browse_folder = ctk.CTkButton(
                folder_frame,
                text="Browse",
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color=Config.get_color("accent"),
                hover_color="#0071E3",
                height=36,
                width=80,
                corner_radius=8,
                command=self.pilih_folder
            )
            self.btn_browse_folder.pack(side="right")
            
            format_section = ctk.CTkFrame(right_content, fg_color="transparent")
            format_section.pack(fill="x", pady=(0, 15))
            
            format_title = ctk.CTkFrame(format_section, fg_color="transparent")
            format_title.pack(anchor="w")
            
            ctk.CTkLabel(
                format_title,
                text="🎬",
                font=ctk.CTkFont(size=16),
                text_color=Config.get_color("accent_alt")
            ).pack(side="left", padx=(0, 5))
            
            ctk.CTkLabel(
                format_title,
                text="Format Video",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            format_frame = ctk.CTkFrame(format_section, fg_color="transparent")
            format_frame.pack(fill="x", pady=(5, 0))
            
            self.format_var = ctk.StringVar(value="H.264 (MP4) - Recommended")
            
            format_options = [
                "H.264 (MP4) - Recommended",
                "HEVC (MP4) - Paling Ramping",
                "AVI (MJPEG) - Kompatible",
                "WebM (VP9) - Ringan",
            ]
            
            self.format_menu = ctk.CTkOptionMenu(
                format_frame,
                values=format_options,
                variable=self.format_var,
                fg_color=Config.get_color("bg_dark"),
                button_color=Config.get_color("accent_alt"),
                dropdown_fg_color=Config.get_color("bg_secondary"),
                font=ctk.CTkFont(size=12)
            )
            self.format_menu.pack(fill="x")
            
            format_info = ctk.CTkLabel(
                format_section,
                text="H.264: Ukuran kecil, kualitas baik, kompatible",
                font=ctk.CTkFont(size=11),
                text_color=Config.get_color("text_secondary")
            )
            format_info.pack(anchor="w", pady=(5, 0))
            
            scan_section = ctk.CTkFrame(right_content, fg_color="transparent")
            scan_section.pack(fill="x", pady=(0, 15))
            
            scan_title = ctk.CTkFrame(scan_section, fg_color="transparent")
            scan_title.pack(anchor="w")
            
            ctk.CTkLabel(
                scan_title,
                text="1️⃣",
                font=ctk.CTkFont(size=16),
                text_color=Config.get_color("accent_alt")
            ).pack(side="left", padx=(0, 5))
            
            ctk.CTkLabel(
                scan_title,
                text="Scan Resi",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            resi_frame = ctk.CTkFrame(scan_section, fg_color="transparent")
            resi_frame.pack(fill="x", pady=(5, 0))
            
            self.entry_resi_video = ctk.CTkEntry(
                resi_frame,
                placeholder_text="Scan Resi Disini...",
                height=44,
                font=ctk.CTkFont(size=14, weight="bold"),
                fg_color=Config.get_color("bg_dark"),
                border_width=0,
                corner_radius=8
            )
            self.entry_resi_video.pack(side="left", fill="x", expand=True, padx=(0, 10))
            self.entry_resi_video.bind("<Return>", self.proses_scan_resi_video)
            
            self.btn_scan = ctk.CTkButton(
                resi_frame,
                text="Scan",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=Config.get_color("accent"),
                hover_color="#0071E3",
                height=44,
                width=80,
                corner_radius=8,
                command=self.proses_scan_resi_manual
            )
            self.btn_scan.pack(side="right")
            
            info_section = ctk.CTkFrame(right_content, fg_color="transparent")
            info_section.pack(fill="x", pady=(0, 15))
            
            info_title = ctk.CTkFrame(info_section, fg_color="transparent")
            info_title.pack(anchor="w")
            
            ctk.CTkLabel(
                info_title,
                text="2️⃣",
                font=ctk.CTkFont(size=16),
                text_color=Config.get_color("accent_alt")
            ).pack(side="left", padx=(0, 5))
            
            ctk.CTkLabel(
                info_title,
                text="Informasi Packing",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            self.resi_info_card = ctk.CTkFrame(
                info_section,
                fg_color=Config.get_color("bg_dark"),
                corner_radius=8,
                height=80
            )
            self.resi_info_card.pack(fill="x", pady=(10, 0))
            self.resi_info_card.pack_propagate(False)
            
            self.resi_info_label = ctk.CTkLabel(
                self.resi_info_card,
                text="Belum ada resi di-scan",
                font=ctk.CTkFont(size=14),
                text_color=Config.get_color("text_secondary")
            )
            self.resi_info_label.pack(expand=True)
            
            status_section = ctk.CTkFrame(right_content, fg_color="transparent")
            status_section.pack(fill="x", pady=(0, 15))
            
            status_title = ctk.CTkFrame(status_section, fg_color="transparent")
            status_title.pack(anchor="w")
            
            ctk.CTkLabel(
                status_title,
                text="3️⃣",
                font=ctk.CTkFont(size=16),
                text_color=Config.get_color("accent_alt")
            ).pack(side="left", padx=(0, 5))
            
            ctk.CTkLabel(
                status_title,
                text="Status Rekaman",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            self.status_frame = ctk.CTkFrame(
                status_section,
                fg_color=Config.get_color("bg_dark"),
                corner_radius=8,
                height=60
            )
            self.status_frame.pack(fill="x", pady=(10, 0))
            self.status_frame.pack_propagate(False)
            
            status_inner = ctk.CTkFrame(self.status_frame, fg_color="transparent")
            status_inner.pack(expand=True)
            
            self.status_indicator = ctk.CTkLabel(
                status_inner,
                text="●",
                font=ctk.CTkFont(size=20),
                text_color=Config.get_color("text_secondary")
            )
            self.status_indicator.pack(side="left", padx=(0, 10))
            
            self.status_text = ctk.CTkLabel(
                status_inner,
                text="Ready",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=Config.get_color("text_secondary")
            )
            self.status_text.pack(side="left")
            
            self.timer_label = ctk.CTkLabel(
                self.status_frame,
                text="00:00:00",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=Config.get_color("text_primary")
            )
            self.timer_label.pack(side="right", padx=15)
            
            self.timer_value = 0
            self.timer_running = False
            
            self.recording_info = ctk.CTkLabel(
                status_section,
                text="",
                font=ctk.CTkFont(size=12),
                text_color=Config.get_color("text_secondary"),
                wraplength=250
            )
            self.recording_info.pack(anchor="w", pady=(5, 0))
        except Exception as e:
            self.logger.error(f"Setup UI error: {e}")
    
    def get_video_settings(self):
        format_choice = self.format_var.get()
        
        settings = {
            "H.264 (MP4) - Recommended": {
                "codec": "avc1",
                "ext": ".mp4",
                "fourcc": cv2.VideoWriter_fourcc(*'avc1'),
                "fps": 15,
                "width": 480,
                "height": 360,
                "desc": "H.264 - Ukuran kecil, kualitas baik"
            },
            "HEVC (MP4) - Paling Ramping": {
                "codec": "hevc",
                "ext": ".mp4",
                "fourcc": cv2.VideoWriter_fourcc(*'hevc'),
                "fps": 12,
                "width": 426,
                "height": 240,
                "desc": "HEVC - Ukuran sangat kecil, butuh codec"
            },
            "AVI (MJPEG) - Kompatible": {
                "codec": "MJPG",
                "ext": ".avi",
                "fourcc": cv2.VideoWriter_fourcc(*'MJPG'),
                "fps": 20,
                "width": 640,
                "height": 480,
                "desc": "MJPEG - Ukuran besar, semua Windows bisa"
            },
            "WebM (VP9) - Ringan": {
                "codec": "VP90",
                "ext": ".webm",
                "fourcc": cv2.VideoWriter_fourcc(*'VP90'),
                "fps": 15,
                "width": 480,
                "height": 360,
                "desc": "VP9 - Ukuran kecil, untuk web"
            }
        }
        
        return settings.get(format_choice, settings["H.264 (MP4) - Recommended"])
    
    def toggle_camera(self):
        if not self.preview_active:
            try:
                self.camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if not self.camera.isOpened():
                    CustomDialog.show_error(self.window.window, "Tidak dapat mengakses kamera!")
                    return
                
                settings = self.get_video_settings()
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, settings["width"])
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, settings["height"])
                self.camera.set(cv2.CAP_PROP_FPS, settings["fps"])
                
                for _ in range(10):
                    self.camera.read()
                
                self.preview_active = True
                self.btn_start_camera.configure(
                    text="■ Stop Camera",
                    fg_color=Config.get_color("danger"),
                    hover_color="#D32F2F"
                )
                
                self.preview_thread = threading.Thread(target=self.update_preview, daemon=True)
                self.preview_thread.start()
                
            except Exception as e:
                CustomDialog.show_error(self.window.window, f"Gagal membuka kamera: {str(e)}")
        else:
            self.preview_active = False
            time.sleep(0.5)
            
            if self.camera:
                self.camera.release()
                self.camera = None
            
            self.btn_start_camera.configure(
                text="▶ Start Camera",
                fg_color=Config.get_color("accent"),
                hover_color="#0071E3"
            )
            self.preview_label.configure(image=None, text="Camera Off")
            
            if self.is_recording:
                self.toggle_recording()
            self.btn_start_recording.configure(state="disabled")
    
    def update_preview(self):
        settings = self.get_video_settings()
        preview_width = 400
        preview_height = 300
        
        while self.preview_active and self.camera:
            try:
                ret, frame = self.camera.read()
                if ret:
                    frame = cv2.resize(frame, (preview_width, preview_height))
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(frame)
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(preview_width, preview_height))
                    self.preview_label.configure(image=ctk_img, text="")
                else:
                    break
                time.sleep(0.03)
            except:
                break
        
        if not self.preview_active:
            self.preview_label.configure(image=None, text="Camera Off")
    
    def proses_scan_resi_video(self, event=None):
        try:
            resi = self.entry_resi_video.get().strip()
            if not resi:
                return
            
            if not Validator.resi(resi):
                CustomDialog.show_warning(self.window.window, "Format resi tidak valid!")
                return
            
            if any(len(r) > 2 and r[2] == resi for r in self.parent.active_data):
                winsound.Beep(400, 600)
                CustomDialog.show_warning(self.window.window, "Resi ini sudah ada di scan history!")
                self.entry_resi_video.delete(0, 'end')
                return
            
            self.current_resi = resi
            
            self.resi_info_label.configure(
                text=f"Resi: {resi}",
                text_color=Config.get_color("success")
            )
            
            if self.preview_active:
                self.btn_start_recording.configure(state="normal")
            
            if self.callback_resi_scan:
                self.callback_resi_scan(resi)
            
            self.entry_resi_video.delete(0, 'end')
            winsound.Beep(1200, 200)
        except Exception as e:
            self.logger.error(f"Proses scan resi video error: {e}")
    
    def proses_scan_resi_manual(self):
        self.proses_scan_resi_video()
    
    @log_activity("video_recording")
    def toggle_recording(self):
        if not self.is_recording:
            if not self.current_resi:
                CustomDialog.show_warning(self.window.window, "Scan resi terlebih dahulu!")
                return
            
            if not self.camera:
                CustomDialog.show_warning(self.window.window, "Start camera terlebih dahulu!")
                return
            
            settings = self.get_video_settings()
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{self.current_resi}_{timestamp}{settings['ext']}"
            filepath = os.path.join(self.video_folder, filename)
            
            try:
                self.video_writer = cv2.VideoWriter(
                    filepath, 
                    settings["fourcc"], 
                    settings["fps"], 
                    (settings["width"], settings["height"])
                )
                
                if not self.video_writer.isOpened():
                    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                    filepath = filepath.replace(settings['ext'], '.avi')
                    self.video_writer = cv2.VideoWriter(filepath, fourcc, 15, (480, 360))
            except:
                try:
                    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                    filepath = os.path.join(self.video_folder, f"{self.current_resi}_{timestamp}.avi")
                    self.video_writer = cv2.VideoWriter(filepath, fourcc, 15, (480, 360))
                except:
                    CustomDialog.show_error(self.window.window, "Tidak dapat membuat file video!")
                    return
            
            if not self.video_writer or not self.video_writer.isOpened():
                CustomDialog.show_error(self.window.window, "Tidak dapat membuat file video!")
                return
            
            self.is_recording = True
            self.frame_count = 0
            self.current_filepath = filepath
            
            self.btn_start_recording.configure(
                text="■ Stop Recording",
                fg_color=Config.get_color("danger"),
                hover_color="#D32F2F"
            )
            
            self.status_indicator.configure(text_color=Config.get_color("danger"))
            self.status_text.configure(text="Recording...", text_color=Config.get_color("danger"))
            
            self.recording_info.configure(
                text=f"File: {os.path.basename(filepath)}"
            )
            
            self.timer_value = 0
            self.timer_running = True
            self.update_timer()
            
            self.recording_thread = threading.Thread(target=self.record_video, args=(settings,), daemon=True)
            self.recording_thread.start()
            
        else:
            self.is_recording = False
            self.timer_running = False
            
            if self.recording_thread and self.recording_thread.is_alive():
                self.recording_thread.join(timeout=2.0)
            
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None
            
            self.btn_start_recording.configure(
                text="● Start Recording",
                fg_color=Config.get_color("danger"),
                hover_color="#D32F2F",
                state="disabled"
            )
            
            if hasattr(self, 'current_filepath') and self.current_filepath:
                if os.path.exists(self.current_filepath):
                    file_size = os.path.getsize(self.current_filepath)
                    file_size_mb = file_size / (1024 * 1024)
                    
                    if file_size > 1024:
                        self.status_indicator.configure(text_color=Config.get_color("success"))
                        self.status_text.configure(text="Recording saved!", text_color=Config.get_color("success"))
                        self.recording_info.configure(
                            text=f"✓ Video tersimpan: {os.path.basename(self.current_filepath)}\n"
                                 f"Ukuran: {file_size_mb:.2f} MB\n"
                                 f"Durasi: {self.format_time(self.timer_value)}"
                        )
                        winsound.Beep(800, 300)
                        CustomDialog.show_info(self.window.window, f"Video tersimpan:\n{os.path.basename(self.current_filepath)}")
                    else:
                        self.status_indicator.configure(text_color=Config.get_color("warning"))
                        self.status_text.configure(text="File terlalu kecil", text_color=Config.get_color("warning"))
                        self.recording_info.configure(text="⚠ Video gagal tersimpan - rekam minimal 5 detik")
                else:
                    self.status_indicator.configure(text_color=Config.get_color("danger"))
                    self.status_text.configure(text="Error: File tidak tersimpan!", text_color=Config.get_color("danger"))
                    self.recording_info.configure(text="❌ Video gagal tersimpan, coba lagi")
                    winsound.Beep(400, 600)
                    CustomDialog.show_error(self.window.window, "Video gagal tersimpan!")
            
            self.current_resi = None
            self.resi_info_label.configure(
                text="Scan resi untuk rekaman baru",
                text_color=Config.get_color("text_secondary")
            )
            self.current_filepath = None
    
    def format_time(self, seconds):
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"
    
    def record_video(self, settings):
        fps = settings["fps"]
        target_width = settings["width"]
        target_height = settings["height"]
        frame_time = 1.0 / fps
        last_frame_time = time.time()
        
        while self.is_recording and self.camera and self.video_writer:
            try:
                current_time = time.time()
                if current_time - last_frame_time >= frame_time:
                    ret, frame = self.camera.read()
                    if ret:
                        frame = cv2.resize(frame, (target_width, target_height))
                        self.video_writer.write(frame)
                        self.frame_count += 1
                        last_frame_time = current_time
                else:
                    time.sleep(0.001)
            except:
                break
    
    def update_timer(self):
        if self.timer_running:
            self.timer_value += 1
            hours = self.timer_value // 3600
            minutes = (self.timer_value % 3600) // 60
            seconds = self.timer_value % 60
            self.timer_label.configure(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            self.window.window.after(1000, self.update_timer)

# ============ EDIT EKSPEDISI WINDOW ============
class EditExpedisiWindow:
    def __init__(self, parent):
        self.parent = parent
        self.window = ModernWindow(
            parent,
            title="Edit Ekspedisi - iScan Pro",
            width=800,
            height=600
        )
        self.db = Database()
        self.logger = logging.getLogger("EditExpedisi")
        self.setup_ui()
        self.load_expedisi()
    
    def setup_ui(self):
        try:
            container = self.window.main_container
            
            header = ctk.CTkFrame(container, fg_color="transparent")
            header.pack(fill="x", padx=20, pady=(20, 10))
            
            title_frame = ctk.CTkFrame(header, fg_color="transparent")
            title_frame.pack(side="left")
            
            ctk.CTkLabel(
                title_frame,
                text=Icons.edit,
                font=ctk.CTkFont(size=24),
                text_color=Config.get_color("accent")
            ).pack(side="left", padx=(0, 5))
            
            ctk.CTkLabel(
                title_frame,
                text="Edit Ekspedisi",
                font=self.parent.font_title_2,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            ctk.CTkButton(
                header,
                text=Icons.save + " Tambah Ekspedisi",
                font=self.parent.font_button,
                fg_color=Config.get_color("accent"),
                hover_color="#0071E3",
                height=36,
                width=180,
                corner_radius=18,
                command=self.tambah_ekspedisi
            ).pack(side="right")
            
            table_frame = ctk.CTkFrame(container, fg_color=Config.get_color("bg_tertiary"), corner_radius=16)
            table_frame.pack(fill="both", expand=True, padx=20, pady=(10, 20))
            
            self.scroll_frame = SafeScrollableFrame(
                table_frame,
                orientation="vertical"
            )
            self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)
        except Exception as e:
            self.logger.error(f"Setup UI error: {e}")
    
    def load_expedisi(self):
        try:
            self.scroll_frame.clear()
            
            cursor = self.db.execute("SELECT id, nama, prefix, keterangan FROM ekspedisi ORDER BY nama")
            expeditions = cursor.fetchall()
            
            if not expeditions:
                self.create_default_expedisi()
                self.load_expedisi()
                return
            
            for exp in expeditions:
                self.create_expedisi_card(exp)
        except Exception as e:
            self.logger.error(f"Load expedisi error: {e}")
    
    def create_default_expedisi(self):
        defaults = [
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
            ("LAINNYA", "", "Ekspedisi lain")
        ]
        
        for nama, prefix, ket in defaults:
            try:
                self.db.execute(
                    "INSERT OR IGNORE INTO ekspedisi (nama, prefix, keterangan) VALUES (?, ?, ?)",
                    (nama, prefix, ket)
                )
            except:
                pass
    
    def create_expedisi_card(self, exp_data):
        try:
            exp_id, nama, prefix, keterangan = exp_data
            
            card = ctk.CTkFrame(
                self.scroll_frame.scrollable_frame,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=12,
                height=100,
                border_width=0.5,
                border_color=Config.get_color("border")
            )
            card.pack(fill="x", pady=5)
            card.pack_propagate(False)
            
            content = ctk.CTkFrame(card, fg_color="transparent")
            content.pack(fill="both", expand=True, padx=15, pady=10)
            
            info_frame = ctk.CTkFrame(content, fg_color="transparent")
            info_frame.pack(side="left", fill="both", expand=True)
            
            ctk.CTkLabel(
                info_frame,
                text=nama,
                font=self.parent.font_headline,
                text_color=Config.get_color("text_primary")
            ).pack(anchor="w")
            
            ctk.CTkLabel(
                info_frame,
                text=f"Prefix: {prefix if prefix else '(kosong)'}",
                font=self.parent.font_caption,
                text_color=Config.get_color("text_secondary")
            ).pack(anchor="w", pady=(2, 0))
            
            ctk.CTkLabel(
                info_frame,
                text=keterangan if keterangan else "",
                font=self.parent.font_caption,
                text_color=Config.get_color("text_tertiary")
            ).pack(anchor="w", pady=(2, 0))
            
            action_frame = ctk.CTkFrame(content, fg_color="transparent")
            action_frame.pack(side="right")
            
            ctk.CTkButton(
                action_frame,
                text="Edit",
                font=self.parent.font_button,
                fg_color=Config.get_color("accent_alt"),
                hover_color="#7A7878",
                width=60,
                height=30,
                corner_radius=15,
                command=lambda: self.edit_ekspedisi(exp_id, nama, prefix, keterangan)
            ).pack(side="left", padx=2)
            
            if nama != "LAINNYA":
                ctk.CTkButton(
                    action_frame,
                    text="Hapus",
                    font=self.parent.font_button,
                    fg_color=Config.get_color("danger"),
                    hover_color="#D70015",
                    width=60,
                    height=30,
                    corner_radius=15,
                    command=lambda: self.hapus_ekspedisi(exp_id, nama)
                ).pack(side="left", padx=2)
        except Exception as e:
            self.logger.error(f"Create expedisi card error: {e}")
    
    @log_activity("tambah_ekspedisi")
    def tambah_ekspedisi(self):
        try:
            dialog = ctk.CTkToplevel(self.window.window)
            dialog.title("Tambah Ekspedisi")
            dialog.geometry("400x450")
            dialog.configure(fg_color=Config.get_color("bg_primary"))
            dialog.attributes("-topmost", True)
            dialog.transient(self.window.window)
            dialog.grab_set()
            
            dialog.update_idletasks()
            x = self.window.window.winfo_x() + (self.window.winfo_width() // 2) - (400 // 2)
            y = self.window.window.winfo_y() + (self.window.winfo_height() // 2) - (450 // 2)
            dialog.geometry(f'+{x}+{y}')
            
            container = ctk.CTkFrame(dialog, fg_color=Config.get_color("bg_secondary"), corner_radius=16)
            container.pack(fill="both", expand=True, padx=20, pady=20)
            
            ctk.CTkLabel(
                container,
                text="Tambah Ekspedisi Baru",
                font=self.parent.font_title_3,
                text_color=Config.get_color("text_primary")
            ).pack(pady=(20, 15))
            
            form_frame = ctk.CTkFrame(container, fg_color="transparent")
            form_frame.pack(fill="x", padx=30, pady=10)
            
            ctk.CTkLabel(
                form_frame,
                text="Nama Ekspedisi:",
                font=self.parent.font_body,
                text_color=Config.get_color("text_secondary")
            ).pack(anchor="w", pady=(5, 2))
            
            entry_nama = ctk.CTkEntry(
                form_frame,
                height=35,
                font=self.parent.font_body,
                fg_color=Config.get_color("bg_tertiary"),
                border_width=0,
                corner_radius=8
            )
            entry_nama.pack(fill="x", pady=(0, 10))
            
            ctk.CTkLabel(
                form_frame,
                text="Prefix/Ciri Khas (pisahkan dengan koma):",
                font=self.parent.font_body,
                text_color=Config.get_color("text_secondary")
            ).pack(anchor="w", pady=(5, 2))
            
            entry_prefix = ctk.CTkEntry(
                form_frame,
                height=35,
                font=self.parent.font_body,
                fg_color=Config.get_color("bg_tertiary"),
                border_width=0,
                corner_radius=8,
                placeholder_text="Contoh: SPXID,JX,JP"
            )
            entry_prefix.pack(fill="x", pady=(0, 10))
            
            ctk.CTkLabel(
                form_frame,
                text="Keterangan (opsional):",
                font=self.parent.font_body,
                text_color=Config.get_color("text_secondary")
            ).pack(anchor="w", pady=(5, 2))
            
            entry_keterangan = ctk.CTkEntry(
                form_frame,
                height=35,
                font=self.parent.font_body,
                fg_color=Config.get_color("bg_tertiary"),
                border_width=0,
                corner_radius=8
            )
            entry_keterangan.pack(fill="x", pady=(0, 10))
            
            button_frame = ctk.CTkFrame(container, fg_color="transparent")
            button_frame.pack(pady=20, side="bottom")
            
            def simpan():
                nama = entry_nama.get().strip()
                prefix = entry_prefix.get().strip()
                keterangan = entry_keterangan.get().strip()
                
                if not nama:
                    CustomDialog.show_warning(dialog, "Nama ekspedisi harus diisi!")
                    return
                
                try:
                    self.db.execute(
                        "INSERT INTO ekspedisi (nama, prefix, keterangan) VALUES (?, ?, ?)",
                        (nama, prefix, keterangan)
                    )
                    self.parent.expedition_cache.invalidate()
                    dialog.destroy()
                    self.load_expedisi()
                    Toast.show(self.window.window, "Ekspedisi ditambahkan", "success")
                except Exception as e:
                    CustomDialog.show_error(dialog, f"Gagal menambah: {str(e)}")
            
            btn_save = ctk.CTkButton(
                button_frame,
                text="💾 Simpan",
                font=self.parent.font_button,
                fg_color=Config.get_color("success"),
                hover_color="#28A745",
                width=120,
                height=40,
                corner_radius=20,
                command=simpan
            )
            btn_save.pack(side="left", padx=10)
            
            btn_cancel = ctk.CTkButton(
                button_frame,
                text="✕ Batal",
                font=self.parent.font_button,
                fg_color=Config.get_color("danger"),
                hover_color="#D70015",
                width=120,
                height=40,
                corner_radius=20,
                command=dialog.destroy
            )
            btn_cancel.pack(side="left", padx=10)
        except Exception as e:
            self.logger.error(f"Tambah ekspedisi error: {e}")
    
    @log_activity("edit_ekspedisi")
    def edit_ekspedisi(self, exp_id, nama_lama, prefix_lama, keterangan_lama):
        try:
            dialog = ctk.CTkToplevel(self.window.window)
            dialog.title("Edit Ekspedisi")
            dialog.geometry("400x450")
            dialog.configure(fg_color=Config.get_color("bg_primary"))
            dialog.attributes("-topmost", True)
            dialog.transient(self.window.window)
            dialog.grab_set()
            
            dialog.update_idletasks()
            x = self.window.window.winfo_x() + (self.window.winfo_width() // 2) - (400 // 2)
            y = self.window.window.winfo_y() + (self.window.winfo_height() // 2) - (450 // 2)
            dialog.geometry(f'+{x}+{y}')
            
            container = ctk.CTkFrame(dialog, fg_color=Config.get_color("bg_secondary"), corner_radius=16)
            container.pack(fill="both", expand=True, padx=20, pady=20)
            
            ctk.CTkLabel(
                container,
                text="Edit Ekspedisi",
                font=self.parent.font_title_3,
                text_color=Config.get_color("text_primary")
            ).pack(pady=(20, 15))
            
            form_frame = ctk.CTkFrame(container, fg_color="transparent")
            form_frame.pack(fill="x", padx=30, pady=10)
            
            ctk.CTkLabel(
                form_frame,
                text="Nama Ekspedisi:",
                font=self.parent.font_body,
                text_color=Config.get_color("text_secondary")
            ).pack(anchor="w", pady=(5, 2))
            
            entry_nama = ctk.CTkEntry(
                form_frame,
                height=35,
                font=self.parent.font_body,
                fg_color=Config.get_color("bg_tertiary"),
                border_width=0,
                corner_radius=8
            )
            entry_nama.insert(0, nama_lama)
            entry_nama.pack(fill="x", pady=(0, 10))
            
            ctk.CTkLabel(
                form_frame,
                text="Prefix/Ciri Khas (pisahkan dengan koma):",
                font=self.parent.font_body,
                text_color=Config.get_color("text_secondary")
            ).pack(anchor="w", pady=(5, 2))
            
            entry_prefix = ctk.CTkEntry(
                form_frame,
                height=35,
                font=self.parent.font_body,
                fg_color=Config.get_color("bg_tertiary"),
                border_width=0,
                corner_radius=8
            )
            entry_prefix.insert(0, prefix_lama)
            entry_prefix.pack(fill="x", pady=(0, 10))
            
            ctk.CTkLabel(
                form_frame,
                text="Keterangan (opsional):",
                font=self.parent.font_body,
                text_color=Config.get_color("text_secondary")
            ).pack(anchor="w", pady=(5, 2))
            
            entry_keterangan = ctk.CTkEntry(
                form_frame,
                height=35,
                font=self.parent.font_body,
                fg_color=Config.get_color("bg_tertiary"),
                border_width=0,
                corner_radius=8
            )
            entry_keterangan.insert(0, keterangan_lama)
            entry_keterangan.pack(fill="x", pady=(0, 10))
            
            button_frame = ctk.CTkFrame(container, fg_color="transparent")
            button_frame.pack(pady=20, side="bottom")
            
            def simpan():
                nama = entry_nama.get().strip()
                prefix = entry_prefix.get().strip()
                keterangan = entry_keterangan.get().strip()
                
                if not nama:
                    CustomDialog.show_warning(dialog, "Nama ekspedisi harus diisi!")
                    return
                
                try:
                    self.db.execute(
                        "UPDATE ekspedisi SET nama=?, prefix=?, keterangan=? WHERE id=?",
                        (nama, prefix, keterangan, exp_id)
                    )
                    self.parent.expedition_cache.invalidate()
                    dialog.destroy()
                    self.load_expedisi()
                    Toast.show(self.window.window, "Ekspedisi diupdate", "success")
                except Exception as e:
                    CustomDialog.show_error(dialog, f"Gagal update: {str(e)}")
            
            btn_save = ctk.CTkButton(
                button_frame,
                text="💾 Simpan",
                font=self.parent.font_button,
                fg_color=Config.get_color("success"),
                hover_color="#28A745",
                width=120,
                height=40,
                corner_radius=20,
                command=simpan
            )
            btn_save.pack(side="left", padx=10)
            
            btn_cancel = ctk.CTkButton(
                button_frame,
                text="✕ Batal",
                font=self.parent.font_button,
                fg_color=Config.get_color("danger"),
                hover_color="#D70015",
                width=120,
                height=40,
                corner_radius=20,
                command=dialog.destroy
            )
            btn_cancel.pack(side="left", padx=10)
        except Exception as e:
            self.logger.error(f"Edit ekspedisi error: {e}")
    
    @log_activity("hapus_ekspedisi")
    def hapus_ekspedisi(self, exp_id, nama):
        if CustomDialog.show_question(self.window.window, f"Hapus ekspedisi '{nama}'?"):
            try:
                self.db.execute("DELETE FROM ekspedisi WHERE id=?", (exp_id,))
                self.parent.expedition_cache.invalidate()
                self.load_expedisi()
                Toast.show(self.window.window, "Ekspedisi dihapus", "success")
            except Exception as e:
                CustomDialog.show_error(self.window.window, f"Gagal hapus: {str(e)}")

# ============ PENDING REPORT WINDOW ============
class PendingReportWindow:
    def __init__(self, parent, pending_data):
        self.parent = parent
        self.pending_data = pending_data
        self.logger = logging.getLogger("PendingReport")
        self.window = ModernWindow(
            parent,
            title="Pending Report - iScan Pro",
            width=600,
            height=500
        )
        self.setup_ui()
    
    def setup_ui(self):
        try:
            container = self.window.main_container
            
            header = ctk.CTkFrame(container, fg_color="transparent")
            header.pack(fill="x", padx=20, pady=(20, 10))
            
            title_frame = ctk.CTkFrame(header, fg_color="transparent")
            title_frame.pack(side="left")
            
            ctk.CTkLabel(
                title_frame,
                text=Icons.pending,
                font=ctk.CTkFont(size=24),
                text_color=Config.get_color("warning")
            ).pack(side="left", padx=(0, 5))
            
            ctk.CTkLabel(
                title_frame,
                text="Pending Report",
                font=self.parent.font_title_2,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            ctk.CTkLabel(
                header,
                text=f"Total: {len(self.pending_data)}",
                font=self.parent.font_headline,
                text_color=Config.get_color("warning")
            ).pack(side="right")
            
            table_frame = ctk.CTkFrame(container, fg_color=Config.get_color("bg_tertiary"), corner_radius=16)
            table_frame.pack(fill="both", expand=True, padx=20, pady=(10, 20))
            
            scroll = SafeScrollableFrame(
                table_frame,
                orientation="vertical"
            )
            scroll.pack(fill="both", expand=True, padx=10, pady=10)
            
            if self.pending_data:
                header_frame = ctk.CTkFrame(scroll.scrollable_frame, fg_color=Config.get_color("bg_secondary"), height=40, corner_radius=8)
                header_frame.pack(fill="x", pady=(0, 5))
                header_frame.pack_propagate(False)
                
                ctk.CTkLabel(
                    header_frame,
                    text="No",
                    font=self.parent.font_headline,
                    text_color=Config.get_color("accent"),
                    width=50
                ).pack(side="left", padx=10)
                
                ctk.CTkLabel(
                    header_frame,
                    text="Waktu",
                    font=self.parent.font_headline,
                    text_color=Config.get_color("accent"),
                    width=80
                ).pack(side="left")
                
                ctk.CTkLabel(
                    header_frame,
                    text="Nomor Resi",
                    font=self.parent.font_headline,
                    text_color=Config.get_color("accent"),
                    width=200
                ).pack(side="left")
                
                ctk.CTkLabel(
                    header_frame,
                    text="Ekspedisi",
                    font=self.parent.font_headline,
                    text_color=Config.get_color("accent"),
                    width=150
                ).pack(side="left")
                
                for i, row in enumerate(self.pending_data, 1):
                    row_frame = ctk.CTkFrame(scroll.scrollable_frame, fg_color=Config.get_color("bg_secondary") if i%2==0 else Config.get_color("bg_tertiary"), height=35, corner_radius=6)
                    row_frame.pack(fill="x", pady=1)
                    row_frame.pack_propagate(False)
                    
                    ctk.CTkLabel(
                        row_frame,
                        text=str(i),
                        font=self.parent.font_caption,
                        text_color=Config.get_color("text_secondary"),
                        width=50
                    ).pack(side="left", padx=10)
                    
                    ctk.CTkLabel(
                        row_frame,
                        text=row[0] if len(row) > 0 else "",
                        font=self.parent.font_caption,
                        text_color=Config.get_color("text_primary"),
                        width=80
                    ).pack(side="left")
                    
                    ctk.CTkLabel(
                        row_frame,
                        text=row[2] if len(row) > 2 else "",
                        font=self.parent.font_caption,
                        text_color=Config.get_color("warning"),
                        width=200
                    ).pack(side="left")
                    
                    ctk.CTkLabel(
                        row_frame,
                        text=row[3] if len(row) > 3 else "",
                        font=self.parent.font_caption,
                        text_color=Config.get_color("text_secondary"),
                        width=150
                    ).pack(side="left")
            else:
                show_empty_state(scroll, "Tidak ada data pending", "", Icons.pending)
        except Exception as e:
            self.logger.error(f"Setup UI error: {e}")

# ============ EXPEDITION DETAIL WINDOW (FIXED - DATA LANGSUNG MUNCUL) ============
class ExpeditionDetailWindow:
    def __init__(self, parent, ekspedisi_nama, active_data, header, folder_handover, get_stored_stores_func):
        self.parent = parent
        self.ekspedisi_nama = ekspedisi_nama
        self.active_data = active_data
        self.header = header
        self.folder_handover = folder_handover
        self.get_stored_stores = get_stored_stores_func
        self.logger = logging.getLogger("ExpeditionDetail")
        
        # Filter data untuk expedisi ini
        self.filtered_data = [r for r in active_data if len(r) > 3 and r[3] == ekspedisi_nama]
        self.current_filtered_data = self.filtered_data.copy()  # LANGSUNG SET DENGAN SEMUA DATA
        
        self.window = ModernWindow(
            parent,
            title=f"{ekspedisi_nama} - Details",
            width=1000,
            height=700
        )
        
        self._update_scheduled = False
        self._filter_job = None
        
        # UI Elements
        self.menu_filter = None
        self.filter_toko_var = None
        self.start_hour = None
        self.start_minute = None
        self.end_hour = None
        self.end_minute = None
        self.summary_frame = None
        self.canvas_history = None
        
        # Setup UI
        self.setup_ui()
        
        # Tampilkan data LANGSUNG (tanpa nunggu filter)
        self.after(100, self._display_all_data)
    
    def after(self, ms, func):
        """Helper untuk after"""
        return self.window.window.after(ms, func)
    
    def after_cancel(self, job):
        """Helper untuk after_cancel"""
        try:
            self.window.window.after_cancel(job)
        except:
            pass
    
    def _display_all_data(self) -> None:
        """Tampilkan semua data langsung"""
        try:
            self._update_summary(self.current_filtered_data)
            self.canvas_history.set_data(self.current_filtered_data)
        except Exception as e:
            self.logger.error(f"Display all data error: {e}")
    
    def setup_ui(self):
        try:
            container = self.window.main_container
            
            # SIDEBAR
            self.sidebar = ctk.CTkFrame(
                self.main_container,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=20,
                width=220,
                border_width=0.5,
                border_color=Config.get_color("border")
            )
            self.sidebar.pack(side="left", fill="y", padx=(0, 20))
            self.sidebar.pack_propagate(False)
            
            # Logo
            logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
            logo_frame.pack(fill="x", padx=15, pady=(30, 40))
            
            logo_inner = ctk.CTkFrame(logo_frame, fg_color="transparent")
            logo_inner.pack(anchor="w")
            
            ctk.CTkLabel(
                logo_inner,
                text="iScan",
                font=self.font_large_title,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            ctk.CTkLabel(
                logo_inner,
                text="Pro",
                font=self.font_title_2,
                text_color=Config.get_color("accent")
            ).pack(side="left", padx=(5, 0))
            
            ctk.CTkLabel(
                logo_inner,
                text="By MMA",
                font=self.font_caption,
                text_color=Config.get_color("text_secondary")
            ).pack(side="left", padx=(5, 0))
            
            # Menu items
            menu_items = [
                (Icons.dashboard, "Dashboard", self.show_dashboard),
                (Icons.scan, "Scan", self.focus_scan),
                (Icons.reports, "Reports", self.show_reports_menu),
                (Icons.video, "Video Packing", self.buka_video_packing),
                (Icons.edit, "Edit Ekspedisi", self.buka_edit_ekspedisi),
                (Icons.new_session, "New Session", self.mulai_baru_reset),
                (Icons.save, "Save to Archive", self.save_ke_arsip_excel),
                (Icons.archive, "Archive", self.buka_window_arsip),
            ]
            
            self.sidebar_buttons = []
            for icon, text, command in menu_items:
                btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
                btn_frame.pack(fill="x", padx=10, pady=2)
                
                ctk.CTkLabel(
                    btn_frame,
                    text=icon,
                    font=ctk.CTkFont(size=16),
                    text_color=Config.get_color("text_secondary"),
                    width=30
                ).pack(side="left")
                
                btn = ctk.CTkButton(
                    btn_frame,
                    text=text,
                    font=self.font_body,
                    fg_color="transparent",
                    hover_color=Config.get_color("menu_hover"),
                    anchor="w",
                    height=36,
                    corner_radius=8,
                    command=command,
                    text_color=Config.get_color("sidebar_text")
                )
                btn.pack(side="left", fill="x", expand=True)
                self.sidebar_buttons.append(btn)
            
            # Main content
            self.content = ctk.CTkFrame(self.main_container, fg_color="transparent")
            self.content.pack(side="right", fill="both", expand=True)
            
            # Header
            self.header_frame_ui = ctk.CTkFrame(self.content, fg_color="transparent", height=70)
            self.header_frame_ui.pack(fill="x", pady=(0, 20))
            self.header_frame_ui.pack_propagate(False)
            
            title_frame = ctk.CTkFrame(self.header_frame_ui, fg_color="transparent")
            title_frame.pack(side="left")
            
            ctk.CTkLabel(
                title_frame,
                text="Dashboard",
                font=self.font_title_1,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            # Right actions
            action_frame = ctk.CTkFrame(self.header_frame_ui, fg_color="transparent")
            action_frame.pack(side="right")
            
            self.theme_btn = ctk.CTkButton(
                action_frame,
                text="🌓",
                width=40,
                height=36,
                corner_radius=10,
                fg_color=Config.get_color("bg_tertiary"),
                hover_color=Config.get_color("menu_hover"),
                font=ctk.CTkFont(size=16, weight="bold"),
                command=self.toggle_theme
            )
            self.theme_btn.pack(side="right", padx=5)
            
            # Store selector
            store_frame = ctk.CTkFrame(action_frame, fg_color="transparent")
            store_frame.pack(side="left", padx=(0, 15))
            
            ctk.CTkLabel(
                store_frame,
                text=Icons.store,
                font=ctk.CTkFont(size=14),
                text_color=Config.get_color("text_secondary")
            ).pack(side="left", padx=(0, 5))
            
            self.toko_var = ctk.StringVar(value="Mitra Mulia Abadi")
            self.daftar_toko = self.get_stored_stores()
            
            self.toko_menu = ctk.CTkOptionMenu(
                store_frame,
                values=self.daftar_toko,
                variable=self.toko_var,
                width=180,
                height=36,
                corner_radius=10,
                fg_color=Config.get_color("bg_tertiary"),
                button_color=Config.get_color("accent_alt"),
                dropdown_fg_color=Config.get_color("bg_secondary"),
                font=self.font_body
            )
            self.toko_menu.pack(side="left")
            
            self.add_store_btn = ctk.CTkButton(
                store_frame,
                text="+",
                width=36,
                height=36,
                corner_radius=10,
                fg_color=Config.get_color("bg_tertiary"),
                hover_color=Config.get_color("menu_hover"),
                font=ctk.CTkFont(size=16, weight="bold"),
                command=self.tambah_toko_custom
            )
            self.add_store_btn.pack(side="left", padx=2)
            
            self.remove_store_btn = ctk.CTkButton(
                store_frame,
                text="−",
                width=36,
                height=36,
                corner_radius=10,
                fg_color=Config.get_color("bg_tertiary"),
                hover_color=Config.get_color("menu_hover"),
                font=ctk.CTkFont(size=16, weight="bold"),
                command=self.hapus_toko_window
            )
            self.remove_store_btn.pack(side="left", padx=2)
            
            self.retur_switch = ctk.CTkSwitch(
                action_frame,
                text="Mode Retur",
                variable=self.is_retur_mode,
                command=self.update_ui_mode,
                font=self.font_body,
                progress_color=Config.get_color("danger"),
                fg_color=Config.get_color("bg_tertiary"),
                switch_width=46,
                switch_height=24
            )
            self.retur_switch.pack(side="left")
            
            # SCAN CARD
            self.scan_card = ctk.CTkFrame(
                self.content,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=24,
                height=120,
                border_width=0.5,
                border_color=Config.get_color("accent")
            )
            self.scan_card.pack(fill="x", pady=(0, 25))
            self.scan_card.pack_propagate(False)
            
            scan_inner = ctk.CTkFrame(self.scan_card, fg_color="transparent")
            scan_inner.pack(fill="both", expand=True, padx=30, pady=25)
            
            ctk.CTkLabel(
                scan_inner,
                text=Icons.scan,
                font=ctk.CTkFont(size=28),
                text_color=Config.get_color("accent")
            ).pack(side="left", padx=(0, 15))
            
            self.entry_resi = ctk.CTkEntry(
                scan_inner,
                placeholder_text="Scan barcode atau ketik nomor resi",
                height=50,
                font=self.font_body,
                fg_color=Config.get_color("bg_tertiary"),
                border_width=0,
                corner_radius=12,
                placeholder_text_color=Config.get_color("text_tertiary")
            )
            self.entry_resi.pack(side="left", fill="x", expand=True)
            self.entry_resi.bind("<Return>", self.proses_scan_cepat)
            self.entry_resi.focus()
            
            # STATISTICS CARDS
            self.stats_container = ctk.CTkFrame(self.content, fg_color="transparent", height=80)
            self.stats_container.pack(fill="x", pady=(0, 25))
            self.stats_container.pack_propagate(False)
            
            self.stats_grid = ctk.CTkFrame(self.stats_container, fg_color="transparent")
            self.stats_grid.pack(fill="both", expand=True)
            
            total_kirim = len([r for r in self.active_data if len(r) > 5 and r[5] == ScanStatus.KIRIM])
            total_retur = len([r for r in self.active_data if len(r) > 5 and r[5] == ScanStatus.RETUR])
            total_pending = len([r for r in self.active_data if len(r) > 5 and r[5] == ScanStatus.PENDING])
            
            self.total_card = self.create_stat_card(
                "📦", "Total Paket", str(total_kirim), Config.get_color("success")
            )
            if self.total_card:
                self.total_card.pack(side="left", padx=(0, 15), fill="both", expand=True)
            
            self.retur_card = self.create_stat_card(
                "↩️", "Total Retur", str(total_retur), Config.get_color("danger")
            )
            if self.retur_card:
                self.retur_card.pack(side="left", padx=(0, 15), fill="both", expand=True)
            
            self.pending_card = self.create_stat_card(
                "⏳", "Total Pending", str(total_pending), Config.get_color("warning")
            )
            if self.pending_card:
                self.pending_card.pack(side="left", fill="both", expand=True)
            
            # EXPEDISI CHIPS - Canvas Version
            self.expedisi_frame = ctk.CTkFrame(
                self.content,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=20,
                height=150,
                border_width=0.5,
                border_color=Config.get_color("border")
            )
            self.expedisi_frame.pack(fill="x", pady=(0, 25))
            self.expedisi_frame.pack_propagate(False)
            
            header_frame = ctk.CTkFrame(self.expedisi_frame, fg_color="transparent")
            header_frame.pack(fill="x", padx=20, pady=(15, 5))
            
            ctk.CTkLabel(
                header_frame,
                text=Icons.truck + " Ekspedisi",
                font=self.font_headline,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            # Canvas-based expedition chips
            self.canvas_expedisi = CanvasExpeditionChips(self.expedisi_frame, width=1000, height=120)
            self.canvas_expedisi.clicked_callback = self.buka_detail_ekspedisi
            
            # VIRTUAL TABLE untuk SCAN HISTORY
            self.table_card = ctk.CTkFrame(
                self.content,
                fg_color=Config.get_color("bg_secondary"),
                corner_radius=20,
                border_width=0.5,
                border_color=Config.get_color("border")
            )
            self.table_card.pack(fill="both", expand=True)
            
            table_header = ctk.CTkFrame(self.table_card, fg_color="transparent", height=50)
            table_header.pack(fill="x", padx=20, pady=(15, 0))
            table_header.pack_propagate(False)
            
            ctk.CTkLabel(
                table_header,
                text="📋 Scan History",
                font=self.font_title_3,
                text_color=Config.get_color("text_primary")
            ).pack(side="left")
            
            self.count_label = ctk.CTkLabel(
                table_header,
                text=f"{len(self.active_data)} items",
                font=self.font_caption,
                text_color=Config.get_color("text_secondary")
            )
            self.count_label.pack(side="right")
            
            self.table_container = ctk.CTkFrame(self.table_card, fg_color="transparent")
            self.table_container.pack(fill="both", expand=True, padx=20, pady=(10, 20))
            
            # Canvas-based scan history with copy functionality
            self.canvas_history = CanvasScanHistory(
                self.table_container,
                self.header[0],
                self.col_widths,
                height=400
            )
            self.canvas_history.copy_callback = self.copy_to_clipboard
            
            # DELETE SECTION
            self.delete_section = ctk.CTkFrame(self.content, fg_color="transparent", height=60)
            self.delete_section.pack(fill="x", pady=(0, 25))
            self.delete_section.pack_propagate(False)
            
            entry_frame = ctk.CTkFrame(self.delete_section, fg_color=Config.get_color("bg_secondary"), corner_radius=12)
            entry_frame.pack(side="left", fill="x", expand=True, padx=(0, 15))
            
            ctk.CTkLabel(
                entry_frame,
                text=Icons.delete,
                font=ctk.CTkFont(size=14),
                text_color=Config.get_color("text_secondary")
            ).pack(side="left", padx=(15, 5))
            
            self.entry_hapus_resi = ctk.CTkEntry(
                entry_frame,
                placeholder_text="Nomor resi yang akan dihapus",
                height=44,
                font=self.font_body,
                fg_color="transparent",
                border_width=0,
                placeholder_text_color=Config.get_color("text_tertiary")
            )
            self.entry_hapus_resi.pack(side="left", fill="x", expand=True, padx=5)
            
            self.pending_toggle_btn = ctk.CTkButton(
                self.delete_section,
                text=Icons.pending + " Toggle Pending",
                font=self.font_button,
                fg_color=Config.get_color("warning"),
                hover_color="#D98C0A",
                height=44,
                width=160,
                corner_radius=22,
                command=self.toggle_status_pending
            )
            self.pending_toggle_btn.pack(side="right", padx=(0, 10))
            
            self.delete_btn = ctk.CTkButton(
                self.delete_section,
                text="Remove",
                font=self.font_button,
                fg_color=Config.get_color("danger"),
                hover_color="#D70015",
                height=44,
                width=120,
                corner_radius=22,
                command=self.hapus_resi_spesifik
            )
            self.delete_btn.pack(side="right", padx=(0, 10))
            
            # ACTION BUTTONS
            self.action_buttons = ctk.CTkFrame(self.content, fg_color="transparent", height=70)
            self.action_buttons.pack(fill="x", side="bottom", pady=(0, 10))
            self.action_buttons.pack_propagate(False)
            
            button_container = ctk.CTkFrame(self.action_buttons, fg_color="transparent")
            button_container.pack(side="right")
            
            self.undo_btn = ctk.CTkButton(
                button_container,
                text=Icons.delete + " Undo",
                font=self.font_button_large,
                fg_color=Config.get_color("danger"),
                hover_color="#D70015",
                height=50,
                width=150,
                corner_radius=25,
                command=self.hapus_item_tabel
            )
            self.undo_btn.pack(side="left", padx=(0, 10))
            
            self.new_session_btn = ctk.CTkButton(
                button_container,
                text=Icons.new_session + " New Session",
                font=self.font_button_large,
                fg_color=Config.get_color("accent"),
                hover_color="#0071E3",
                height=50,
                width=180,
                corner_radius=25,
                command=self.mulai_baru_reset
            )
            self.new_session_btn.pack(side="left", padx=(0, 10))
            
            self.save_archive_btn = ctk.CTkButton(
                button_container,
                text=Icons.save + " Save to Archive",
                font=self.font_button_large,
                fg_color=Config.get_color("accent_alt"),
                hover_color="#4A4A9E",
                height=50,
                width=200,
                corner_radius=25,
                command=self.save_ke_arsip_excel
            )
            self.save_archive_btn.pack(side="left", padx=(0, 10))
            
            # Initial update
            self.update_expedisi_chips()
            self.canvas_history.set_data(self.active_data)
        except Exception as e:
            self.logger.error(f"Setup UI error: {e}")

# ============ MAIN ============
if __name__ == "__main__":
    try:
        app = IScanApp()
        app.mainloop()
    except Exception as e:
        logging.critical(f"Fatal error: {e}", exc_info=True)
        messagebox.showerror("Fatal Error", f"Aplikasi mengalami error:\n{str(e)}")