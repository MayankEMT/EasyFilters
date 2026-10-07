"""The output filter JSON: its exact shape, and the field metadata everything
else is driven from.

The spelling here mirrors the consuming API exactly - including `AirCarftType`
and `IsRedEyes`. Do not "fix" either; they are the wire format.
"""
from copy import deepcopy
from typing import Any, Dict, List

# Fields carrying a {Min, Max} pair. The `Is*` flag is derived from whether
# either bound is set.
RANGE_FIELDS = ("Price", "DepTime", "ArrTime", "Duration")

# Range fields where zero is a meaningful floor, so an upper bound on its own
# can be completed with "0" - the consuming filter wants both bounds present.
# Deliberately excludes DepTime/ArrTime: "00:00" is a real time of day, not an
# absence, and "arrive before noon" must not become "between midnight and noon".
ZERO_FLOOR_FIELDS = ("Price", "Duration")

# Fields carrying a list of values.
LIST_FIELDS = (
    "Stop",
    "Airline",
    "Layover",
    "AirCarftType",
    "TakeOffAirport",
    "LandingAirport",
)

# The list fields whose valid values are unknowable without facets, because the
# facet is our sole source of the token to write. Stop is excluded: a stop count
# is a plain integer, so we can always emit it without being told the options.
FACET_GATED_FIELDS = (
    "Airline",
    "Layover",
    "AirCarftType",
    "TakeOffAirport",
    "LandingAirport",
)

# Implausible stop counts are rejected rather than passed through.
MAX_STOPS = 3

# A pseudo-field: the model uses it to say "only the airports I searched", and
# the merger turns that into TakeOffAirport/LandingAirport from the caller's
# sector. It is never a key in the emitted filter.
NEARBY_FIELD = "NearbyAirports"

# Fields where "not X" is rewritten as "everything except X", using the facet
# list as the set of possibilities.
#
# Layover carries a known caveat, included here as a product decision: a
# non-stop flight has no layover value, and the consuming API ANDs Layover with
# the rest of the filter - verified on the live site, where picking a layover
# returns only flights routed through it. So "avoid Bengaluru" emitting
# Layover=[the others] also removes every non-stop flight from the results.
# Accepted deliberately: the alternative is declining the request outright.
# It becomes lossless the day the filter API accepts a "no layover" token.
EXCLUDABLE_FIELDS = (
    "Airline",
    "Layover",
    "AirCarftType",
    "TakeOffAirport",
    "LandingAirport",
)

# Standalone booleans with no companion array and no `Is*` twin of their own.
# We can always set these, so they never need a facet.
BOOL_FIELDS = ("Refundable", "IsWifi", "IsRedEyes")

# Single-value fields carrying one token from a fixed vocabulary.
SCALAR_FIELDS = ("SortBy",)

ALL_FIELDS = RANGE_FIELDS + LIST_FIELDS + BOOL_FIELDS + SCALAR_FIELDS

# The sort options we emit, spelled exactly as the listing page labels them.
# Defined here alone, so re-spelling them for the API is a one-place change.
SORT_VALUES = (
    "Best",
    "Cheapest",
    "Fastest",
    "Early Take-off",
    "Late Take-off",
    "Early Arrival",
    "Late Arrival",
    "Slowest",
    "Highest Price",
)

# Which facet key feeds each facet-gated field.
FACET_KEY_FOR_FIELD = {
    "Airline": "airline",
    "Layover": "layover",
    "AirCarftType": "airCarftType",
    "TakeOffAirport": "takeOffAirport",
    "LandingAirport": "landingAirport",
}

# `Refundable` has no `Is` prefix; the other two already carry it.
_BOOL_FLAG_NAME = {"Refundable": "Refundable", "IsWifi": "IsWifi", "IsRedEyes": "IsRedEyes"}


def flag_name(field: str) -> str:
    """The `Is*` flag key belonging to a field."""
    if field in BOOL_FIELDS:
        return _BOOL_FLAG_NAME[field]
    return f"Is{field}"


def empty_filter() -> Dict[str, Any]:
    """A fresh filter with every key present and nothing set.

    Key order matches the spec the consuming team supplied.
    """
    return {
        "IsPrice": False,
        "Price": {"Min": "", "Max": ""},
        "IsDepTime": False,
        "DepTime": {"Min": "", "Max": ""},
        "IsArrTime": False,
        "ArrTime": {"Min": "", "Max": ""},
        "IsStop": False,
        "Stop": [],
        "IsAirline": False,
        "Airline": [],
        "IsDuration": False,
        "Duration": {"Min": "", "Max": ""},
        "IsLayover": False,
        "Layover": [],
        "IsAirCarftType": False,
        "AirCarftType": [],
        "Refundable": False,
        "IsWifi": False,
        "IsRedEyes": False,
        "IsTakeOffAirport": False,
        "TakeOffAirport": [],
        "IsLandingAirport": False,
        "LandingAirport": [],
        "IsSortBy": False,
        "SortBy": "",
    }


def empty_for_trip(trip_type: str) -> Any:
    """One object for oneway, a two-element list for roundtrip."""
    if is_roundtrip(trip_type):
        return [empty_filter(), empty_filter()]
    return empty_filter()


def is_roundtrip(trip_type: str) -> bool:
    return str(trip_type or "").strip().lower() in {"roundtrip", "round_trip", "round trip", "rt"}


def as_legs(filter_obj: Any, trip_type: str) -> List[Dict[str, Any]]:
    """Normalise a filter into a list of leg dicts we can mutate uniformly."""
    roundtrip = is_roundtrip(trip_type)
    if filter_obj is None:
        return [empty_filter(), empty_filter()] if roundtrip else [empty_filter()]

    if isinstance(filter_obj, list):
        legs = [deepcopy(leg) if isinstance(leg, dict) else empty_filter() for leg in filter_obj]
        if roundtrip:
            while len(legs) < 2:
                legs.append(empty_filter())
            return legs[:2]
        return legs[:1] or [empty_filter()]

    if isinstance(filter_obj, dict):
        leg = deepcopy(filter_obj)
        return [leg, deepcopy(filter_obj)] if roundtrip else [leg]

    return [empty_filter(), empty_filter()] if roundtrip else [empty_filter()]


def from_legs(legs: List[Dict[str, Any]], trip_type: str) -> Any:
    """Inverse of as_legs."""
    if is_roundtrip(trip_type):
        return legs[:2]
    return legs[0]
