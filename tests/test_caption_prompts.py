"""Guard the caption/outfit extraction against silent prompt drift.

These prompts were moved out of studio/routes.py so the browser and the CLI
share one implementation instead of two copies drifting apart. prompts
must therefore render byte-identically to the pre-refactor originals, which
tests/prompt_golden.json captures exactly.

If you change a prompt on purpose, regenerate the golden with
``python _make_golden.py`` and read the diff before committing it.
"""
import json
import pathlib

import pytest

from studio import caption, outfit

GOLDEN = json.loads(
    (pathlib.Path(__file__).parent / 'prompt_golden.json').read_text(encoding='utf-8')
)


# --------------------------------------------------------------------------
# the tables
# --------------------------------------------------------------------------
def test_vibe_prompts_match_golden():
    assert caption.VIBE_PROMPTS == GOLDEN['vibe_prompts']


def test_length_rules_match_golden():
    assert caption.LENGTH_RULES == GOLDEN['length_rules']


# --------------------------------------------------------------------------
# the fully rendered prompts
# --------------------------------------------------------------------------
def _ids(cases):
    return [f"{c['vibe']}|{c['length']}" for c in cases]


@pytest.mark.parametrize('case', GOLDEN['caption'], ids=_ids(GOLDEN['caption']))
def test_caption_prompt_matches_golden(case):
    assert caption.caption_prompt(case['vibe'], case['length']) == case['prompt']


def test_outfit_prompt_matches_golden():
    assert outfit.OUTFIT_PROMPT == GOLDEN['outfit']


def test_golden_covers_every_vibe_and_length():
    """If someone adds a vibe, the golden should already account for it."""
    assert set(caption.VIBE_PROMPTS) == set(GOLDEN['vibe_prompts'])
    assert set(caption.LENGTH_RULES) == set(GOLDEN['length_rules'])


# --------------------------------------------------------------------------
# behaviour
# --------------------------------------------------------------------------
def test_caption_prompt_mentions_every_rule():
    p = caption.caption_prompt('hype', 'long')
    assert 'rooftop' in p                                  # tone reached the prompt
    assert GOLDEN['length_rules']['long'] in p
    assert '2-4 emojis' in p
    assert 'exactly 2 relevant hashtags' in p


def test_empty_response_raises_empty_caption(tmp_path, monkeypatch):
    class Empty:
        def generate(self, **kw):
            return {'response': '   '}

    _stub_model(monkeypatch, Empty)
    with pytest.raises(caption.EmptyCaption):
        caption.write_caption(_FakeStudio(), str(_img(tmp_path)))


def test_write_caption_strips_wrapping_quotes(tmp_path, monkeypatch):
    class Quoted:
        def generate(self, **kw):
            return {'response': '  "a lovely shot"  '}

    _stub_model(monkeypatch, Quoted)
    assert caption.write_caption(_FakeStudio(), str(_img(tmp_path))) == 'a lovely shot'


def test_write_caption_rejects_a_missing_model(tmp_path, monkeypatch):
    """A RuntimeError, not an HTTPException: the CLI has no status codes."""
    monkeypatch.setattr(caption, 'resolve_model', lambda m, *a, **k: None)
    with pytest.raises(RuntimeError):
        caption.write_caption(_FakeStudio(), str(_img(tmp_path)))


def test_outfit_reports_a_missing_model(tmp_path, monkeypatch):
    monkeypatch.setattr(outfit, 'resolve_model', lambda m, *a, **k: None)
    with pytest.raises(RuntimeError):
        outfit.describe_outfit(_FakeStudio(), str(_img(tmp_path)))


def test_outfit_tidy_strips_markdown_and_truncates():
    messy = "**Bold** look\n# A heading\n- item one\n- item two   " + "word " * 200
    out = outfit._tidy(messy)
    assert '**' not in out
    assert '#' not in out
    assert not out.startswith('-')
    assert len(out) <= outfit.MAX_DESCRIPTION_CHARS + 1


def _img(tmp_path):
    from PIL import Image
    p = tmp_path / "x.png"
    Image.new("RGB", (16, 16), (10, 10, 10)).save(p)
    return p


def _stub_model(monkeypatch, client_cls):
    monkeypatch.setattr(caption, 'resolve_model', lambda m, *a, **k: m or 'stub')
    monkeypatch.setattr(caption, 'client_for_model', lambda m, *a, **k: client_cls())


class _FakeStudio:
    selected_model = 'stub-model'
