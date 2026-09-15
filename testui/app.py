"""Test harness for the Smart Flight Filter API.

Runs a real EaseMyTrip flight search, renders the listing the way the website
does, and lets you filter it by typing at a chat box instead of clicking chips.

Three services are stitched together here:

  search      tools_factory.flights.search_flights  (EMT_TOOLS_ECOSYSTEM)
  autosuggest emt_client.utils.fetch_autosuggest    (EMT_TOOLS_ECOSYSTEM)
  filtering   the Smart Filter API                  (EasyFilters)

Facets are computed from the search results, exactly as the website computes
its filter chips, and handed to the filter API as the closed vocabulary. That
is the whole point of the harness: it proves the round trip works against real
data rather than a fixture.
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).parent
# The flight search needs FLIGHT_ATK_TOKEN, which lives in the tools repo's own
# .env. Point TOOLS_DIR at your checkout if it is not a sibling of this repo.
TOOLS = Path(os.getenv("TOOLS_DIR", HERE.parent.parent / "EMT_TOOLS_ECOSYSTEM"))

load_dotenv(HERE / ".env")
load_dotenv(TOOLS / ".env", override=False)

from emt_client.clients.flight_client import FlightApiClient  # noqa: E402
from emt_client.utils import fetch_autosuggest  # noqa: E402
from tools_factory.flights.flight_search_service import search_flights  # noqa: E402

FILTER_API = os.getenv("FILTER_API", "http://aimltest1.easemytrip.com/api/smart-filter/parse")

app = FastAPI(title="Smart Filter - test harness")


# --------------------------------------------------------------------------
# result shaping
# --------------------------------------------------------------------------

def _minutes(journey_time: Any) -> Optional[int]:
    """'02h 15m' -> 135."""
    if not journey_time:
        return None
    text = str(journey_time)
    hours = re.search(r"(\d+)\s*h", text)
    mins = re.search(r"(\d+)\s*m", text)
    if not hours and not mins:
        return None
    return int(hours.group(1) or 0) * 60 + int(mins.group(1) or 0) if hours else int(mins.group(1))


def _hhmm(value: Any) -> Optional[int]:
    try:
        hh, mm = str(value).split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return None


AIRCRAFT_RE = re.compile(r"^(boeing|airbus|embraer|atr|alenia|bombardier)[ -]", re.I)


def _aircraft(flight: Dict[str, Any]) -> List[str]:
    """Aircraft descriptions hide in the raw segment, backtick-delimited.

    The same field also carries fare codes that happen to contain "ATR", so
    anchor the match at the start and drop anything with punctuation noise.
    """
    out: List[str] = []
    for seg in ((flight.get("_raw_seg") or {}).get("b") or []):
        for part in str(seg.get("BkKY") or "").split("`"):
            part = part.strip()
            if not part or "!" in part or len(part) > 60:
                continue
            if AIRCRAFT_RE.match(part) and part not in out:
                out.append(part)
    return out


def _price(flight: Dict[str, Any]) -> Optional[float]:
    fares = [f.get("total_fare") for f in (flight.get("fare_options") or [])]
    fares = [f for f in fares if isinstance(f, (int, float))]
    return min(fares) if fares else None


def shape(flight: Dict[str, Any]) -> Dict[str, Any]:
    legs = flight.get("legs") or []
    first, last = (legs[0] if legs else {}), (legs[-1] if legs else {})
    for leg in legs:
        # Layover facets read far better as "HYD:Hyderabad" than a bare code,
        # and the results already carry the city name.
        if leg.get("destination") and leg.get("destination_city"):
            CITY_NAMES.setdefault(leg["destination"], leg["destination_city"])
    return {
        "id": str(flight.get("segment_key") or flight.get("segment_id") or ""),
        "airlineName": first.get("airline_name") or "",
        "airlineCode": first.get("airline_code") or "",
        "flightNumber": "-".join(
            filter(None, [first.get("airline_code"), first.get("flight_number")])
        ),
        "origin": flight.get("origin"),
        "originCity": flight.get("origin_city"),
        "destination": flight.get("destination"),
        "destinationCity": flight.get("destination_city"),
        "departureTime": first.get("departure_time"),
        "arrivalTime": last.get("arrival_time"),
        "journeyTime": flight.get("journey_time"),
        "durationMinutes": _minutes(flight.get("journey_time")),
        "stops": flight.get("total_stops"),
        "layovers": [leg.get("destination") for leg in legs[:-1] if leg.get("destination")],
        "aircraft": _aircraft(flight),
        "refundable": bool(flight.get("is_refundable")),
        "price": _price(flight),
        "cabin": first.get("cabin"),
        "baggage": first.get("baggage"),
    }


CITY_NAMES: Dict[str, str] = {}


def build_facets(flights: List[Dict[str, Any]]) -> Dict[str, str]:
    """The five lists the filter API needs, derived from the results.

    Emitted as "CODE:Label" wherever the token differs from the word a person
    would say, which is exactly the form the contract asks callers to send.
    """
    airlines, layovers, aircraft, origins, destinations = [], [], [], [], []

    for f in flights:
        if f["airlineName"] and f["airlineName"] not in airlines:
            airlines.append(f["airlineName"])
        for code in f["layovers"]:
            token = f"{code}:{CITY_NAMES[code]}" if code in CITY_NAMES else code
            if token not in layovers:
                layovers.append(token)
        for kind in f["aircraft"]:
            if kind not in aircraft:
                aircraft.append(kind)
        origin = f"{f['origin']}:{f['originCity']}" if f.get("originCity") else f["origin"]
        if origin and origin not in origins:
            origins.append(origin)
        dest = (
            f"{f['destination']}:{f['destinationCity']}"
            if f.get("destinationCity") else f["destination"]
        )
        if dest and dest not in destinations:
            destinations.append(dest)

    facets = {
        "airline": ",".join(airlines),
        "layover": ",".join(layovers),
        "airCarftType": ",".join(aircraft),
        "takeOffAirport": ",".join(origins),
        "landingAirport": ",".join(destinations),
    }
    return {k: v for k, v in facets.items() if v}


def build_ranges(flights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bounds for the slider controls, and which stop counts actually exist.

    Separate from build_facets because the filter API does not want these - it
    needs no vocabulary for a number. They exist purely so the UI can draw a
    slider over the real range rather than a guessed one.
    """
    prices = [f["price"] for f in flights if f["price"] is not None]
    durations = [f["durationMinutes"] for f in flights if f["durationMinutes"]]
    return {
        "price": {"min": int(min(prices)), "max": int(max(prices))} if prices else None,
        "duration": {"min": min(durations), "max": max(durations)} if durations else None,
        "stops": sorted({f["stops"] for f in flights if f["stops"] is not None}),
    }


# --------------------------------------------------------------------------
# applying a filter
# --------------------------------------------------------------------------

SEARCH_NATIVE = {"Stop", "DepTime", "ArrTime", "Airline", "Refundable"}

SORTERS = {
    "Cheapest":       lambda f: (f["price"] is None, f["price"]),
    "Highest Price":  lambda f: (f["price"] is None, -(f["price"] or 0)),
    "Fastest":        lambda f: (f["durationMinutes"] is None, f["durationMinutes"]),
    "Slowest":        lambda f: (f["durationMinutes"] is None, -(f["durationMinutes"] or 0)),
    "Early Take-off": lambda f: (_hhmm(f["departureTime"]) is None, _hhmm(f["departureTime"])),
    "Late Take-off":  lambda f: (_hhmm(f["departureTime"]) is None, -(_hhmm(f["departureTime"]) or 0)),
    "Early Arrival":  lambda f: (_hhmm(f["arrivalTime"]) is None, _hhmm(f["arrivalTime"])),
    "Late Arrival":   lambda f: (_hhmm(f["arrivalTime"]) is None, -(_hhmm(f["arrivalTime"]) or 0)),
}


def search_kwargs(flt: Dict[str, Any]) -> Dict[str, Any]:
    """The parts of a filter the search API can apply itself."""
    kwargs: Dict[str, Any] = {}
    stops = flt.get("Stop") or []
    if len(stops) == 1:
        kwargs["stops"] = int(stops[0])
    if flt.get("IsDepTime"):
        lo, hi = flt["DepTime"].get("Min"), flt["DepTime"].get("Max")
        kwargs["departure_time_window"] = f"{lo or '00:00'}-{hi or '23:59'}"
    if flt.get("IsArrTime"):
        lo, hi = flt["ArrTime"].get("Min"), flt["ArrTime"].get("Max")
        kwargs["arrival_time_window"] = f"{lo or '00:00'}-{hi or '23:59'}"
    if flt.get("IsAirline"):
        kwargs["airline_names"] = list(flt["Airline"])
    if flt.get("Refundable"):
        kwargs["refundable"] = True
    if flt.get("SortBy") == "Fastest":
        kwargs["fastest"] = True
    return kwargs


def post_filter(flights: List[Dict[str, Any]], flt: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Everything the search API has no parameter for.

    Price, duration, layover, aircraft, the two airport fields, red-eye and the
    sort orders other than fastest. Kept deliberately separate from
    search_kwargs so it is obvious which half of the filter came from where.
    """
    out = list(flights)

    def bound(value):
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    if flt.get("IsPrice"):
        lo, hi = bound(flt["Price"].get("Min")), bound(flt["Price"].get("Max"))
        if lo is not None:
            out = [f for f in out if f["price"] is not None and f["price"] >= lo]
        if hi is not None:
            out = [f for f in out if f["price"] is not None and f["price"] <= hi]

    if flt.get("IsDuration"):
        lo, hi = bound(flt["Duration"].get("Min")), bound(flt["Duration"].get("Max"))
        if lo is not None:
            out = [f for f in out if f["durationMinutes"] and f["durationMinutes"] >= lo]
        if hi is not None:
            out = [f for f in out if f["durationMinutes"] and f["durationMinutes"] <= hi]

    if flt.get("IsStop") and len(flt.get("Stop") or []) > 1:
        wanted = {int(s) for s in flt["Stop"]}
        out = [f for f in out if f["stops"] in wanted]

    if flt.get("IsLayover"):
        # Matches the live site: choosing a layover returns only flights routed
        # through it, so a non-stop flight does not survive this filter.
        wanted = set(flt["Layover"])
        out = [f for f in out if wanted & set(f["layovers"])]

    if flt.get("IsAirCarftType"):
        wanted = set(flt["AirCarftType"])
        out = [f for f in out if wanted & set(f["aircraft"])]

    if flt.get("IsTakeOffAirport"):
        out = [f for f in out if f["origin"] in set(flt["TakeOffAirport"])]

    if flt.get("IsLandingAirport"):
        out = [f for f in out if f["destination"] in set(flt["LandingAirport"])]

    if flt.get("IsRedEyes"):
        # No red-eye field exists in the search response, so the harness infers
        # it from the departure time. The real site computes this elsewhere.
        def red(f):
            m = _hhmm(f["departureTime"])
            return m is not None and (m >= 21 * 60 or m <= 5 * 60)
        out = [f for f in out if red(f)]

    sorter = SORTERS.get(flt.get("SortBy") or "")
    if sorter:
        out = sorted(out, key=sorter)

    return out


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

class SearchRequest(BaseModel):
    origin: str = "DEL"
    destination: str = "BOM"
    date: str
    returnDate: Optional[str] = None
    adults: int = 1
    children: int = 0
    infants: int = 0
    cabin: Optional[str] = None
    filter: Optional[Any] = None


class ChatRequest(BaseModel):
    message: str
    tripType: str = "oneway"
    facets: Any
    currentFilter: Optional[Any] = None


@app.get("/api/suggest")
async def suggest(q: str):
    if len(q.strip()) < 2:
        return {"results": []}
    client = FlightApiClient()
    try:
        raw = await fetch_autosuggest(client, q.strip())
    except Exception as exc:
        raise HTTPException(502, f"autosuggest failed: {exc}") from exc
    results = []
    for item in raw or []:
        # No Code field: it is "Navi Mumbai(NMI)" in City, "NMI-Navi Mumbai" in
        # ShowCity. Prefer the ShowCity prefix, fall back to the bracket.
        show = str(item.get("ShowCity") or "")
        code = show.split("-")[0].strip() if "-" in show else ""
        if not re.fullmatch(r"[A-Z]{3}", code):
            match = re.search(r"\(([A-Z]{3})\)", str(item.get("City") or ""))
            code = match.group(1) if match else ""
        if not code:
            continue
        city = item.get("CityName") or str(item.get("City") or "").split("(")[0].strip()
        if city:
            CITY_NAMES[code] = city
        results.append({"code": code, "city": city, "name": item.get("AirportName") or ""})
    return {"results": results[:8]}


@app.post("/api/search")
async def search(req: SearchRequest):
    flt = req.filter
    leg0 = (flt[0] if isinstance(flt, list) else flt) or {}
    kwargs = search_kwargs(leg0) if leg0 else {}

    try:
        raw = await search_flights(
            origin=req.origin,
            destination=req.destination,
            outbound_date=req.date,
            return_date=req.returnDate,
            adults=req.adults,
            children=req.children,
            infants=req.infants,
            cabin=req.cabin,
            use_short_links=False,
            **kwargs,
        )
    except Exception as exc:
        raise HTTPException(502, f"search failed: {exc}") from exc

    outbound = [shape(f) for f in (raw.get("outbound_flights") or [])]
    inbound = [shape(f) for f in (raw.get("return_flights") or [])]

    # Facets come from the UNFILTERED result set, the way the site's chips do -
    # otherwise each filter would shrink the vocabulary the next prompt can use.
    facets_source = req.filter is None
    payload = {
        "outbound": post_filter(outbound, leg0) if leg0 else outbound,
        "inbound": inbound,
        "totals": {"outbound": len(outbound), "inbound": len(inbound)},
        "appliedVia": {
            "searchApi": sorted(kwargs.keys()),
            "harness": [k for k in ("IsPrice", "IsDuration", "IsLayover", "IsAirCarftType",
                                    "IsTakeOffAirport", "IsLandingAirport", "IsRedEyes")
                        if leg0.get(k)] + (["SortBy"] if leg0.get("SortBy") else []),
        },
    }
    if facets_source:
        payload["facets"] = build_facets(outbound)
        if inbound:
            payload["facets"] = [build_facets(outbound), build_facets(inbound)]
        payload["ranges"] = build_ranges(outbound)
    return payload


@app.post("/api/chat")
async def chat(req: ChatRequest):
    body = {
        "message": req.message,
        "tripType": req.tripType,
        "facets": req.facets,
        "currentFilter": req.currentFilter,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        try:
            resp = await client.post(FILTER_API, json=body)
        except Exception as exc:
            raise HTTPException(502, f"filter API unreachable: {exc}") from exc
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
