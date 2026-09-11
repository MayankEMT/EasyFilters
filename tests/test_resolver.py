"""Verification 5 and 8: relative intents, no clamping, presets."""
import pytest

from src.core.facets import parse
from src.core.resolver import resolve_range, resolve_sort, resolve_stops, resolve_values
from src.schema.filter_json import SORT_VALUES
from src.utils import duration as duration_utils
from src.utils import timewin
from src.utils import timewin


def _facets(raw):
    return parse(raw, roundtrip=False)[0]


def test_comparatives_become_a_sort_not_a_price_band():
    """"cheapest" means sort by price, not filter out mid-priced flights."""
    assert resolve_sort({"sort": "Cheapest"}) == "Cheapest"
    assert resolve_sort({"sort": "Fastest"}) == "Fastest"


def test_every_published_value_resolves_to_itself():
    """Guards a typo between SORT_VALUES and the model's enum."""
    for value in SORT_VALUES:
        assert resolve_sort({"sort": value}) == value


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Cheapest", "Cheapest"),
        ("cheapest", "Cheapest"),
        ("CHEAPEST", "Cheapest"),
        ("early takeoff", "Early Take-off"),
        ("EARLY_TAKE_OFF", "Early Take-off"),
        ("early take off", "Early Take-off"),
        ("highest_price", "Highest Price"),
        ("late arrival", "Late Arrival"),
    ],
)
def test_sort_tokens_are_shape_insensitive(raw, expected):
    """The tokens carry spaces and a hyphen; a model may echo them loosely."""
    assert resolve_sort({"sort": raw}) == expected


@pytest.mark.parametrize("bad", ["BEST_VALUE", "", None, "cheap", "FEWEST_STOPS"])
def test_unknown_sort_token_is_rejected(bad):
    """Including FEWEST_STOPS - the site has no stop-count sort."""
    assert resolve_sort({"sort": bad}) is None


def test_explicit_number_is_never_clamped():
    """"under 2k" on a route starting at 6,270 passes through as-is.
    Predicting an empty result set is the caller's job, not ours."""
    payload, _ = resolve_range("Price", {"range_max": "2000"})
    assert payload == {"Min": "", "Max": "2000"}


def test_explicit_number_above_ceiling_is_not_clamped_either():
    payload, _ = resolve_range("Price", {"range_min": "90000"})
    assert payload == {"Min": "90000", "Max": ""}


@pytest.mark.parametrize(
    "raw,expected",
    [("135", "135"), ("02h 15m", "135"), ("3h", "180"), ("02:15", "135")],
)
def test_duration_is_emitted_as_plain_minutes(raw, expected):
    """The filter API takes minutes, whatever shape the phrasing arrives in."""
    payload, _ = resolve_range("Duration", {"range_max": raw})
    assert payload == {"Min": "", "Max": expected}


@pytest.mark.parametrize(
    "preset,expected",
    [
        ("morning", {"Min": "06:00", "Max": "12:00"}),
        ("evening", {"Min": "17:00", "Max": "21:00"}),
        ("early morning", {"Min": "00:00", "Max": "06:00"}),
        ("MORNING", {"Min": "06:00", "Max": "12:00"}),
    ],
)
def test_presets_are_a_fixed_table(preset, expected):
    payload, _ = resolve_range("DepTime", {"preset": preset})
    assert payload == expected


def test_unknown_preset_reports_a_reason():
    payload, reason = resolve_range("DepTime", {"preset": "brunch"})
    assert payload is None and "brunch" in reason


def test_explicit_time_passes_through():
    payload, _ = resolve_range("DepTime", {"range_min": "18:00"})
    assert payload == {"Min": "18:00", "Max": ""}


@pytest.mark.parametrize("bad", ["25:00", "6pm", "", "abc"])
def test_invalid_time_is_rejected_not_crashed(bad):
    payload, reason = resolve_range("DepTime", {"range_min": bad})
    assert payload is None and reason


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("10000", "10000"),
        ("Rs 10,000", "10000"),
        ("10k", "10000"),
        ("1.5k", "1500"),
        ("2 lakh", "200000"),
        ("10 thousand", "10000"),
    ],
)
def test_price_token_normalisation(raw, expected):
    """The model is asked to send 10000, but occasionally echoes "10k".
    That must not silently drop the filter."""
    payload, _ = resolve_range("Price", {"range_max": raw})
    assert payload["Max"] == expected


def test_values_resolve_through_labels_and_codes():
    f = _facets({"airline": [{"value": "6E", "label": "IndiGo"}]})
    assert resolve_values("Airline", {"values": ["indigo"]}, f) == (["6E"], [])
    assert resolve_values("Airline", {"values": ["6E"]}, f) == (["6E"], [])
    assert resolve_values("Airline", {"values": ["  INDIGO "]}, f) == (["6E"], [])


def test_values_outside_the_facets_are_rejected():
    f = _facets({"airline": [{"value": "6E", "label": "IndiGo"}]})
    accepted, rejected = resolve_values("Airline", {"values": ["Vistara", "IndiGo"]}, f)
    assert accepted == ["6E"]
    assert rejected == ["Vistara"]


@pytest.mark.parametrize(
    "values,accepted,rejected",
    [
        (["0"], [0], []),
        (["1"], [1], []),
        (["0", "1"], [0, 1], []),
        (["non-stop"], [0], []),      # the model may echo the traveller's words
        (["direct"], [0], []),
        (["1 stop"], [1], []),
        (["47"], [], ["47"]),         # implausible - rejected, not passed on
        (["xyz"], [], ["xyz"]),
    ],
)
def test_stops_are_plain_integers_needing_no_facet(values, accepted, rejected):
    """Stop carries no facet: a stop count is just a number."""
    got, missed = resolve_stops({"values": values})
    assert got == accepted and all(isinstance(v, int) for v in got)
    assert missed == rejected


@pytest.mark.parametrize("field", ["Price", "Duration"])
def test_zero_lower_bound_is_treated_as_unset(field):
    """"below 1.5k" has no lower bound; a model sometimes fills one in as 0."""
    payload, _ = resolve_range(field, {"range_min": "0", "range_max": "1500"})
    assert payload["Min"] == ""


def test_midnight_is_a_real_departure_bound():
    """The zero-bound rule must not swallow 00:00 on a time field."""
    payload, _ = resolve_range("DepTime", {"range_min": "00:00", "range_max": "06:00"})
    assert payload == {"Min": "00:00", "Max": "06:00"}


def test_negative_price_is_rejected():
    """A negative fare is outside the domain - no result could ever match it.
    Distinct from "under 2k" on an expensive route, which passes through."""
    payload, reason = resolve_range("Price", {"range_max": "-5000"})
    assert payload is None and "negative" in reason


@pytest.mark.parametrize("raw", ["-5000", "-1", "-02h 30m"])
def test_negative_duration_is_rejected(raw):
    """Rejected during bound parsing rather than by the negative check, but
    rejected either way - assert the outcome, not the mechanism."""
    payload, reason = resolve_range("Duration", {"range_max": raw})
    assert payload is None and reason


def test_inverted_price_range_is_rejected():
    """"under 5000 and above 40000" - empty by arithmetic, so emitting it would
    hand the caller a filter that cannot match."""
    payload, reason = resolve_range("Price", {"range_min": "40000", "range_max": "5000"})
    assert payload is None and "inverted" in reason


def test_equal_bounds_are_allowed():
    payload, _ = resolve_range("Price", {"range_min": "5000", "range_max": "5000"})
    assert payload == {"Min": "5000", "Max": "5000"}


def test_inverted_time_range_is_allowed_through():
    """"night" is legitimately 21:00-03:00 and wraps midnight; how the filter
    API treats Min > Max on a time field is still open with that team."""
    payload, _ = resolve_range("DepTime", {"range_min": "21:00", "range_max": "03:00"})
    assert payload == {"Min": "21:00", "Max": "03:00"}


def test_inverted_duration_range_is_rejected():
    payload, reason = resolve_range("Duration", {"range_min": "10h 00m", "range_max": "02h 00m"})
    assert payload is None and "inverted" in reason
    # Same check once both sides are already minutes.
    payload2, reason2 = resolve_range("Duration", {"range_min": "600", "range_max": "120"})
    assert payload2 is None and "inverted" in reason2


@pytest.mark.parametrize("field", ["Price", "Duration"])
def test_zero_upper_bound_is_rejected(field):
    """"under 0 rupees" - nothing costs nothing, nothing takes no time."""
    payload, reason = resolve_range(field, {"range_max": "0"})
    assert payload is None and "zero" in reason


def test_zero_upper_bound_on_a_time_field_is_untouched():
    """00:00 is a real arrival bound, not an empty interval."""
    payload, _ = resolve_range("ArrTime", {"range_max": "00:00"})
    assert payload == {"Min": "", "Max": "00:00"}


def test_night_presets_wrap_past_midnight():
    """The filter API handles Min > Max on a time range, so a night window
    keeps the small hours instead of being truncated at 24:00."""
    payload, _ = resolve_range("DepTime", {"preset": "night"})
    assert payload == {"Min": "21:00", "Max": "03:00"}


@pytest.mark.parametrize("preset", ["night", "late night", "midnight"])
def test_wrapping_presets_are_not_normalised_into_order(preset):
    payload, _ = resolve_range("DepTime", {"preset": preset})
    lo, hi = timewin.to_minutes(payload["Min"]), timewin.to_minutes(payload["Max"])
    assert lo > hi, f"{preset} was flattened into ascending order"


def test_every_preset_is_a_valid_hhmm_pair():
    for name in timewin.PRESETS:
        lo, hi = timewin.preset_window(name)
        assert timewin.is_valid_hhmm(lo) and timewin.is_valid_hhmm(hi), name


def test_comma_separated_facets_echo_what_was_sent():
    """"Send what you get" - with no codes supplied, the name is the token."""
    f = parse({"airline": "IndiGo,Air India,SpiceJet"}, roundtrip=False)[0]
    assert resolve_values("Airline", {"values": ["indigo"]}, f) == (["IndiGo"], [])
    assert resolve_values("Airline", {"values": ["Vistara"]}, f) == ([], ["Vistara"])


def test_code_label_pairs_let_city_names_resolve():
    """A bare code cannot match "navi mumbai"; "NMI:Navi Mumbai" can."""
    f = parse({"landingAirport": "BOM:Mumbai,NMI:Navi Mumbai"}, roundtrip=False)[0]
    assert resolve_values("LandingAirport", {"values": ["navi mumbai"]}, f) == (["NMI"], [])
    assert resolve_values("LandingAirport", {"values": ["NMI"]}, f) == (["NMI"], [])


def test_unique_substring_resolves_verbose_facet_values():
    """"boeing 737" against "Boeing 737 (Narrow-body)"."""
    f = parse({"airCarftType": "Boeing 737 (Narrow-body),Airbus A320 (Narrow-body)"}, roundtrip=False)[0]
    assert resolve_values("AirCarftType", {"values": ["boeing 737"]}, f) == (
        ["Boeing 737 (Narrow-body)"], [])


def test_ambiguous_substring_is_not_guessed():
    """Two candidates means unresolved, not a coin flip."""
    f = parse({"airline": "Air India,Air India Express"}, roundtrip=False)[0]
    accepted, rejected = resolve_values("Airline", {"values": ["air"]}, f)
    assert accepted == [] and rejected == ["air"]


def test_exact_match_beats_a_substring_sibling():
    f = parse({"airline": "Air India,Air India Express"}, roundtrip=False)[0]
    assert resolve_values("Airline", {"values": ["Air India"]}, f) == (["Air India"], [])
