"""Turn one LLM op into a concrete field payload.

Division of labour: the model converts colloquial input ("10k" -> 10000,
"6pm" -> "18:00"), because it is better at that than a regex table. This module
does the two things the model cannot:

  a. validate and normalise the bounds it supplies into the wire format;
  b. map preset names through a fixed table, so "morning" is the same window on
     every call.

Comparative words ("cheapest", "fastest") are NOT turned into numeric bounds -
they set SortBy instead. Filtering out mid-priced flights is not what a user
asking for "the cheapest" means, and a synthetic band was only ever a stand-in
for the sort the API actually offers.

What this module deliberately does NOT do is clamp explicit user numbers or
predict whether a filter will return results. "under 2k" on a route starting at
4,210 is emitted as-is; the consuming side runs the filter and owns that outcome.
"""
import re
from typing import Any, Dict, Optional, Tuple

from src.core.facets import LegFacets
from src.schema.filter_json import FACET_KEY_FOR_FIELD, MAX_STOPS, SORT_VALUES
from src.utils import duration as duration_utils
from src.utils import timewin

TIME_FIELDS = ("DepTime", "ArrTime")


def _numeric(bound: str) -> Optional[float]:
    """The comparable number behind a normalised bound string."""
    if bound is None:
        return None
    text = str(bound)
    if "h" in text.lower():  # "02h 15m"
        return duration_utils.to_minutes(text)
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _is_zero(bound: str) -> bool:
    digits = re.sub(r"[^0-9]", "", bound)
    return digits == "" or int(digits) == 0


def _parse_bound(field: str, raw: Any) -> Optional[str]:
    """Validate and normalise an explicit bound the model supplied."""
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip()

    if field in TIME_FIELDS:
        return text if timewin.is_valid_hhmm(text) else None

    if field == "Duration":
        # The filter API takes minutes, so "3h" / "02h 15m" / "180" all leave
        # here as a plain minute count. Facets still ARRIVE as "02h 15m" -
        # that is the search response's format, not the filter's.
        minutes = duration_utils.to_minutes(text)
        return str(minutes) if minutes is not None else None

    # Price - strip separators and currency, keep it an integer string.
    cleaned = text.replace(",", "").replace("₹", "").replace("Rs", "").replace("rs", "").strip()
    try:
        return str(int(round(float(cleaned))))
    except (TypeError, ValueError):
        pass

    # Safety net for a known model slip: it is asked to send 10000, but
    # occasionally echoes the user's "10k" or "2 lakh" verbatim. This only
    # normalises a numeric token the model already isolated - it is not a parser
    # for raw chat phrasing ("under 10k", "between 5k and 10k"), which stays the
    # model's job.
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(k|thousand|l|lac|lakh|lakhs|cr|crore)$", cleaned, re.IGNORECASE)
    if m:
        multiplier = {
            "k": 1_000, "thousand": 1_000,
            "l": 100_000, "lac": 100_000, "lakh": 100_000, "lakhs": 100_000,
            "cr": 10_000_000, "crore": 10_000_000,
        }[m.group(2).lower()]
        return str(int(round(float(m.group(1)) * multiplier)))

    return None


def resolve_range(field: str, op: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Build a {"Min","Max"} payload for a range field.

    Takes no facets: explicit bounds are passed through untouched, so there is
    nothing to compare them against.

    Returns (payload, unavailable_reason). A None payload with a reason means we
    could not honour the request.
    """
    preset = op.get("preset")
    if preset and field in TIME_FIELDS:
        window = timewin.preset_window(preset)
        if window:
            return {"Min": window[0], "Max": window[1]}, None
        return None, f"unknown time window '{preset}'"

    lo = _parse_bound(field, op.get("range_min"))
    hi = _parse_bound(field, op.get("range_max"))

    # "below 1.5k" has no lower bound, but a model sometimes fills one in as 0.
    # Emitting Min="0" is noise: it means the same as unset, and differs run to
    # run. Only Price/Duration - "00:00" is a real DepTime bound.
    if field in ("Price", "Duration") and lo is not None and _is_zero(lo):
        lo = None

    # A negative fare or duration is outside the domain, not merely a narrow
    # filter. Unlike "under 2k" on an expensive route - which we pass through
    # untouched - there is no result this could ever describe.
    if field in ("Price", "Duration"):
        for bound, value in (("range_min", lo), ("range_max", hi)):
            if value is not None and _numeric(value) is not None and _numeric(value) < 0:
                return None, f"{field} cannot be negative"

        # A zero upper bound is empty for the same reason: no flight costs
        # nothing or takes no time. A zero LOWER bound is different - it just
        # means "no lower bound" - and is dropped above.
        if hi is not None and _numeric(hi) == 0:
            return None, f"{field} upper bound of zero cannot match"

        # An inverted interval is empty by arithmetic, so emitting it would hand
        # the caller a filter that cannot match. Time fields are left alone:
        # "night" is legitimately 21:00-03:00 and wraps midnight.
        if lo is not None and hi is not None:
            lo_n, hi_n = _numeric(lo), _numeric(hi)
            if lo_n is not None and hi_n is not None and lo_n > hi_n:
                return None, f"{field} range is inverted ({lo} > {hi})"

    if lo is None and hi is None:
        return None, f"no usable bound for {field}"
    return {"Min": lo or "", "Max": hi or ""}, None


def resolve_stops(op: Dict[str, Any]):
    """Parse requested stop counts. No facet needed - a stop count is just an int.

    Implausible counts are rejected rather than passed through, so "47 stops"
    does not reach the caller as a filter nothing can satisfy.
    """
    accepted, rejected = [], []
    for item in op.get("values") or []:
        text = str(item).strip().lower()
        # The model is told to send "0"/"1", but may echo the traveller's words.
        if text in ("non-stop", "nonstop", "non stop", "direct", "no stops"):
            if 0 not in accepted:
                accepted.append(0)
            continue
        digits = re.sub(r"[^0-9]", "", text)
        if digits == "":
            rejected.append(str(item))
            continue
        count = int(digits)
        if count > MAX_STOPS:
            rejected.append(str(item))
        elif count not in accepted:
            accepted.append(count)
    return accepted, rejected


def resolve_values(field: str, op: Dict[str, Any], facets: LegFacets):
    """Map requested list values onto the caller's own facet tokens.

    Returns (accepted_values, rejected_labels). A rejection means the caller
    never offered that option, so we have no token to write.
    """
    facet_key = FACET_KEY_FOR_FIELD[field]
    wanted = op.get("values") or []
    accepted, rejected = [], []
    for item in wanted:
        resolved = facets.resolve(facet_key, item)
        if resolved is None:
            rejected.append(str(item))
        elif resolved not in accepted:
            accepted.append(resolved)
    return accepted, rejected


def resolve_exclusion(field: str, op: Dict[str, Any], facets: LegFacets):
    """Turn "not X" into the facet values that survive it.

    The filter schema can only include, never exclude, so an exclusion is
    expressed as the complement: everything the caller offered, minus what the
    user ruled out. Returns (surviving_values, rejected_labels); an empty
    survivor list means the user ruled out every option there was.
    """
    facet_key = FACET_KEY_FOR_FIELD[field]
    unwanted, rejected = [], []
    for item in op.get("values") or []:
        resolved = facets.resolve(facet_key, item)
        if resolved is None:
            rejected.append(str(item))
        elif resolved not in unwanted:
            unwanted.append(resolved)

    if not unwanted:
        return [], rejected

    surviving = [v for v in facets.allowed_values(facet_key) if v not in unwanted]
    return surviving, rejected


def _sort_key(text: Any) -> str:
    """Collapse a sort token to letters and digits only.

    The published tokens carry spaces and a hyphen ("Early Take-off"), and a
    model may echo them as "early_takeoff" or "EARLY TAKE-OFF". Comparing on a
    stripped key accepts all of those without widening the vocabulary.
    """
    return re.sub(r"[^a-z0-9]", "", str(text).strip().lower())


_SORT_LOOKUP = {_sort_key(value): value for value in SORT_VALUES}


def resolve_sort(op: Dict[str, Any]) -> Optional[str]:
    """Map a requested sort onto one of the tokens we publish."""
    wanted = op.get("sort") or op.get("values")
    if isinstance(wanted, list):
        wanted = wanted[0] if wanted else None
    if not wanted:
        return None
    return _SORT_LOOKUP.get(_sort_key(wanted))
