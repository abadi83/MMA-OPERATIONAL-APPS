"""
Custom exceptions module for iScan Pro.
"""


class IScanException(Exception):
    """Base exception for all iScan application errors."""
    pass


class DatabaseError(IScanException):
    """Raised when a database operation fails."""
    pass


class ValidationError(IScanException):
    """Raised when input validation fails."""
    pass


class ConfigError(IScanException):
    """Raised when configuration is invalid or missing."""
    pass


class FileOperationError(IScanException):
    """Raised when a file operation (read/write) fails."""
    pass


class CameraError(IScanException):
    """Raised when camera operations fail."""
    pass


class ReportGenerationError(IScanException):
    """Raised when report generation fails."""
    pass
