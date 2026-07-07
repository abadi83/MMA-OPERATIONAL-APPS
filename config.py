"""
Config module for iScan Pro - Streamlit Edition
Handles application configuration, paths, themes, and colors.
"""

import os
from enum import Enum


class Theme(Enum):
    DARK = "dark"
    LIGHT = "light"


class Config:
    """Application configuration singleton."""

    # Base path
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))

    # Database
    DB_PATH = os.path.join(BASE_PATH, "iscan_database.db")

    # Folders
    LOGS_FOLDER = os.path.join(BASE_PATH, "logs")
    ARSIP_FOLDER = os.path.join(BASE_PATH, "Gudang_Arsip_Excel")
    HANDOVER_FOLDER = os.path.join(BASE_PATH, "Handover_Reports")
    SALES_FOLDER = os.path.join(BASE_PATH, "Sales_Reports")
    VIDEOS_FOLDER = os.path.join(BASE_PATH, "Packing_Videos")

    APP_GEOMETRY = "1280x800"

    _current_theme = Theme.DARK

    # Color schemes
    _colors = {
        Theme.DARK: {
            "bg_primary": "#0A0A0A",
            "bg_secondary": "#1C1C1E",
            "bg_tertiary": "#2C2C2E",
            "bg_element": "#1C1C1E",
            "bg_dark": "#000000",
            "text_primary": "#FFFFFF",
            "text_secondary": "#AEAEB2",
            "text_tertiary": "#636366",
            "accent": "#0A84FF",
            "accent_alt": "#5E5CE6",
            "success": "#30D158",
            "warning": "#FF9F0A",
            "danger": "#FF453A",
            "border": "#38383A",
            "menu_hover": "#2C2C2E",
            "sidebar_text": "#AEAEB2",
        },
        Theme.LIGHT: {
            "bg_primary": "#F2F2F7",
            "bg_secondary": "#FFFFFF",
            "bg_tertiary": "#E5E5EA",
            "bg_element": "#FFFFFF",
            "bg_dark": "#F2F2F7",
            "text_primary": "#000000",
            "text_secondary": "#3C3C43",
            "text_tertiary": "#8E8E93",
            "accent": "#007AFF",
            "accent_alt": "#5856D6",
            "success": "#34C759",
            "warning": "#FF9500",
            "danger": "#FF3B30",
            "border": "#D1D1D6",
            "menu_hover": "#E5E5EA",
            "sidebar_text": "#3C3C43",
        },
    }

    @classmethod
    def get_color(cls, key: str, default: str = "#FFFFFF") -> str:
        """Get a color value for the current theme."""
        return cls._colors.get(cls._current_theme, {}).get(key, default)

    @classmethod
    def set_theme(cls, theme: Theme) -> None:
        """Set the current theme."""
        cls._current_theme = theme

    @classmethod
    def get_theme(cls) -> Theme:
        """Get the current theme."""
        return cls._current_theme

    @classmethod
    def ensure_folders(cls) -> None:
        """Create all required folders if they don't exist."""
        folders = [
            cls.LOGS_FOLDER,
            cls.ARSIP_FOLDER,
            cls.HANDOVER_FOLDER,
            cls.SALES_FOLDER,
            cls.VIDEOS_FOLDER,
        ]
        for folder in folders:
            os.makedirs(folder, exist_ok=True)
