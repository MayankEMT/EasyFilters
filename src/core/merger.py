"""Apply LLM ops onto the current filter, one leg at a time.

Patching rather than regenerating is what makes cumulative refinement work:
"also make it morning" must not drop the airline filter the user set two turns
ago, and "remove the morning filter" must clear exactly one field.
"""
from typing import Any, Dict, List, Tuple

from src.core.facets import LegFacets
from src.core.resolver import (
    resolve_exclusion,
    resolve_range,
    resolve_sort,
    resolve_stops,
    resolve_values,
)
from src.schema.filter_json import (
    BOOL_FIELDS,
    EXCLUDABLE_FIELDS,
    FACET_GATED_FIELDS,
    LIST_FIELDS,
    RANGE_FIELDS,
    SCALAR_FIELDS,
    empty_filter,
)


def _target_legs(op: Dict[str, Any], leg_count: int) -> List[int]:
    """Which legs an op applies to. Defaults to all of them."""
    if op.get("field") in SCALAR_FIELDS:
        # Sort is one choice for the whole itinerary - the consuming API sorts
        # the combined roundtrip, not each leg separately. "make the first
        # flight the cheapest" must not leave the two legs disagreeing, so a
        # sort always lands on every leg whatever the model aimed it at.
        return list(range(leg_count))

    legs = op.get("legs")
    if not legs:
        return list(range(leg_count))
    valid = [int(i) for i in legs if isinstance(i, (int, float)) and 0 <= int(i) < leg_count]
    return valid or list(range(leg_count))


def _normalise(ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Split out a `sort` that arrived on some other field's op.

    Models reliably express the sort intent but not always in its own op - e.g.
    "non stop under 8k cheapest first" comes back as
    {field:"Stop", values:["0"], sort:"Cheapest"}. The intent is unambiguous, so
    recover it rather than dropping a filter the user actually asked for.
    """
    out: List[Dict[str, Any]] = []
    for op in ops:
        field = op.get("field")
        if op.get("sort") and field not in SCALAR_FIELDS:
            out.append(
                {
                    "action": "set",
                    "field": "SortBy",
                    "sort": op["sort"],
                    "legs": op.get("legs"),
                }
            )
            op = {k: v for k, v in op.items() if k != "sort"}
        out.append(op)
    return out


def apply(
    legs: List[Dict[str, Any]],
    ops: List[Dict[str, Any]],
    facets: Tuple[LegFacets, ...],
) -> Tuple[List[Dict[str, Any]], List[str], int]:
    """Mutate `legs` in place per `ops`.

    Returns (legs, rejected_labels, applied_count). `rejected_labels` are values
    the caller's facets never offered, so we had no token to write.
    """
    rejected: List[str] = []
    applied = 0

    for op in _normalise(ops):
        action = (op.get("action") or "").strip().lower()

        if action == "clear_all":
            for i in range(len(legs)):
                legs[i] = empty_filter()
            applied += 1
            continue

        field = op.get("field")
        if not field:
            continue

        for leg_index in _target_legs(op, len(legs)):
            leg = legs[leg_index]
            leg_facets = facets[leg_index] if leg_index < len(facets) else facets[0]

            if action == "clear":
                if field in RANGE_FIELDS:
                    leg[field] = {"Min": "", "Max": ""}
                elif field in LIST_FIELDS:
                    leg[field] = []
                elif field in BOOL_FIELDS:
                    leg[field] = False
                elif field in SCALAR_FIELDS:
                    leg[field] = ""
                applied += 1
                continue

            if field in BOOL_FIELDS:
                # Plain booleans - we can always honour these, no facet needed.
                leg[field] = True if op.get("flag") is None else bool(op.get("flag"))
                applied += 1
                continue

            if field in SCALAR_FIELDS:
                token = resolve_sort(op)
                if token is None:
                    continue
                leg[field] = token
                applied += 1
                continue

            if field in RANGE_FIELDS:
                payload, reason = resolve_range(field, op)
                if payload is None:
                    # Surface it the same way an out-of-facet value is surfaced,
                    # so a dropped bound is reported instead of vanishing when
                    # some other op in the same message succeeds.
                    if reason and reason not in rejected:
                        rejected.append(reason)
                    continue
                if action == "add" and isinstance(leg.get(field), dict):
                    merged = dict(leg[field])
                    for bound in ("Min", "Max"):
                        if payload.get(bound):
                            merged[bound] = payload[bound]
                    leg[field] = merged
                else:
                    leg[field] = payload
                applied += 1
                continue

            if action == "exclude" and field in LIST_FIELDS:
                if field not in EXCLUDABLE_FIELDS:
                    # Not expressible as an inclusion list - report it as
                    # unavailable rather than writing a filter that means
                    # something else. See EXCLUDABLE_FIELDS for why.
                    for label in op.get("values") or []:
                        if str(label) not in rejected:
                            rejected.append(str(label))
                    continue
                surviving, missed = resolve_exclusion(field, op, leg_facets)
                for label in missed:
                    if label not in rejected:
                        rejected.append(label)
                if not surviving:
                    # Either nothing resolved, or the user ruled out every
                    # option the route has. Neither is a filter we can write.
                    continue
                leg[field] = surviving
                applied += 1
                continue

            if field in LIST_FIELDS:
                if field in FACET_GATED_FIELDS:
                    accepted, missed = resolve_values(field, op, leg_facets)
                else:
                    # Stop: plain integers, so no vocabulary to check against.
                    accepted, missed = resolve_stops(op)
                for label in missed:
                    if label not in rejected:
                        rejected.append(label)
                if not accepted:
                    continue
                if action == "add":
                    existing = list(leg.get(field) or [])
                    for value in accepted:
                        if value not in existing:
                            existing.append(value)
                    leg[field] = existing
                else:
                    leg[field] = accepted
                applied += 1

    return legs, rejected, applied
