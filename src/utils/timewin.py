"""Time-of-day presets and "HH:MM" handling.

Deliberately small: the LLM converts loose phrasing like "6pm" or "1830" into
"18:00" itself, so there is no loose-string parser here. What *is* here is the
preset table - what "morning" means is a product decision and must be identical
on every call, which a model cannot guarantee.
"""
import re
from typing import Optional, Tuple

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")

# Window presets, as "HH:MM-HH:MM".
#
# The late ones wrap past midnight, so Min > Max on purpose - the filter API
# handles the wrap, confirmed with the consuming team. Do not "fix" these into
# ascending order; 21:00-24:00 silently drops the small hours a traveller
# asking for a night flight means.
PRESETS = {
    "early morning": "00:00-06:00",
    "morning": "06:00-12:00",
    "late morning": "09:00-12:00",
    "noon": "11:00-14:00",
    "afternoon": "12:00-17:00",
    "evening": "17:00-21:00",
    "night": "21:00-03:00",
    "late night": "23:00-04:00",
    "midnight": "23:00-01:00",
}
# "red eye" is deliberately not a preset: the filter has an IsRedEyes flag, and
# a DepTime window here meant "red eye" and "red eye flights only" produced two
# different filters for the same request.


# Presets that legitimately wrap past midnight.
WRAPPING = ("night", "late night", "midnight")


def is_valid_hhmm(value: str) -> bool:
    """True for "00:00" through "24:00"."""
    if not isinstance(value, str):
        return False
    m = _HHMM.match(value.strip())
    if not m:
        return False
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh == 24:
        return mm == 0
    return 0 <= hh <= 23 and 0 <= mm <= 59


def to_minutes(value: str) -> Optional[int]:
    """"18:30" -> 1110. None when the input is not a valid HH:MM."""
    if not is_valid_hhmm(value):
        return None
    hh, mm = value.strip().split(":")
    return int(hh) * 60 + int(mm)


def from_minutes(total: int) -> str:
    """1110 -> "18:30". Clamped to the 00:00-24:00 range."""
    total = max(0, min(24 * 60, int(total)))
    return f"{total // 60:02d}:{total % 60:02d}"


def preset_window(name: str) -> Optional[Tuple[str, str]]:
    """Look up a preset by name, returning ("06:00", "12:00")."""
    if not name:
        return None
    window = PRESETS.get(name.strip().lower())
    if not window:
        return None
    start, end = window.split("-")
    return start, end
