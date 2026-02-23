"""
Shared utilities for robust data handling.
"""
import logging

logger = logging.getLogger(__name__)

def safe_float(val, default=0.0):
    """Safely convert value to float, handling None, empty strings, and other types."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    """Safely convert value to int, handling None, empty strings, and other types."""
    if val is None:
        return default
    try:
        # Handle cases where float string is passed to int() (e.g. "10.0")
        if isinstance(val, str) and '.' in val:
            return int(float(val))
        return int(val)
    except (ValueError, TypeError):
        return default
