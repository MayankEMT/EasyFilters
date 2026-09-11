import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# Real facet values, read off a live DEL->BOM search.
# Real values, read off a live DEL->BOM search, in the shape the caller sends:
# a comma-separated string per field. No ranges and no stop list - comparatives
# set SortBy, and a stop count is a plain integer.
FACETS = {
    "airline": "IndiGo,Air India,AkasaAir,Air India Express,SpiceJet",
    "layover": "HYD,BLR,AMD,CCU,MAA",
    "airCarftType": "Boeing 737 (Narrow-body),Airbus A320 (Narrow-body),Airbus 32L",
    "takeOffAirport": "DEL,DXN,HDO",
    "landingAirport": "BOM,NMI",
}


@pytest.fixture
def facets():
    return dict(FACETS)


@pytest.fixture
def rt_facets():
    """Two legs with genuinely different layover sets, as the live API returns."""
    outbound = dict(FACETS)
    inbound = dict(FACETS, layover="BHJ,IXR")
    return [outbound, inbound]


@pytest.fixture
def stub_llm(monkeypatch):
    """Replace the LLM with a canned FilterPatch, so the deterministic layers
    are tested without a network call."""
    from src.schema.patch import FilterPatch
    import src.service as service

    def _install(payload):
        patch = FilterPatch.model_validate(payload)

        class _Stub:
            def invoke(self, _messages):
                return patch

        monkeypatch.setattr(service, "get_structured_llm", lambda *a, **k: _Stub())
        return patch

    return _install
