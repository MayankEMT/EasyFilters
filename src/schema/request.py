"""Request and response models for the parse endpoint."""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class FilterParseRequest(BaseModel):
    message: str = Field(
        description="The raw user chat message, unmodified. Do not pre-clean or pre-extract."
    )
    trip_type: Literal["oneway", "roundtrip"] = Field(
        "oneway",
        alias="tripType",
        description="Decides whether the filter is one object or a two-element array.",
    )
    facets: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = Field(
        None,
        description=(
            "Required. The same option lists the site already computes to render "
            "filter chips. A two-element array for roundtrip."
        ),
    )
    current_filter: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = Field(
        None,
        alias="currentFilter",
        description="The previous response's `filter`, for cumulative refinement.",
    )
    provider: Optional[str] = Field(
        None, description="Override the LLM provider for this call: groq or openai."
    )
    model: Optional[str] = Field(None, description="Override the model name for this call.")

    model_config = ConfigDict(populate_by_name=True, extra="forbid", protected_namespaces=())


class FilterParseResponse(BaseModel):
    status: Literal["applied", "no_match"]
    filter: Union[Dict[str, Any], List[Dict[str, Any]]]
    message: str = ""
