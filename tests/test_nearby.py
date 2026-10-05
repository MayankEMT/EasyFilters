"""The searched sector, and the "hide nearby airports" intent it enables.

A metro search returns several airports (DEL also brings Noida and Ghaziabad),
so the listing page offers a chip to keep only the one that was searched. The
phrase names no airport, so the model cannot supply a code - the caller's own
`from`/`to` facets are the only source, which is what these cover.
"""
import pytest

from src.core.facets import LegFacets, parse
from src.core.merger import apply
from src.core.serializer import serialize
from src.schema.filter_json import empty_filter

from tests.conftest import FACETS


def _legs(n=1):
    return [empty_filter() for _ in range(n)]


def _hide(legs=None):
    return [{"action": "set", "field": "NearbyAirports", "flag": False, "legs": legs}]


def _show(legs=None):
    return [{"action": "set", "field": "NearbyAirports", "flag": True, "legs": legs}]


# ---------------------------------------------------------------- facets


@pytest.mark.parametrize("raw_from", ["DEL", "DEL:New Delhi"])
def test_sector_accepts_a_bare_code_or_code_label(raw_from):
    leg = LegFacets(dict(FACETS, **{"from": raw_from, "to": "BOM:Mumbai"}))
    assert leg.sector == {"from": "DEL", "to": "BOM"}


def test_origin_and_destination_are_accepted_as_aliases():
    leg = LegFacets(dict(FACETS, origin="DEL", destination="BOM"))
    assert leg.sector == {"from": "DEL", "to": "BOM"}


def test_a_sector_alone_is_not_usable_facets():
    """It is context, not a vocabulary - the 400 for empty facets must hold."""
    assert LegFacets({"from": "DEL", "to": "BOM"}).has_any() is False
    with pytest.raises(Exception):
        parse({"from": "DEL", "to": "BOM"}, roundtrip=False)


def test_sector_airport_uses_the_callers_own_spelling():
    """DEL resolves through the airport list so the token matches the rest."""
    leg = LegFacets(dict(FACETS, takeOffAirport="DEL:New Delhi,DXN:Noida", **{"from": "new delhi"}))
    assert leg.sector_airport("from") == "DEL"


def test_sector_airport_falls_back_when_no_airport_list_was_sent():
    leg = LegFacets({"airline": "IndiGo", "from": "DEL", "to": "BOM"})
    assert leg.sector_airport("from") == "DEL"


# ---------------------------------------------------------------- merger


def test_hiding_nearby_airports_uses_the_searched_sector():
    legs = _legs()
    facets = parse(dict(FACETS, **{"from": "DEL", "to": "BOM"}), roundtrip=False)
    legs, rejected, applied = apply(legs, _hide(), facets)
    assert applied
    assert legs[0]["TakeOffAirport"] == ["DEL"]
    assert legs[0]["LandingAirport"] == ["BOM"]
    assert not rejected


def test_showing_nearby_airports_clears_both_ends():
    legs = _legs()
    legs[0]["TakeOffAirport"], legs[0]["LandingAirport"] = ["DEL"], ["BOM"]
    facets = parse(dict(FACETS, **{"from": "DEL", "to": "BOM"}), roundtrip=False)
    legs, _, applied = apply(legs, _show(), facets)
    assert applied
    assert legs[0]["TakeOffAirport"] == []
    assert legs[0]["LandingAirport"] == []


def test_without_a_sector_the_request_is_reported_not_silently_dropped():
    """Returning "applied" having changed nothing would be a lie."""
    legs = _legs()
    facets = parse(dict(FACETS), roundtrip=False)        # no from/to
    legs, rejected, applied = apply(legs, _hide(), facets)
    assert applied == 0
    assert rejected, "the dropped preference must reach the caller"
    assert legs[0]["TakeOffAirport"] == []


def test_the_pseudo_field_never_reaches_the_filter():
    legs = _legs()
    facets = parse(dict(FACETS, **{"from": "DEL", "to": "BOM"}), roundtrip=False)
    legs, _, _ = apply(legs, _hide(), facets)
    assert "NearbyAirports" not in serialize(legs, roundtrip=False)


def test_naming_an_airport_still_goes_through_the_normal_path():
    """The regression most at risk: "fly from noida" must not become a sector op."""
    legs = _legs()
    facets = parse(dict(FACETS, **{"from": "DEL", "to": "BOM"}), roundtrip=False)
    legs, _, applied = apply(
        legs, [{"action": "set", "field": "TakeOffAirport", "values": ["DXN"]}], facets
    )
    assert applied
    assert legs[0]["TakeOffAirport"] == ["DXN"]


# ---------------------------------------------------------------- roundtrip


def test_each_leg_uses_its_own_sector():
    legs = _legs(2)
    facets = parse(
        [dict(FACETS, **{"from": "DEL", "to": "BOM"}),
         dict(FACETS, **{"from": "BOM", "to": "DEL"})],
        roundtrip=True,
    )
    legs, _, applied = apply(legs, _hide(), facets)
    assert applied
    assert legs[0]["TakeOffAirport"] == ["DEL"] and legs[0]["LandingAirport"] == ["BOM"]
    assert legs[1]["TakeOffAirport"] == ["BOM"] and legs[1]["LandingAirport"] == ["DEL"]


def test_targeting_the_return_leaves_the_outbound_alone():
    legs = _legs(2)
    facets = parse(
        [dict(FACETS, **{"from": "DEL", "to": "BOM"}),
         dict(FACETS, **{"from": "BOM", "to": "DEL"})],
        roundtrip=True,
    )
    legs, _, _ = apply(legs, _hide(legs=[1]), facets)
    assert legs[0]["TakeOffAirport"] == []
    assert legs[1]["TakeOffAirport"] == ["BOM"]
