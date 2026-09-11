"""Duration parsing for the "02h 15m" format the search API returns.

Facet duration bounds arrive in that shape; the filter API wants plain minutes,
so this only ever converts inward.

Ported from EMT_TOOLS_ECOSYSTEM tools_factory/flights/flight_search_service.py
(_duration_to_minutes). Needed because resolving "shortest" requires arithmetic
on the duration facet range, and that range arrives as a string.
"""
import re
from typing import Any, Optional

_HM = re.compile(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?", re.IGNORECASE)


def to_minutes(value: Any) -> Optional[int]:
    """"02h 15m" -> 135. Also accepts "2h", "45m", plain ints, and "135"."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip().lower()
    if not text:
        return None

    if text.isdigit():
        return int(text)

    if ":" in text:  # "02:15"
        parts = text.split(":", 1)
        if parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]) * 60 + int(parts[1])

    m = _HM.match(text)
    if m and (m.group(1) or m.group(2)):
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        return hours * 60 + minutes

    return None
