"""Orchestrates one parse request: facets -> LLM -> resolve -> merge -> serialize."""
import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Tuple

import yaml

from src.core import facets as facets_mod
from src.core.merger import apply as apply_ops
from src.core.serializer import serialize
from src.llm.client import get_structured_llm
from src.schema.filter_json import as_legs, is_roundtrip
from src.utils import messages as msg

logger = logging.getLogger(__name__)

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "filter.yml")


@lru_cache(maxsize=1)
def _prompt() -> Dict[str, str]:
    with open(PROMPT_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _describe_vocabulary(legs: Tuple[facets_mod.LegFacets, ...]) -> str:
    lines: List[str] = []
    for index, leg in enumerate(legs):
        if len(legs) > 1:
            lines.append(f"  leg {index} ({'outbound' if index == 0 else 'return'}):")
        vocab = leg.prompt_vocabulary()
        if not vocab:
            lines.append("    (none)")
            continue
        for key, values in vocab.items():
            shown = ", ".join(values[:60])
            lines.append(f"    {key}: {shown}")
    return "\n".join(lines) or "  (none)"


def _describe_active(legs: List[Dict[str, Any]]) -> str:
    """Only the fields actually set, so the model sees a short, honest summary."""
    from src.schema.filter_json import BOOL_FIELDS, LIST_FIELDS, RANGE_FIELDS

    lines: List[str] = []
    for index, leg in enumerate(legs):
        parts: List[str] = []
        for field in RANGE_FIELDS:
            payload = leg.get(field) or {}
            if payload.get("Min") or payload.get("Max"):
                parts.append(f"{field}={payload.get('Min') or '*'}..{payload.get('Max') or '*'}")
        for field in LIST_FIELDS:
            if leg.get(field):
                parts.append(f"{field}={leg[field]}")
        for field in BOOL_FIELDS:
            if leg.get(field):
                parts.append(f"{field}=true")
        prefix = f"  leg {index}: " if len(legs) > 1 else "  "
        lines.append(prefix + (", ".join(parts) if parts else "(no filters set)"))
    return "\n".join(lines)


def parse_message(
    message: str,
    trip_type: str,
    raw_facets: Any,
    current_filter: Any = None,
    provider: str = None,
    model: str = None,
) -> Dict[str, Any]:
    """Turn a chat message into the filter JSON.

    Raises facets_mod.FacetError when facets are missing or unusable.
    """
    roundtrip = is_roundtrip(trip_type)
    leg_facets = facets_mod.parse(raw_facets, roundtrip)
    legs = as_legs(current_filter, trip_type)

    text = (message or "").strip()
    if not text:
        return {
            "status": "no_match",
            "filter": serialize(legs, roundtrip),
            "message": msg.NO_FILTER_INTENT,
        }

    prompt = _prompt()
    user_block = prompt["user"].format(
        trip_type="roundtrip" if roundtrip else "oneway",
        vocabulary=_describe_vocabulary(leg_facets),
        active=_describe_active(legs),
        message=text,
    )

    llm = get_structured_llm(provider, model)
    try:
        patch = llm.invoke([("system", prompt["system"]), ("human", user_block)])
    except Exception:
        # A message can make the provider refuse to call the tool at all - text
        # that mimics our own schema does it reliably. Never let that reach the
        # caller as a 500: leave their filters untouched and say nothing changed.
        # Missing keys / bad provider names raise ValueError earlier, from
        # LLMFactory, and are still reported as a configuration fault.
        logger.warning("filter extraction failed for message=%r", text[:200], exc_info=True)
        return {
            "status": "no_match",
            "filter": serialize(legs, roundtrip),
            "message": msg.NO_FILTER_INTENT,
        }

    if patch is None or not getattr(patch, "has_filter_intent", False):
        return {
            "status": "no_match",
            "filter": serialize(legs, roundtrip),
            "message": msg.NO_FILTER_INTENT,
        }

    ops = [op.model_dump(exclude_none=True) for op in (patch.ops or [])]
    if not ops:
        return {
            "status": "no_match",
            "filter": serialize(legs, roundtrip),
            "message": msg.NO_FILTER_INTENT,
        }

    legs, rejected, applied = apply_ops(legs, ops, leg_facets)

    if applied == 0:
        # Nothing landed - every requested option was outside the facets, so we
        # have no token to write. Leave the caller's filters untouched.
        return {
            "status": "no_match",
            "filter": serialize(as_legs(current_filter, trip_type), roundtrip),
            "message": msg.NO_MATCH,
        }

    return {
        "status": "applied",
        "filter": serialize(legs, roundtrip),
        # Partial application: some preferences landed, at least one did not.
        "message": msg.PARTIAL if rejected else "",
    }
