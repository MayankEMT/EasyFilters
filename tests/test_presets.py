

def test_red_eye_is_not_a_time_preset():
    """It is the IsRedEyes flag; a DepTime window made the two disagree."""
    from src.utils.timewin import PRESETS, preset_window
    assert "red eye" not in PRESETS
    assert preset_window("red eye") is None
