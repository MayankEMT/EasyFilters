"""Normalise and index the facets the caller sends.

Facets are the closed vocabulary for the five fields whose valid values only
exist once a search has run: airline, layover, aircraft type, and the two
airport fields. Whatever the caller sends is exactly what we echo back into the
filter JSON - that is what keeps us from guessing "IndiGo" when the API wants
"6E".

The wire form is a comma-separated string per field:

    {"airline": "IndiGo,Air India,SpiceJet", "layover": "HYD,BLR"}

Arrays are accepted too, including {"value","label"} objects, so a caller that
already holds structured lists need not flatten them.

Stop is deliberately absent: a stop count is a plain integer, so it needs no
vocabulary. So are the price/duration/time ranges - comparative words like
"cheapest" set SortBy now, so there is nothing left to measure against.

Alongside the lists the caller sends the searched sector:

    {"from": "DEL", "to": "CCU", ...}

That is not a vocabulary - it is the one airport at each end the traveller
actually searched for. It exists so "hide nearby airports" can be resolved: the
phrase names no airport, and the lists alone cannot say which of DEL/DXN/HDO was
the searched one.
"""
from typing import Any, Dict, List, Optional, Tuple

from src.schema.filter_json import FACET_GATED_FIELDS, FACET_KEY_FOR_FIELD

LIST_FACET_KEYS = tuple(FACET_KEY_FOR_FIELD[f] for f in FACET_GATED_FIELDS)

# The searched origin and destination. Aliases are accepted because the naming
# is the caller's to choose and tolerating both costs a dict lookup.
SECTOR_KEYS = {"from": ("from", "origin"), "to": ("to", "destination")}


class FacetError(ValueError):
    """Raised when facets are missing or unusable; surfaces as a 400."""


def _norm_entry(raw: Any) -> Optional[Dict[str, Any]]:
    """Coerce a facet entry to {"value": <original>, "label": str}.

    Accepts {"value","label"}, {"value"}, bare strings and bare ints - the
    caller's own data shapes vary by field.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        if "value" not in raw:
            return None
        value = raw["value"]
        label = raw.get("label")
        return {"value": value, "label": str(label if label not in (None, "") else value)}
    if isinstance(raw, (str, int, float)) and not isinstance(raw, bool):
        return {"value": raw, "label": str(raw)}
    return None


def _entries(raw):
    """Normalise one field's facet into a list of {"value","label"} entries.

    Accepts the comma-separated string the caller sends, or an array of plain
    strings or {"value","label"} objects.
    """
    if isinstance(raw, str):
        entries = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            # "NMI:Navi Mumbai" keeps a display name alongside the code, so a
            # traveller saying "navi mumbai" still resolves. Plain "NMI" works
            # too - it is then both the value and the only thing to match on.
            value, _, label = part.partition(":")
            value, label = value.strip(), label.strip()
            entries.append({"value": value, "label": label or value})
        return entries
    if isinstance(raw, list):
        return [e for e in (_norm_entry(x) for x in raw) if e]
    single = _norm_entry(raw)
    return [single] if single else []


def _key(text: Any) -> str:
    return " ".join(str(text).strip().lower().split())


class LegFacets:
    """Indexed facets for a single leg."""

    def __init__(self, raw: Dict[str, Any]):
        self.values: Dict[str, List[Dict[str, Any]]] = {}
        self._lookup: Dict[str, Dict[str, Any]] = {}
        self.sector: Dict[str, Any] = {}

        raw = raw if isinstance(raw, dict) else {}

        for end, aliases in SECTOR_KEYS.items():
            for alias in aliases:
                entries = _entries(raw.get(alias)) if alias in raw else []
                if entries:
                    # One airport per end; "DEL" and "DEL:New Delhi" both work
                    # because _entries already splits on the colon.
                    self.sector[end] = entries[0]["value"]
                    break

        for key in LIST_FACET_KEYS:
            if key not in raw:
                continue
            normalised = _entries(raw.get(key))
            if not normalised:
                continue
            self.values[key] = normalised
            index: Dict[str, Any] = {}
            for entry in normalised:
                index[_key(entry["value"])] = entry["value"]
                index[_key(entry["label"])] = entry["value"]
            self._lookup[key] = index

    def has_any(self) -> bool:
        return bool(self.values)

    def sector_airport(self, end: str) -> Optional[Any]:
        """The searched airport at one end: "from" or "to".

        Returned as the caller's own token where the matching airport list was
        sent, so the spelling matches the rest of the filter; otherwise the raw
        sector value, which is still the caller's own.
        """
        value = self.sector.get(end)
        if value is None:
            return None
        facet_key = "takeOffAirport" if end == "from" else "landingAirport"
        return self.resolve(facet_key, value) or value

    def allowed_values(self, facet_key: str) -> List[Any]:
        return [e["value"] for e in self.values.get(facet_key, [])]

    def resolve(self, facet_key: str, wanted: Any) -> Optional[Any]:
        """Map a model-supplied token to the caller's own facet value.

        Returns None when there is no match - the caller never sent that option,
        so we have no token to write and must report no_match.
        """
        index = self._lookup.get(facet_key)
        if not index:
            return None

        exact = index.get(_key(wanted))
        if exact is not None:
            return exact

        # Fall back to a unique substring match, so "boeing 737" resolves
        # against "Boeing 737 (Narrow-body)". Only when exactly one entry
        # matches - an ambiguous prefix stays unresolved rather than guessed.
        needle = _key(wanted)
        if len(needle) < 3:
            return None
        hits = {value for key, value in index.items() if needle in key or key in needle}
        return hits.pop() if len(hits) == 1 else None

    def prompt_vocabulary(self) -> Dict[str, List[str]]:
        """Human-readable allowed values, for injecting into the prompt."""
        out: Dict[str, List[str]] = {}
        for key, entries in self.values.items():
            out[key] = [
                entry["label"] if _key(entry["label"]) != _key(entry["value"])
                else str(entry["value"])
                for entry in entries
            ]
        return out

    def all_tokens(self) -> List[str]:
        """Every label and value across every field, for the model's enum."""
        seen, tokens = set(), []
        for entries in self.values.values():
            for entry in entries:
                for token in (str(entry["value"]), entry["label"]):
                    if token and token not in seen:
                        seen.add(token)
                        tokens.append(token)
        return tokens


def parse(raw: Any, roundtrip: bool) -> Tuple[LegFacets, ...]:
    """Validate and index the request's facets.

    Roundtrip facets must be a two-element array: on real searches the legs
    genuinely differ (different layover airports, different price ranges), so a
    single shared object would mis-filter one leg.
    """
    if raw is None:
        raise FacetError("facets is required")

    if isinstance(raw, list):
        if not raw:
            raise FacetError("facets is required")
        legs = [LegFacets(item) for item in raw[:2]]
    elif isinstance(raw, dict):
        if not raw:
            raise FacetError("facets is required")
        legs = [LegFacets(raw)]
    else:
        raise FacetError("facets must be an object, or an array of two objects for roundtrip")

    if not any(leg.has_any() for leg in legs):
        raise FacetError(
            "facets contained no usable field; expected at least one of "
            f"{', '.join(LIST_FACET_KEYS)}"
        )

    if roundtrip and len(legs) == 1:
        # Tolerated, but the two legs really can differ - flagged by the caller
        # sending one object for a roundtrip search.
        legs = [legs[0], legs[0]]

    return tuple(legs)
