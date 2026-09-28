"""Prompt Injector — LLM-assisted replacement with a stubbed client."""
from studio.inject import inject_prompt


class _Model:
    def __init__(self, model):
        self.model = model


class _Models:
    models = [_Model("gemma3:4b")]


class StubClient:
    def list(self):
        return _Models()

    def generate(self, **kwargs):
        num_predict = kwargs.get("options", {}).get("num_predict")
        if num_predict == 256:
            clothing = '"wearing a red dress"' if "red dress" in kwargs["prompt"] else "null"
            return {
                "response": (
                    f'{{"hair": "long blonde hair", "body": null, "skin": null, '
                    f'"clothing": {clothing}, "style": null}}'
                )
            }
        # grammar pass — echo the input back unchanged
        return {"response": kwargs["prompt"].splitlines()[-1]}


class GarbageStub(StubClient):
    """LLM identification returns unparseable output — script fallback must kick in."""

    def generate(self, **kwargs):
        if kwargs.get("options", {}).get("num_predict") == 256:
            return {"response": "Sorry, I could not parse this prompt."}
        return super().generate(**kwargs)


class ParaphrasedStub(StubClient):
    """LLM reports a hair span that does not verbatim-match the prompt."""

    def generate(self, **kwargs):
        if kwargs.get("options", {}).get("num_predict") == 256:
            return {
                "response": (
                    '{"hair": "locks flowing down", "body": null, "skin": null, '
                    '"clothing": "wearing a red dress", "style": null}'
                )
            }
        return super().generate(**kwargs)


class DropLockedStub(StubClient):
    """Grammar pass drops the injected hair — the guard must restore the input."""

    def generate(self, **kwargs):
        if kwargs.get("options", {}).get("num_predict") == 256:
            return {
                "response": (
                    '{"hair": "long blonde hair", "body": null, "skin": null, '
                    '"clothing": null, "style": null}'
                )
            }
        return {"response": "a cinematic photo with the image."}


def test_inject_basic(studio):
    raw = "A photo of a woman with long blonde hair standing in a studio, cinematic."
    res = inject_prompt(studio, StubClient(), raw)
    r = res["result"]

    assert "long blonde hair" not in r
    assert "The image has" in r
    assert "HEX VALUES:" in r


def test_inject_naked_mode_strips_clothing(studio):
    studio.opt_naked = True
    raw = "A woman wearing a red dress standing by a pool."
    res = inject_prompt(studio, StubClient(), raw)
    r = res["result"]
    assert "red dress" not in r.lower()
    assert "HEX VALUES:" in r


def test_inject_uses_scanned_outfit(studio):
    studio.outfit_active = True
    studio.outfit_description = (
        "a fitted black leather jacket with silver zippers worn open over a "
        "white crop top with ripped high-waist denim jeans and black ankle boots"
    )
    raw = "A woman wearing a red dress standing by a pool."
    res = inject_prompt(studio, StubClient(), raw)
    r = res["result"]
    assert "leather jacket" in r
    assert "red dress" not in r.lower()
    assert "HEX VALUES:" in r


def test_inject_uses_clothing_scan_ground_truth(studio):
    studio.last_clothing_gt = {
        "DRESS": "a flowing white maxi dress with a thigh-high slit",
        "FOOTWEAR": "strappy gold heels",
    }
    raw = "A woman in a black hoodie posing indoors."
    res = inject_prompt(studio, StubClient(), raw)
    r = res["result"]
    assert "white maxi dress" in r
    assert "HEX VALUES:" in r


def test_inject_naked_overrides_outfit(studio):
    studio.opt_naked = True
    studio.outfit_active = True
    studio.outfit_description = "a fitted black leather jacket and ripped jeans"
    raw = "A woman wearing a red dress standing by a pool."
    res = inject_prompt(studio, StubClient(), raw)
    r = res["result"]
    assert "red dress" not in r.lower()
    assert "leather jacket" not in r.lower()
    assert "HEX VALUES:" in r


def test_inject_json_failure_still_removes_hair(studio):
    raw = "A photo of a woman with long blonde hair standing in a studio, cinematic."
    res = inject_prompt(studio, GarbageStub(), raw)
    r = res["result"]
    assert "long blonde hair" not in r
    assert "(hex" in r
    assert "HEX VALUES:" in r


def test_inject_paraphrased_hair_still_removed(studio):
    raw = "She has shoulder-length wavy hair in a high ponytail, wearing a red dress."
    res = inject_prompt(studio, ParaphrasedStub(), raw)
    r = res["result"]
    assert "wavy hair" not in r
    assert "ponytail" not in r
    assert "(hex" in r
    assert "HEX VALUES:" in r


def test_inject_grammar_guard_keeps_locked_hair(studio):
    raw = "A photo of a woman with long blonde hair standing in a studio."
    res = inject_prompt(studio, DropLockedStub(), raw)
    r = res["result"]
    assert "long blonde hair" not in r
    assert "(hex" in r
    assert "HEX VALUES:" in r