"""The single endpoint: chat message in, filter JSON out."""
import logging

from fastapi import APIRouter, HTTPException

from src.core.facets import FacetError
from src.schema.request import FilterParseRequest, FilterParseResponse
from src.service import parse_message

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/smart-filter/parse", response_model=FilterParseResponse)
def parse_filter(req: FilterParseRequest):
    """Deliberately sync, not async.

    parse_message blocks for the whole LLM call - a second or two. Declared
    `async def`, that blocks the event loop and the worker serves exactly one
    request at a time. Declared `def`, FastAPI runs it in a threadpool and the
    worker handles many at once.
    """
    try:
        result = parse_message(
            message=req.message,
            trip_type=req.trip_type,
            raw_facets=req.facets,
            current_filter=req.current_filter,
            provider=req.provider,
            model=req.model,
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
