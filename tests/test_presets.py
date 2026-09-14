

def test_red_eye_is_not_a_time_preset():
    """It is the IsRedEyes flag; a DepTime window made the two disagree."""
    from src.utils.timewin import PRESETS, preset_window
    assert "red eye" not in PRESETS
    assert preset_window("red eye") is None


def test_patch_schema_advertises_exactly_the_presets_that_exist():
    """The model is told the preset list twice - they must not drift apart.

    "red eye" survived here after being removed from PRESETS, so the schema was
    offering the model a window that no longer resolved.
    """
    from src.schema.patch import FilterOp
    from src.utils.timewin import PRESETS

    described = FilterOp.model_fields["preset"].description.lower()
    for name in PRESETS:
        assert name in described, f"preset {name!r} exists but is not offered to the model"
    assert "red eye" not in described.split("not 'red eye'")[0]
