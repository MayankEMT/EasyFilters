"""HTTP-level checks: auth, the 400 on missing facets, and the response shape."""
import pytest
from fastapi.testclient import TestClient

import main
import src.routes.filter_routes as routes
import src.service as service
from src.schema.patch import FilterPatch

from tests.conftest import FACETS


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def patched_llm(monkeypatch):
    def _install(payload):
        patch = FilterPatch.model_validate(payload)

        class _Stub:
            async def ainvoke(self, _messages):
                return patch

        monkeypatch.setattr(service, "get_structured_llm", lambda *a, **k: _Stub())

    return _install


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_facets_returns_400(client):
    for body in (
        {"message": "under 10k", "tripType": "oneway"},
        {"message": "under 10k", "tripType": "oneway", "facets": {}},
        {"message": "under 10k", "tripType": "oneway", "facets": None},
    ):
        response = client.post("/api/smart-filter/parse", json=body)
        assert response.status_code == 400, response.text
        assert "facets" in response.json()["detail"]


def test_unknown_field_is_rejected(client):
    response = client.post(
        "/api/smart-filter/parse",
        json={"message": "hi", "facets": FACETS, "surprise": 1},
    )
    assert response.status_code == 422


def test_no_auth_header_required(client, patched_llm):
    """The endpoint is unauthenticated by design - no x-api-token."""
    patched_llm({"has_filter_intent": True, "ops": [{"action": "set", "field": "Stop", "values": ["0"]}]})
    response = client.post(
        "/api/smart-filter/parse", json={"message": "non stop", "facets": FACETS}
    )
    assert response.status_code == 200
    assert response.json()["filter"]["Stop"] == [0]


def test_successful_parse_shape(client, patched_llm):
    patched_llm(
        {
            "has_filter_intent": True,
            "ops": [{"action": "set", "field": "Price", "range_max": "10000"}],
        }
    )
    response = client.post(
        "/api/smart-filter/parse",
        json={"message": "give me flight under 10k", "tripType": "oneway", "facets": FACETS},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # Exactly three fields, nothing more.
    assert set(body.keys()) == {"status", "filter", "message"}
    assert body["status"] == "applied"
    assert body["filter"]["IsPrice"] is True
    assert body["filter"]["Price"] == {"Min": "0", "Max": "10000"}
    assert len(body["filter"]) == 25
