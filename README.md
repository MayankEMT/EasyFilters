# EasyFilters — Smart Flight Filter API

Turns a traveller's chat message into the flight-filter JSON the listing page
already consumes.

```
"give me flight under 10k, non-stop indigo"
        |
        v
{ "IsPrice": true, "Price": {"Min":"","Max":"10000"},
  "IsStop": true,  "Stop": [0],
  "IsAirline": true, "Airline": ["6E"], ... }
```

That is the entire job. This service does **not** run the search, apply the
filter, count results, or render chips — the caller owns all of that.

## Run it

```bash
uv sync
cp .env.example .env        # fill in GROQ_API_KEY
uv run uvicorn main:app --reload --port 8000
uv run pytest               # 80 tests, no network required
```

## `POST /api/smart-filter/parse`

No auth header — the endpoint is unauthenticated by design.

```jsonc
{
  "message": "give me flight under 10k, non-stop indigo",  // raw chat, unmodified
  "tripType": "oneway",          // "oneway" | "roundtrip"
  "currentFilter": null,         // previous response's `filter`, for refinement
  "facets": {                    // REQUIRED -> 400 without it
    "price":          { "min": 6270.0, "max": 44266.0 },
    "duration":       { "min": "02h 00m", "max": "22h 35m" },
    "depTime":        { "min": "00:05", "max": "23:50" },
    "arrTime":        { "min": "00:05", "max": "23:55" },
    "stop":           [0, 1],
    "airline":        [{ "value": "6E", "label": "IndiGo" }],
    "layover":        [{ "value": "HYD", "label": "Hyderabad" }],
    "airCarftType":   [{ "value": "Boeing 737 (Narrow-body)" }],
    "takeOffAirport": [{ "value": "DEL", "label": "New Delhi" }],
    "landingAirport": [{ "value": "BOM", "label": "Mumbai" }]
  }
}
```

Response — three fields, always:

```jsonc
{
  "status": "applied",   // "applied" | "no_match"
  "filter": { /* the full 25-key filter; a 2-element array for roundtrip */ },
  "message": ""          // populated only when status is "no_match"
}
```

Handling it: if `status` is `"applied"`, drop `filter` into the existing filter
call. If `"no_match"`, show `message` and leave the current filters alone —
`filter` comes back as whatever `currentFilter` you sent, never wiped.

## Why `facets` is mandatory

Six fields have no fixed vocabulary — `Stop`, `Airline`, `Layover`,
`AirCarftType`, `TakeOffAirport`, `LandingAirport`. Their valid values exist only
*after* a search runs, which is why the site renders those chips post-search.

`facets` is the closed vocabulary for those fields: **whatever you put in an
entry's `value` is exactly what comes back in the filter array.** `label` is only
matching material for the model. So "indigo", "IndiGo" and "6E" all resolve to
whichever token *you* supplied — the service can never guess `"Vistara"` when
the API wants `"UK"`, and can never emit an option your result set lacks.

Send `facets` as a **two-element array** `[outbound, return]` for round trips.
This matters: on a live `DEL→BOM` round-trip the legs genuinely differ — the
outbound offered layovers `BEK`/`CCU`/`MAA` the return lacked, the return offered
`BHJ`/`IXR` the outbound lacked, and price ranges were ₹6,270–44,266 vs
₹5,980–26,195.

You do **not** send: amenity hints, route/date/passenger info, search results,
session or user id, or chat history.

## What sets `no_match`

Only two things:

1. The value asked for is not in the `facets` you sent — we have no token to
   write. → *"No flights match this preference."*
2. The message carries no filter intent at all (`"delhi to mumbai tomorrow"`,
   `"thanks!"`). → *"No filter change requested."*

It never fires as a prediction about result counts. `"under 2k"` on a route
starting at ₹6,270 is emitted verbatim as `Price.Max = "2000"` — not clamped,
not second-guessed. You run the filter and own that outcome.

When a message mixes available and unavailable preferences (`"under 10k on
vistara"`), the available part applies, `status` stays `"applied"`, and `message`
reports the miss.

## Cumulative refinement

Stateless — send the previous `filter` back as `currentFilter`:

| turn | message | result |
|---|---|---|
| 1 | "only indigo" | `Airline: ["6E"]` |
| 2 | "also morning" | `Airline: ["6E"]` **+** `DepTime: 06:00–12:00` |
| 3 | "drop the airline filter" | `DepTime` kept, `Airline` cleared |
| 4 | "clear all filters" | back to the empty template |

## `SortBy`

Comparative words set `SortBy` rather than fabricating a numeric bound —
"cheapest" means *sort by price*, not *filter out mid-priced flights*. A sort and
a filter can both apply: "non-stop under 8k, cheapest first" yields `Stop: [0]`,
`Price.Max: "8000"` and `SortBy: "Cheapest"`.

| value | from phrasing like |
|---|---|
| `RECOMMENDED` | best, recommended |
| `CHEAPEST` | cheapest, lowest price, budget |
| `HIGHEST_PRICE` | most expensive, premium |
| `FASTEST` | fastest, shortest, quickest |
| `LONGEST` | longest |
| `FEWEST_STOPS` | fewest stops, prefer direct |
| `EARLIEST_DEPARTURE` | earliest, first flight |
| `LATEST_DEPARTURE` | latest, last flight |
| `EARLIEST_ARRIVAL` | lands earliest |
| `LATEST_ARRIVAL` | lands latest |

These tokens are defined in `SORT_VALUES` in `src/schema/filter_json.py`.
**They are our invention** — confirm the filter API accepts these exact strings
and re-spell them in that one constant if not.

## Output formats (confirmed)

| Field | Emitted as | Note |
|---|---|---|
| `Airline` | whatever the facet's `value` held | echoed verbatim |
| `Layover` / `TakeOffAirport` / `LandingAirport` | facet `value` | echoed verbatim |
| `AirCarftType` | facet `value` | echoed verbatim, e.g. `"Boeing 737 (Narrow-body)"` |
| `Stop` | **integers** — `[0, 1]` | int type preserved from the facet |
| `Price` | **string** — `"10000"` | `Min`/`Max`, `""` when unset |
| `Duration` | **string minutes** — `"135"` | facets still *arrive* as `"02h 15m"` |
| `DepTime` / `ArrTime` | `"HH:MM"` 24-hour | |
| `SortBy` | the chip label — `"Cheapest"`, `"Early Take-off"` | one value only |

`Duration` is the one asymmetric field: the search response gives `"02h 15m"`,
so that is what facets carry, but the filter takes plain minutes — so `"3h"`,
`"02h 15m"` and `"180"` all leave as a minute count.

### Time windows wrap past midnight

`Min > Max` on a time range is intentional and handled by the filter API:

| phrase | emitted |
|---|---|
| night | `21:00 – 03:00` |
| late night | `23:00 – 04:00` |
| midnight | `23:00 – 01:00` |
| red eye | `00:00 – 05:00` |

Don't normalise these into ascending order — `21:00–24:00` silently drops the
small hours a traveller asking for a night flight actually means. The inverted-
range rejection applies to `Price` and `Duration` only, never time fields.

Every format conversion lives in `src/core/resolver.py` and
`src/core/serializer.py` alone, so changing one is a one-file edit.

## Layout

```
main.py                     FastAPI app
src/routes/filter_routes.py the endpoint + token auth
src/service.py              orchestration: facets -> LLM -> resolve -> merge -> serialize
src/core/facets.py          validate + index the caller's facets (the closed vocabulary)
src/core/resolver.py        normalise bounds, presets, sort tokens
src/core/merger.py          apply ops onto currentFilter, per leg
src/core/serializer.py      emit the filter JSON; the ONLY place Is* flags are computed
src/schema/filter_json.py   the output template + field metadata + SORT_VALUES
src/schema/patch.py         what the LLM returns
src/prompts/filter.yml      system prompt
```

Two design rules worth keeping: every `Is*` flag is derived in `serializer.py`
and nowhere else (a populated `Stop: [0]` beside `IsStop: false` is the most
likely bug in a service like this), and the model returns *ops* against the
current filter rather than a whole filter, so it cannot silently drop a filter
the user never mentioned.
