"""
geo.py — Country geocoding utilities for Crisis Monitor.

CHANGES from original utils.py:
  - Extracted into its own module
  - Explicit load-once pattern with clear error on missing file
  - Added get_country_name() for display purposes
"""

import json
from pathlib import Path
from typing import Optional
from logger import get_logger

_log = get_logger("geo")

_DATA_PATH = Path(__file__).parent / "data" / "country_coords.json"
_coords: dict = {}
_loaded: bool = False


def _ensure_loaded():
    """Load country coordinates once. Raises FileNotFoundError if missing."""
    global _coords, _loaded
    if _loaded:
        return
    if not _DATA_PATH.exists():
        raise FileNotFoundError(
            f"Country coordinates file not found: {_DATA_PATH}\n"
            f"Expected a JSON file mapping ISO-2 codes to {{lat, lng, name}}."
        )
    with open(_DATA_PATH, encoding="utf-8") as f:
        _coords = json.load(f)
    _loaded = True
    _log.debug(f"Loaded {len(_coords)} country codes from {_DATA_PATH}")


def get_coords(country_code: str) -> Optional[dict]:
    """Get full coordinate data for a country code (ISO-2, case insensitive)."""
    _ensure_loaded()
    return _coords.get(country_code.upper())


def get_lat_lng(country_code: str) -> tuple[float, float] | None:
    """Get (lat, lng) tuple for a country code, or None if not found."""
    data = get_coords(country_code)
    if data:
        return data["lat"], data["lng"]
    return None


def validate_country_code(code: str) -> bool:
    """Check if a country code exists in the coordinates dataset."""
    _ensure_loaded()
    return code.upper() in _coords


def all_country_codes() -> list[str]:
    """Return all known ISO-2 country codes."""
    _ensure_loaded()
    return list(_coords.keys())


def get_country_name(code: str) -> str | None:
    """Get the display name for a country code, if available."""
    data = get_coords(code)
    if data:
        return data.get("name")
    return None
