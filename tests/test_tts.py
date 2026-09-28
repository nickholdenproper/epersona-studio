"""TTS mode — strip body/hair sentences, re-inject current settings."""
from studio.tts import tts_transform


def test_tts_strips_and_reinjects(studio):
    raw = (
        "She has large breasts and long blonde hair. "
        "Standing in a bright garden with a warm smile. "
        'HEX VALUES: ["#FF5733"]'
    )
    res = tts_transform(studio, raw)
    r = res["result"]

    assert "large breasts" not in r
    assert "long blonde hair" not in r
    assert "Standing in a bright garden with a warm smile" in r
    assert '"#FF5733"' in r
    # injected default hair/body/skin anchors are present
    assert "Her hair is" in r


def test_tts_empty_raises(studio):
    import pytest

    with pytest.raises(ValueError):
        tts_transform(studio, "")