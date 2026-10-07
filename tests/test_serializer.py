"""Verification 1 and 8: the Is* flags and the exact output template."""
import pytest

from src.core.serializer import serialize
from src.schema.filter_json import (
    BOOL_FIELDS,
    LIST_FIELDS,
    RANGE_FIELDS,
    empty_filter,
    flag_name,
)

# The template exactly as the consuming team supplied it, including the
# AirCarftType / IsRedEyes spellings.
SPEC_TEMPLATE = {
    "IsPrice": False,
    "Price": {"Min": "", "Max": ""},
    "IsDepTime": False,
    "DepTime": {"Min": "", "Max": ""},
    "IsArrTime": False,
    "ArrTime": {"Min": "", "Max": ""},
    "IsStop": False,
    "Stop": [],
    "IsAirline": False,
    "Airline": [],
    "IsDuration": False,
    "Duration": {"Min": "", "Max": ""},
    "IsLayover": False,
    "Layover": [],
    "IsAirCarftType": False,
    "AirCarftType": [],
    "Refundable": False,
    "IsWifi": False,
    "IsRedEyes": False,
    "IsTakeOffAirport": False,
    "TakeOffAirport": [],
    "IsLandingAirport": False,
    "LandingAirport": [],
    "IsSortBy": False,
    "SortBy": "",
}


def test_empty_matches_spec_byte_for_byte():
    out = serialize([empty_filter()], roundtrip=False)
    assert out == SPEC_TEMPLATE
    assert list(out.keys()) == list(SPEC_TEMPLATE.keys())


@pytest.mark.parametrize("field", RANGE_FIELDS)
def test_range_field_sets_only_its_own_flag(field):
    leg = empty_filter()
    leg[field] = {"Min": "", "Max": "10"}
    out = serialize([leg], roundtrip=False)

    assert out[flag_name(field)] is True
    for other in RANGE_FIELDS + LIST_FIELDS:
        if other != field:
            assert out[flag_name(other)] is False, f"{other} leaked"


@pytest.mark.parametrize("field", LIST_FIELDS)
def test_list_field_sets_only_its_own_flag(field):
    leg = empty_filter()
    leg[field] = ["X"]
    out = serialize([leg], roundtrip=False)

    assert out[flag_name(field)] is True
    assert out[field] == ["X"]
    for other in RANGE_FIELDS + LIST_FIELDS:
        if other != field:
            assert out[flag_name(other)] is False, f"{other} leaked"


@pytest.mark.parametrize("field", BOOL_FIELDS)
def test_bool_fields_set_directly(field):
    leg = empty_filter()
    leg[field] = True
    out = serialize([leg], roundtrip=False)
    assert out[field] is True


def test_flags_never_contradict_payload():
    """The most likely bug in this service: IsStop false beside Stop [0]."""
    leg = empty_filter()
    leg["Stop"] = [0]
    leg["IsStop"] = False  # deliberately wrong on the way in
    out = serialize([leg], roundtrip=False)
    assert out["IsStop"] is True


def test_range_bounds_are_strings():
    leg = empty_filter()
    leg["Price"] = {"Min": 5000, "Max": 10000}
    out = serialize([leg], roundtrip=False)
    assert out["Price"] == {"Min": "5000", "Max": "10000"}


def test_sortby_sets_its_flag():
    leg = empty_filter()
    leg["SortBy"] = "Cheapest"
    out = serialize([leg], roundtrip=False)
    assert out["SortBy"] == "Cheapest" and out["IsSortBy"] is True


def test_sortby_empty_stays_unflagged():
    out = serialize([empty_filter()], roundtrip=False)
    assert out["SortBy"] == "" and out["IsSortBy"] is False


def test_roundtrip_is_two_elements():
    out = serialize([empty_filter(), empty_filter()], roundtrip=True)
    assert isinstance(out, list) and len(out) == 2
    assert out[0] == SPEC_TEMPLATE


def test_an_upper_bound_alone_gets_a_zero_floor():
    """"under 5000" is 0..5000 - the consuming filter wants both bounds."""
    leg = empty_filter()
    leg["Price"] = {"Min": "", "Max": "5000"}
    leg["Duration"] = {"Min": "", "Max": "120"}
    out = serialize([leg], roundtrip=False)
    assert out["Price"] == {"Min": "0", "Max": "5000"}
    assert out["Duration"] == {"Min": "0", "Max": "120"}


def test_times_never_get_a_zero_floor():
    """"arrive before noon" must not become "between midnight and noon"."""
    leg = empty_filter()
    leg["ArrTime"] = {"Min": "", "Max": "12:00"}
    leg["DepTime"] = {"Min": "", "Max": "18:00"}
    out = serialize([leg], roundtrip=False)
    assert out["ArrTime"] == {"Min": "", "Max": "12:00"}
    assert out["DepTime"] == {"Min": "", "Max": "18:00"}


def test_an_unset_range_stays_fully_empty():
    """No upper bound means no filter at all, so no floor is invented."""
    out = serialize([empty_filter()], roundtrip=False)
    assert out["Price"] == {"Min": "", "Max": ""}
    assert out["IsPrice"] is False


def test_a_lower_bound_alone_is_left_alone():
    """"above 5000" has no upper bound to invent."""
    leg = empty_filter()
    leg["Price"] = {"Min": "5000", "Max": ""}
    out = serialize([leg], roundtrip=False)
    assert out["Price"] == {"Min": "5000", "Max": ""}
