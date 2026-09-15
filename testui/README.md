# Smart Filter — test harness

A local page that runs a real EaseMyTrip flight search and lets you filter the
results either by clicking chips or by typing. It exists to exercise the Smart
Filter API end to end against live data.

It sits inside this repo for convenience, but it is **not part of the service**.
It is a separate app with its own entry point, it talks to the filter API over
HTTP like any other caller, and nothing under `src/` imports it. Its
dependencies (`tools_factory`, `emt_client`) must never be added to the
project's `pyproject.toml` - keeping the API free of them is deliberate.

## Run

    run.bat

then open http://127.0.0.1:8600

It borrows `emt-chatbot/.venv`, which already has `tools_factory`, `emt_client`,
`fastapi` and `uvicorn`. Nothing to install.

## What talks to what

| Piece | Source |
|---|---|
| Flight search | `tools_factory.flights.search_flights` (EMT_TOOLS_ECOSYSTEM) |
| Airport autosuggest | `emt_client.utils.fetch_autosuggest` |
| Filter parsing | Smart Filter API — `FILTER_API`, defaults to the dev VM |

Point it at a local filter API instead:

    set FILTER_API=http://127.0.0.1:8000/api/smart-filter/parse

## The filter panel and the chat share one state

`state.filter` in the page is the single source of truth, and it is the exact
25-key JSON the API speaks. Ticking a checkbox edits it; a chat reply replaces
it; both then redraw the panel and re-run the search. Whatever you have ticked
is sent as `currentFilter` on the next prompt, so "also make it morning" builds
on your clicks rather than starting over.

On a roundtrip the panel edits the outbound leg; the chat still targets either
leg correctly.

## How filtering works

Facets are computed from the **unfiltered** search results, the way the website
builds its filter chips, and sent to the filter API as the closed vocabulary.

The returned filter JSON is applied in two halves, and the UI shows which half
did what under the result count:

- **search api** — `Stop`, `DepTime`, `ArrTime`, `Airline`, `Refundable`, and
  `Fastest`, passed as parameters to `search_flights`.
- **harness** — `Price`, `Duration`, `Layover`, `AirCarftType`,
  `TakeOffAirport`, `LandingAirport`, `IsRedEyes` and the other sort orders,
  applied to the returned rows because the search API has no parameter for them.

Two knowingly imperfect bits, both called out in `app.py`:

- `IsRedEyes` is inferred from departure time (21:00–05:00); the search response
  carries no red-eye field.
- `IsWifi` is ignored for the same reason.
