"""Verification 6 and 7: cumulative refinement and roundtrip leg targeting."""
from src.core.facets import parse
from src.core.merger import apply
from src.core.serializer import serialize
from src.schema.filter_json import as_legs, empty_filter

from tests.conftest import FACETS


def _legs(n=1):
    return [empty_filter() for _ in range(n)]


def _facets(n=1):
    return parse(FACETS if n == 1 else [FACETS, FACETS], roundtrip=n == 2)


def test_cumulative_refinement_keeps_earlier_filters():
    """"only indigo" -> "also morning" -> "drop the airline filter"."""
    legs, facets = _legs(), _facets()

    apply(legs, [{"action": "set", "field": "Airline", "values": ["IndiGo"]}], facets)
    assert legs[0]["Airline"] == ["IndiGo"]

    apply(legs, [{"action": "set", "field": "DepTime", "preset": "morning"}], facets)
    assert legs[0]["Airline"] == ["IndiGo"], "airline dropped when adding a second filter"
    assert legs[0]["DepTime"] == {"Min": "06:00", "Max": "12:00"}

    apply(legs, [{"action": "clear", "field": "Airline"}], facets)
    assert legs[0]["Airline"] == []
    assert legs[0]["DepTime"] == {"Min": "06:00", "Max": "12:00"}, "wrong field cleared"


def test_clear_all_restores_the_template():
    legs, facets = _legs(), _facets()
    apply(legs, [{"action": "set", "field": "Airline", "values": ["IndiGo"]}], facets)
    apply(legs, [{"action": "clear_all"}], facets)
    assert legs[0] == empty_filter()


def test_add_appends_without_duplicates():
    legs, facets = _legs(), _facets()
    apply(legs, [{"action": "set", "field": "Airline", "values": ["IndiGo"]}], facets)
    apply(legs, [{"action": "add", "field": "Airline", "values": ["Air India", "IndiGo"]}], facets)
    assert legs[0]["Airline"] == ["IndiGo", "Air India"]


def test_set_replaces_rather_than_appends():
    legs, facets = _legs(), _facets()
    apply(legs, [{"action": "set", "field": "Airline", "values": ["IndiGo"]}], facets)
    apply(legs, [{"action": "set", "field": "Airline", "values": ["SpiceJet"]}], facets)
    assert legs[0]["Airline"] == ["SpiceJet"]


def test_bool_fields_never_need_a_facet():
    """No facet exists for wifi/red-eye anywhere in the search response."""
    legs = _legs()
    facets = parse({"airline": "IndiGo"}, roundtrip=False)  # deliberately minimal
    _, rejected, applied = apply(
        legs,
        [
            {"action": "set", "field": "IsWifi", "flag": True},
            {"action": "set", "field": "Refundable", "flag": True},
            {"action": "set", "field": "IsRedEyes", "flag": True},
        ],
        facets,
    )
    assert applied == 3 and rejected == []
    assert legs[0]["IsWifi"] and legs[0]["Refundable"] and legs[0]["IsRedEyes"]


def test_roundtrip_op_defaults_to_both_legs():
    legs, facets = _legs(2), _facets(2)
    apply(legs, [{"action": "set", "field": "Airline", "values": ["IndiGo"]}], facets)
    assert legs[0]["Airline"] == ["IndiGo"] and legs[1]["Airline"] == ["IndiGo"]


def test_return_leg_targeting_leaves_outbound_untouched():
    """"return must land before noon" must not touch index 0."""
    legs, facets = _legs(2), _facets(2)
    apply(legs, [{"action": "set", "field": "ArrTime", "range_max": "12:00", "legs": [1]}], facets)

    assert legs[0]["ArrTime"] == {"Min": "", "Max": ""}
    assert legs[1]["ArrTime"] == {"Min": "", "Max": "12:00"}

    out = serialize(legs, roundtrip=True)
    assert out[0]["IsArrTime"] is False
    assert out[1]["IsArrTime"] is True


def test_outbound_leg_targeting():
    legs, facets = _legs(2), _facets(2)
    apply(legs, [{"action": "set", "field": "DepTime", "preset": "morning", "legs": [0]}], facets)
    assert legs[0]["DepTime"] == {"Min": "06:00", "Max": "12:00"}
    assert legs[1]["DepTime"] == {"Min": "", "Max": ""}


def test_per_leg_facets_are_respected():
    """The legs genuinely differ on real searches: a layover valid on the
    return leg must not resolve against the outbound leg."""
    outbound = dict(FACETS)
    inbound = dict(FACETS, layover=[{"value": "BHJ", "label": "Bhuj"}])
    facets = parse([outbound, inbound], roundtrip=True)
    legs = _legs(2)

    _, rejected, _ = apply(
        legs, [{"action": "set", "field": "Layover", "values": ["Bhuj"], "legs": [1]}], facets
    )
    assert legs[1]["Layover"] == ["BHJ"] and rejected == []

    legs2 = _legs(2)
    _, rejected2, applied2 = apply(
        legs2, [{"action": "set", "field": "Layover", "values": ["Bhuj"], "legs": [0]}], facets
    )
    assert legs2[0]["Layover"] == [] and rejected2 == ["Bhuj"] and applied2 == 0


def test_rejected_values_are_reported():
    legs, facets = _legs(), _facets()
    _, rejected, applied = apply(
        legs, [{"action": "set", "field": "Airline", "values": ["Vistara"]}], facets
    )
    assert rejected == ["Vistara"] and applied == 0
    assert legs[0]["Airline"] == []


def test_partial_application_keeps_what_landed():
    legs, facets = _legs(), _facets()
    _, rejected, applied = apply(
        legs,
        [
            {"action": "set", "field": "Price", "range_max": "10000"},
            {"action": "set", "field": "Airline", "values": ["Vistara"]},
        ],
        facets,
    )
    assert applied == 1 and rejected == ["Vistara"]
    assert legs[0]["Price"] == {"Min": "", "Max": "10000"}


def test_currentfilter_roundtrips_through_as_legs():
    legs, facets = _legs(), _facets()
    apply(legs, [{"action": "set", "field": "Airline", "values": ["IndiGo"]}], facets)
    emitted = serialize(legs, roundtrip=False)

    # Feed the emitted filter back in, as the caller would on the next turn.
    reloaded = as_legs(emitted, "oneway")
    apply(reloaded, [{"action": "set", "field": "IsWifi", "flag": True}], facets)
    assert reloaded[0]["Airline"] == ["IndiGo"]
    assert reloaded[0]["IsWifi"] is True


def test_sort_attached_to_the_wrong_op_is_recovered():
    """Models reliably express the sort but not always in its own op.
    Dropping it would lose a filter the user explicitly asked for."""
    legs, facets = _legs(), _facets()
    _, _, applied = apply(
        legs,
        [
            {"action": "set", "field": "Stop", "values": ["0"], "sort": "Cheapest"},
            {"action": "set", "field": "Price", "range_max": "8000"},
        ],
        facets,
    )
    assert legs[0]["Stop"] == [0]
    assert legs[0]["Price"] == {"Min": "", "Max": "8000"}
    assert legs[0]["SortBy"] == "Cheapest"
    assert applied == 3


def test_sort_on_its_own_op_still_works():
    legs, facets = _legs(), _facets()
    apply(legs, [{"action": "set", "field": "SortBy", "sort": "Fastest"}], facets)
    assert legs[0]["SortBy"] == "Fastest"


def test_clearing_sortby():
    legs, facets = _legs(), _facets()
    apply(legs, [{"action": "set", "field": "SortBy", "sort": "Fastest"}], facets)
    apply(legs, [{"action": "clear", "field": "SortBy"}], facets)
    assert legs[0]["SortBy"] == ""


def test_sort_is_global_not_per_leg():
    """A sort aimed at one leg still lands on both.

    The consuming API sorts the combined roundtrip, so one leg carrying
    "Cheapest" while the other carries "" would be incoherent.
    """
    legs, facets = _legs(2), _facets(2)
    ops = [{"action": "set", "field": "SortBy", "sort": "Cheapest", "legs": [0]}]
    legs, _, applied = apply(legs, ops, facets)
    assert applied
    assert legs[0]["SortBy"] == "Cheapest"
    assert legs[1]["SortBy"] == "Cheapest"


def test_clearing_sort_clears_both_legs():
    legs, facets = _legs(2), _facets(2)
    for leg in legs:
        leg["SortBy"] = "Cheapest"
    ops = [{"action": "clear", "field": "SortBy", "legs": [1]}]
    legs, _, _ = apply(legs, ops, facets)
    assert legs[0]["SortBy"] == ""
    assert legs[1]["SortBy"] == ""


def test_exclude_airline_keeps_every_other_option():
    legs, facets = _legs(), _facets()
    ops = [{"action": "exclude", "field": "Airline", "values": ["SpiceJet"]}]
    legs, rejected, applied = apply(legs, ops, facets)
    assert applied
    assert "SpiceJet" not in legs[0]["Airline"]
    assert "IndiGo" in legs[0]["Airline"]
    assert not rejected


def test_excluding_a_layover_sends_the_remaining_ones():
    """"i dont want bengaluru or kolkata" -> the layovers that are left.

    Note this also removes non-stop flights from the results, because the
    consuming API ANDs Layover. That trade is deliberate - see
    EXCLUDABLE_FIELDS.
    """
    legs, facets = _legs(), _facets()
    allowed = facets[0].allowed_values("layover")
    ops = [{"action": "exclude", "field": "Layover", "values": [allowed[0]]}]
    legs, rejected, applied = apply(legs, ops, facets)
    assert applied
    assert allowed[0] not in legs[0]["Layover"]
    assert legs[0]["Layover"] == allowed[1:]
    assert not rejected


def test_excluding_every_option_writes_nothing():
    legs, facets = _legs(), _facets()
    allowed = facets[0].allowed_values("airline")
    ops = [{"action": "exclude", "field": "Airline", "values": list(allowed)}]
    legs, _, applied = apply(legs, ops, facets)
    assert legs[0]["Airline"] == []
    assert applied == 0
