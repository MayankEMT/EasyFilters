"""The single endpoint: chat message in, filter JSON out."""
import logging

from fastapi import APIRouter, HTTPException

from src.core.facets import FacetError
from src.schema.request import FilterParseRequest, FilterParseResponse
from src.service import parse_message

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/smart-filter/parse", response_model=FilterParseResponse)
async def parse_filter(req: FilterParseRequest):
    try:
        result = await parse_message(
            message=req.message,
            trip_type=req.trip_type,
            raw_facets=req.facets,
            current_filter=req.current_filter,
        )
    except FacetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        # Misconfigured provider / missing API key.
        logger.exception("smart-filter configuration error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result


@router.get("/health")
async def health():
    return {"status": "ok"}
