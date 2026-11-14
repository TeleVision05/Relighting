"""Query validation for GET /render: bounds, types and plain-language messages."""

import pytest

from render_params import MAX_QUERY_FIELDS, MODES, SETTINGS, RenderParamError, parse_render_query

NUMERIC = [s for s in SETTINGS if s.kind in ("int", "float")]
JARGON = ("Traceback", "ValueError", "Exception", "invalid literal", "HTTP", "400")


def message_for(query: str) -> str:
    with pytest.raises(RenderParamError) as info:
        parse_render_query(query)
    return str(info.value)


def test_empty_query_uses_defaults():
    kwargs = parse_render_query("")
    assert kwargs["width"] == 1600 and kwargs["height"] == 1600
    assert kwargs["mode"] == "relit"
    assert kwargs["stride"] == 1
    assert kwargs["dir_intensity"] == 1.5
    assert len(kwargs) == len(SETTINGS)


def test_valid_values_are_converted():
    kwargs = parse_render_query("w=64&h=32&stride=4&mode=albedo&roughness=0.5&dirX=-2&metallic=1")
    assert (kwargs["width"], kwargs["height"], kwargs["stride"]) == (64, 32, 4)
    assert kwargs["mode"] == "albedo"
    assert kwargs["roughness"] == 0.5 and kwargs["dir_x"] == -2.0 and kwargs["metallic"] == 1.0
    assert isinstance(kwargs["width"], int) and isinstance(kwargs["roughness"], float)


@pytest.mark.parametrize("setting", NUMERIC, ids=lambda s: s.query)
def test_bounds_are_inclusive_and_enforced(setting):
    fmt = (lambda v: str(int(v))) if setting.kind == "int" else repr
    assert parse_render_query(f"{setting.query}={fmt(setting.lo)}")[setting.kwarg] == setting.lo
    assert parse_render_query(f"{setting.query}={fmt(setting.hi)}")[setting.kwarg] == setting.hi
    step = 1 if setting.kind == "int" else 0.001
    for outside in (setting.lo - step, setting.hi + step):
        msg = message_for(f"{setting.query}={fmt(outside)}")
        assert setting.query in msg and "between" in msg
        assert f"{int(setting.lo) if float(setting.lo).is_integer() else setting.lo}" in msg


@pytest.mark.parametrize("setting", NUMERIC, ids=lambda s: s.query)
@pytest.mark.parametrize(
    "bad", ["abc", "", " ", "nan", "NaN", "inf", "-inf", "Infinity", "1e999", "0x10", "1,5", "٣", "1_0", "--1", "1 2"]
)
def test_non_numbers_are_rejected_in_plain_language(setting, bad):
    msg = message_for(f"{setting.query}={bad}")
    assert setting.query in msg
    assert "must be a" in msg
    assert not any(word in msg for word in JARGON)


@pytest.mark.parametrize("bad", ["512.5", "1e3", "5.", "+", "999999999999"])
def test_integers_reject_decimals_and_huge_numbers(bad):
    msg = message_for(f"w={bad}")
    assert "whole number between 16 and 2048" in msg


def test_image_size_message_names_the_limits():
    assert message_for("w=5000") == "Image width (w) must be a whole number between 16 and 2048. You sent '5000'."
    assert "Image height (h)" in message_for("h=0")
    assert "Stride" in message_for("stride=100")


@pytest.mark.parametrize("bad", ["", "sepia", "RELIT", "relit;rm", "relit,neutral"])
def test_mode_must_be_one_of_the_known_modes(bad):
    msg = message_for(f"mode={bad}")
    assert all(mode in msg for mode in MODES)


def test_unknown_and_repeated_settings_are_rejected():
    assert "Unknown setting 'colour'" in message_for("colour=red")
    assert "w was sent more than once" in message_for("w=64&w=65")
    assert "Unknown setting" in message_for("W=64")  # names are case-sensitive


def test_cache_busting_parameter_is_ignored():
    assert parse_render_query("_=12345&w=64")["width"] == 64


def test_every_problem_is_reported_at_once():
    msg = message_for("w=1&h=abc&roughness=3&mode=x")
    for name in ("(w)", "(h)", "(roughness)", "(mode)"):
        assert name in msg


def test_too_many_fields_are_rejected():
    query = "&".join("_x=1" for _ in range(MAX_QUERY_FIELDS + 1))
    assert "Too many settings" in message_for(query)


def test_long_values_are_truncated_in_the_message():
    msg = message_for("w=" + "9" * 5000)
    assert len(msg) < 300
