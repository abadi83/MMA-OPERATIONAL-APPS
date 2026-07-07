"""
Validator module for iScan Pro.
Provides validation functions for resi numbers, store names, etc.
"""

import re
from typing import Optional


class Validator:
    """Static validation utilities."""

    # Resi pattern: alphanumeric, min 3 chars, max 50 chars
    RESI_PATTERN = re.compile(r"^[A-Za-z0-9\-_]{3,50}$")

    # Store name pattern: allows letters, numbers, spaces, and basic punctuation
    STORE_PATTERN = re.compile(r"^[A-Za-z0-9\s\-_.,&()']{2,100}$")

    @staticmethod
    def resi(resi: str) -> bool:
        """Validate a resi/tracking number.

        Args:
            resi: The resi number string to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not resi or not isinstance(resi, str):
            return False
        return bool(Validator.RESI_PATTERN.match(resi.strip()))

    @staticmethod
    def store(store_name: str) -> bool:
        """Validate a store name.

        Args:
            store_name: The store name string to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not store_name or not isinstance(store_name, str):
            return False
        return bool(Validator.STORE_PATTERN.match(store_name.strip()))

    @staticmethod
    def sanitize_resi(resi: str) -> Optional[str]:
        """Sanitize a resi number: strip, uppercase, remove whitespace.

        Args:
            resi: Raw resi input.

        Returns:
            Sanitized resi string, or None if invalid.
        """
        if not resi:
            return None
        cleaned = resi.strip().upper()
        cleaned = re.sub(r"\s+", "", cleaned)
        if Validator.resi(cleaned):
            return cleaned
        return None


def validate_resi_or_raise(resi: str) -> str:
    """Validate resi or raise ValidationError.

    Args:
        resi: Resi number to validate.

    Returns:
        Sanitized resi string.

    Raises:
        ValidationError: If resi is invalid.
    """
    from exceptions import ValidationError

    cleaned = Validator.sanitize_resi(resi)
    if not cleaned:
        raise ValidationError(f"Format resi tidak valid: '{resi}'. Minimal 3 karakter alfanumerik.")
    return cleaned


def validate_store_or_raise(store_name: str) -> str:
    """Validate store name or raise ValidationError.

    Args:
        store_name: Store name to validate.

    Returns:
        Trimmed store name.

    Raises:
        ValidationError: If store name is invalid.
    """
    from exceptions import ValidationError

    name = store_name.strip()
    if not Validator.store(name):
        raise ValidationError(f"Nama toko tidak valid: '{store_name}'")
    return name
