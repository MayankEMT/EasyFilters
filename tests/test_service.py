"""Verification 2, 3, 4, 9: the end-to-end contract, LLM stubbed."""
import pytest

from src.core.facets import FacetError
from src.schema.filter_json import empty_filter
from src.service import parse_message

pytestmark = pytest.mark.anyio
from src.utils import messages as msg


async def test_missing_facets_is_a_400(facets):
    for bad in (None, {}, []):
        with pytest.raises(FacetError):
            await parse_message("under 10k", "oneway", bad)


async def test_facets_with_no_usable_field_is_a_400():
    with pytest.raises(FacetError):
        await parse_message("under 10k", "oneway", {"somethingElse": [1, 2]})


async def test_no_filter_intent_returns_currentfilter_untouched(facets, stub_llm):
    """A plain search or a greeting must never wipe the active filters."""
    stub_llm({"has_filter_intent": False, "ops": []})

    active = empty_filter()
    active["Airline"] = ["IndiGo"]
    active["IsAirline"] = True

    result = await parse_message("delhi to mumbai tomorrow", "oneway", facets, current_filter=active)

    assert result["status"] == "no_match"
    assert result["message"] == msg.NO_FILTER_INTENT
    assert result["filter"]["Airline"] == ["IndiGo"], "active filter was wiped"
    assert result["filter"]["IsAirline"] is True


async def test_empty_message_short_circuits_without_calling_the_llm(facets):
    # No stub installed: if this reached the LLM it would fail on a missing key.
    result = await parse_message("   ", "oneway", facets)
    assert result["status"] == "no_match"
    assert result["message"] == msg.NO_FILTER_INTENT


async def test_intent_true_but_no_ops_is_no_match(facets, stub_llm):
    stub_llm({"has_filter_intent": True, "ops": []})
    result = await parse_message("hmm", "oneway", facets)
    assert result["status"] == "no_match"


async def test_value_outside_facets_returns_no_match_and_preserves_filter(facets, stub_llm):
    """The core safety property: we never invent a token we weren't given."""
    stub_llm(
        {
            "has_filter_intent": True,
            "ops": [{"action": "set", "field": "Airline", "values": ["Vistara", "Emirates"]}],
        }
    )
    active = empty_filter()
    active["Price"] = {"Min": "", "Max": "20000"}
    active["IsPrice"] = True

    result = await parse_message("only vistara and emirates", "oneway", facets, current_filter=active)

    assert result["status"] == "no_match"
    assert result["message"] == msg.NO_MATCH
    assert result["filter"]["Airline"] == []
    assert result["filter"]["IsAirline"] is False
    assert result["filter"]["Price"] == {"Min": "0", "Max": "20000"}, "filter was not preserved"


async def test_applied_filter_sets_flags(facets, stub_llm):
    stub_llm(
        {
            "has_filter_intent": True,
            "ops": [
                {"action": "set", "field": "Price", "range_max": "10000"},
                {"action": "set", "field": "Stop", "values": ["0"]},
                {"action": "set", "field": "Airline", "values": ["IndiGo"]},
            ],
        }
    )
    result = await parse_message("under 10k non-stop indigo", "oneway", facets)

    assert result["status"] == "applied"
    assert result["message"] == ""
    f = result["filter"]
    assert f["IsPrice"] and f["Price"] == {"Min": "0", "Max": "10000"}
    assert f["IsStop"] and f["Stop"] == [0]
    assert f["IsAirline"] and f["Airline"] == ["IndiGo"]


async def test_partial_application_applies_what_it_can(facets, stub_llm):
    stub_llm(
        {
            "has_filter_intent": True,
            "ops": [
                {"action": "set", "field": "Price", "range_max": "10000"},
                {"action": "set", "field": "Airline", "values": ["Vistara"]},
            ],
        }
    )
    result = await parse_message("under 10k on vistara", "oneway", facets)

    assert result["status"] == "applied"
    assert result["message"] == msg.PARTIAL
    assert result["message"] != msg.NO_MATCH, "partial must read differently from total failure"
    assert result["filter"]["Price"] == {"Min": "0", "Max": "10000"}
    assert result["filter"]["Airline"] == []


async def test_amenity_booleans_are_never_gated_by_facets(facets, stub_llm):
    stub_llm(
        {
            "has_filter_intent": True,
            "ops": [
                {"action": "set", "field": "IsWifi", "flag": True},
                {"action": "set", "field": "Refundable", "flag": True},
                {"action": "set", "field": "IsRedEyes", "flag": True},
            ],
        }
    )
    # Facets carry no amenity information at all - the live search has none.
    result = await parse_message("with wifi, refundable, red-eye", "oneway", facets)

    assert result["status"] == "applied"
    f = result["filter"]
    assert f["IsWifi"] is True and f["Refundable"] is True and f["IsRedEyes"] is True


async def test_roundtrip_returns_two_elements(rt_facets, stub_llm):
    stub_llm(
        {
            "has_filter_intent": True,
            "ops": [{"action": "set", "field": "ArrTime", "range_max": "12:00", "legs": [1]}],
        }
    )
    result = await parse_message("return should land before noon", "roundtrip", rt_facets)

    assert isinstance(result["filter"], list) and len(result["filter"]) == 2
    assert result["filter"][0]["IsArrTime"] is False
    assert result["filter"][1]["ArrTime"] == {"Min": "", "Max": "12:00"}


async def test_roundtrip_per_leg_facets(rt_facets, stub_llm):
    """Bhuj is a return-leg layover only; asking for it outbound must not stick."""
    stub_llm(
        {
            "has_filter_intent": True,
            "ops": [{"action": "set", "field": "Layover", "values": ["Bhuj"], "legs": [0]}],
        }
    )
    result = await parse_message("via bhuj on the way out", "roundtrip", rt_facets)
    assert result["status"] == "no_match"
    assert result["filter"][0]["Layover"] == []


async def test_clear_all(facets, stub_llm):
    stub_llm({"has_filter_intent": True, "ops": [{"action": "clear_all"}]})
    active = empty_filter()
    active["Airline"] = ["IndiGo"]
    active["IsAirline"] = True

    result = await parse_message("clear all filters", "oneway", facets, current_filter=active)
    assert result["status"] == "applied"
    assert result["filter"] == empty_filter()


async def test_provider_failure_never_becomes_a_500(facets, monkeypatch):
    """Text that mimics our own schema makes the provider refuse to call the
    tool. That must leave the caller's filters intact, not crash the endpoint."""
    import src.service as service

    class _Exploding:
        def invoke(self, _messages):
            raise RuntimeError("Tool choice is required, but model did not call a tool")

    monkeypatch.setattr(service, "get_structured_llm", lambda *a, **k: _Exploding())

    active = empty_filter()
    active["Airline"] = ["IndiGo"]
    active["IsAirline"] = True

    result = await parse_message("anything", "oneway", facets, current_filter=active)

    assert result["status"] == "no_match"
    assert result["filter"]["Airline"] == ["IndiGo"], "filters lost on provider failure"


async def test_missing_api_key_is_still_a_configuration_error(facets, monkeypatch):
    """A genuine misconfiguration must not hide behind the degrade path."""
    import src.service as service

    def _boom(*a, **k):
        raise ValueError("Groq API key is missing. Set GROQ_API_KEY.")

    monkeypatch.setattr(service, "get_structured_llm", _boom)
    with pytest.raises(ValueError, match="API key"):
        await parse_message("under 10k", "oneway", facets)


async def test_rejected_range_is_reported_alongside_a_successful_op(facets, stub_llm):
    stub_llm(
        {
            "has_filter_intent": True,
            "ops": [
                {"action": "set", "field": "Stop", "values": ["0"]},
                {"action": "set", "field": "Price", "range_max": "-5000"},
            ],
        }
    )
    result = await parse_message("non stop under -5000", "oneway", facets)
    assert result["status"] == "applied"
    assert result["filter"]["Stop"] == [0]
    assert result["filter"]["Price"] == {"Min": "", "Max": ""}
    assert result["message"] == msg.PARTIAL, "dropped bound vanished silently"


async def test_the_caller_cannot_choose_the_provider_or_model(facets, stub_llm, monkeypatch):
    """A public endpoint choosing our model means a public caller choosing our bill."""
    import src.service as service

    stub_llm({"has_filter_intent": True,
              "ops": [{"action": "set", "field": "Price", "range_max": "10000"}]})
    seen = {}
    original = service.get_structured_llm

    def _record(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "get_structured_llm", _record)
    result = await parse_message("under 10k", "oneway", facets)

    assert result["status"] == "applied"
    assert not seen["args"] and not seen["kwargs"], (
        "the caller's provider/model reached the LLM factory"
    )


async def test_a_failing_provider_falls_back_to_the_other(facets, monkeypatch):
    """A Groq rate limit used to read as "No filter change requested"."""
    import src.service as service
    from src.schema.patch import FilterOp, FilterPatch

    patch = FilterPatch(has_filter_intent=True,
                        ops=[FilterOp(action="set", field="Price", range_max="10000")])

    class _Primary:
        async def ainvoke(self, _messages):
            raise RuntimeError("429 rate limit exceeded")

    class _Backup:
        async def ainvoke(self, _messages):
            return patch

    calls = []

    def _factory(provider=None, llm_name=None):
        calls.append(provider)
        return _Backup() if provider else _Primary()

    monkeypatch.setattr(service, "get_structured_llm", _factory)
    monkeypatch.setattr(service, "fallback_provider", lambda: "openai")

    result = await parse_message("under 10k", "oneway", facets)
    assert result["status"] == "applied", "the fallback did not rescue the request"
    assert result["filter"]["Price"]["Max"] == "10000"
    assert calls == [None, "openai"], "the backup provider was not used"


async def test_with_no_fallback_configured_it_degrades_as_before(facets, monkeypatch):
    import src.service as service

    class _Dead:
        async def ainvoke(self, _messages):
            raise RuntimeError("429 rate limit exceeded")

    monkeypatch.setattr(service, "get_structured_llm", lambda *a, **k: _Dead())
    monkeypatch.setattr(service, "fallback_provider", lambda: None)

    result = await parse_message("under 10k", "oneway", facets)
    assert result["status"] == "no_match"
    assert result["filter"]["IsPrice"] is False


async def test_both_providers_failing_still_leaves_filters_untouched(facets, monkeypatch):
    import src.service as service

    active = {"IsAirline": True, "Airline": ["IndiGo"]}

    class _Dead:
        async def ainvoke(self, _messages):
            raise RuntimeError("boom")

    monkeypatch.setattr(service, "get_structured_llm", lambda *a, **k: _Dead())
    monkeypatch.setattr(service, "fallback_provider", lambda: "openai")

    result = await parse_message("under 10k", "oneway", facets, current_filter=active)
    assert result["status"] == "no_match"
    assert result["filter"]["Airline"] == ["IndiGo"], "the caller's filter was lost"
