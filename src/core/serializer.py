"""Emit the final filter JSON.

Every `Is*` flag is computed here from its own payload and nowhere else. A
populated `Stop: [0]` sitting next to `IsStop: false` is the most likely bug in
this service, and one computation site removes the whole class.
"""
from typing import Any, Dict, List

from src.schema.filter_json import (
    BOOL_FIELDS,
    LIST_FIELDS,
    RANGE_FIELDS,
    SCALAR_FIELDS,
    empty_filter,
    flag_name,
)


def _finalise_leg(leg: Dict[str, Any]) -> Dict[str, Any]:
    # Start from a fresh template so key order and completeness are guaranteed
    # regardless of what the caller sent back as currentFilter.
    out = empty_filter()

    for field in RANGE_FIELDS:
        payload = leg.get(field) or {}
        lo = "" if payload.get("Min") in (None, "") else str(payload["Min"])
        hi = "" if payload.get("Max") in (None, "") else str(payload["Max"])
        out[field] = {"Min": lo, "Max": hi}
        out[flag_name(field)] = bool(lo or hi)

    for field in LIST_FIELDS:
        values = list(leg.get(field) or [])
        out[field] = values
        out[flag_name(field)] = len(values) > 0

    for field in BOOL_FIELDS:
        out[field] = bool(leg.get(field))

    for field in SCALAR_FIELDS:
        token = leg.get(field) or ""
        out[field] = str(token)
        out[flag_name(field)] = bool(token)

    return out


def serialize(legs: List[Dict[str, Any]], roundtrip: bool) -> Any:
    """One object for oneway, a two-element array for roundtrip."""
    finalised = [_finalise_leg(leg) for leg in legs]
    if roundtrip:
        while len(finalised) < 2:
            finalised.append(empty_filter())
        return finalised[:2]
    return finalised[0]
