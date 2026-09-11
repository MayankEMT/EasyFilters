"""What the LLM returns: a patch of ops against the current filter.

Ops rather than a whole filter, because regenerating the full object every turn
makes the model silently drop filters the user never mentioned. Ops also give
"remove the morning filter" and "reset everything" for free.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ACTIONS = ("set", "add", "clear", "clear_all")

OpField = Literal[
    "Price",
    "DepTime",
    "ArrTime",
    "Duration",
    "Stop",
    "Airline",
    "Layover",
    "AirCarftType",
    "TakeOffAirport",
    "LandingAirport",
    "Refundable",
    "IsWifi",
    "IsRedEyes",
    "SortBy",
]

SortValue = Literal[
    "Best",
    "Cheapest",
    "Fastest",
    "Early Take-off",
    "Late Take-off",
    "Early Arrival",
    "Late Arrival",
    "Slowest",
    "Highest Price",
]


class FilterOp(BaseModel):
    action: Literal["set", "add", "clear", "clear_all"] = Field(
        description=(
            "'set' replaces the field, 'add' appends to a list field, "
            "'clear' empties one field, 'clear_all' resets every filter."
        )
    )
    field: Optional[OpField] = Field(
        None, description="Which filter field this op targets. Omit only for clear_all."
    )
    values: Optional[List[str]] = Field(
        None,
        description=(
            "ONLY for list fields (Stop, Airline, Layover, AirCarftType, "
            "TakeOffAirport, LandingAirport). A flat array of strings, e.g. "
            '["IndiGo"]. Never an object, and never used for range fields.'
        ),
    )
    range_min: Optional[str] = Field(
        None,
        description=(
            "Lower bound for a range field (Price, Duration, DepTime, ArrTime). "
            "A single string: Price/Duration as a plain number ('10k' -> '10000'), "
            "DepTime/ArrTime as 'HH:MM' 24-hour ('6pm' -> '18:00')."
        ),
    )
    range_max: Optional[str] = Field(
        None, description="Upper bound for a range field. Same formats as range_min."
    )
    preset: Optional[str] = Field(
        None,
        description=(
            "A named time-of-day window for DepTime/ArrTime instead of min/max: "
            "early morning, morning, late morning, noon, afternoon, evening, "
            "night, late night, midnight, red eye."
        ),
    )
    sort: Optional[SortValue] = Field(
        None,
        description=(
            "For field=SortBy. Use this for comparative words instead of "
            "inventing a numeric bound: 'cheapest' -> 'Cheapest', 'quickest' -> "
            "'Fastest', 'earliest' -> 'Early Take-off', 'lands latest' -> "
            "'Late Arrival'."
        ),
    )
    flag: Optional[bool] = Field(
        None, description="For Refundable, IsWifi, IsRedEyes: the boolean to set."
    )
    legs: Optional[List[int]] = Field(
        None,
        description=(
            "Roundtrip only. [0] for the outbound/onward flight, [1] for the "
            "return/inbound flight, [0,1] or omitted for both."
        ),
    )


class FilterPatch(BaseModel):
    has_filter_intent: bool = Field(
        description=(
            "False when the message asks for no filter change at all - a plain "
            "search ('delhi to mumbai tomorrow'), passenger counts, a greeting, "
            "or thanks. True only when the user expresses a filter preference."
        )
    )
    ops: List[FilterOp] = Field(
        default_factory=list, description="The filter changes. Empty when has_filter_intent is false."
    )
