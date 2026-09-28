"""Guard the caption/outfit extraction against silent prompt drift.

The caption and outfit prompts were moved out of routes.py so the CLI and the
browser share one implementation. That is only safe while the strings stay
byte-identical, so this compares them against the version in git history - a
refactor that "tidies" a prompt word is caught here rather than in production.
"""
import ast
import subprocess

import pytest

from studio import caption, outfit


def _committed_routes():
    r = subprocess.run(['git', 'show', 'HEAD:studio/routes.py'],
                       capture_output=True, check=False)
    if r.returncode != 0:
        pytest.skip('no committed studio/routes.py to compare against')
    # Must decode as utf-8 explicitly: on Windows subprocess would otherwise use
    # the cp1252 locale and turn correct em-dashes into fake mojibake.
    return r.stdout.decode('utf-8')


def _tables_from(source):
    found = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id in ('VIBE_PROMPTS', 'LENGTH_RULES'):
                found[t.id] = ast.literal_eval(node.value)
    return found


def test_vibe_table_matches_the_committed_original():
    lit = _tables_from(_committed_routes())
    assert caption.VIBE_PROMPTS == lit['VIBE_PROMPTS']


def test_length_table_matches_the_committed_original():
    lit = _tables_from(_committed_routes())
    assert caption.LENGTH_RULES == lit['LENGTH_RULES']


@pytest.mark.parametrize('vibe', list(caption.VIBE_PROMPTS) + ['nonsense', '', None])
@pytest.mark.parametrize('length', list(caption.LENGTH_RULES) + ['nonsense', '', None])
def test_caption_prompt_is_byte_identical(vibe, length):
    src = _committed_routes()
    lit = _tables_from(src)

    v = (vibe or 'casual').lower().strip()
    ln = (length or 'medium').lower().strip()
    expected = (
        f"You are a social media expert. Look at this image and write a single catchy Twitter/X caption.\n\n"
        f"TONE: {lit['VIBE_PROMPTS'].get(v, lit['VIBE_PROMPTS']['casual'])}\n"
        f"LENGTH: {lit['LENGTH_RULES'].get(ln, lit['LENGTH_RULES']['medium'])}\n\n"
        "Rules:\n"
        "- Use 2-4 emojis placed naturally throughout the caption\n"
        "- End with exactly 2 relevant hashtags\n"
        "- Do NOT use quotation marks around the caption\n"
        "- Return ONLY the raw caption text — no explanation, no labels, no markdown\n"
    )
    assert caption.caption_prompt(vibe, length) == expected


def test_outfit_prompt_matches_the_committed_original():
    src = _committed_routes()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'outfit_prompt' for t in node.targets):
            assert outfit.OUTFIT_PROMPT == ast.literal_eval(node.value)
            return
    pytest.skip('outfit_prompt no longer present in the committed routes.py')


# --------------------------------------------------------------------------
# caption module behaviour
# --------------------------------------------------------------------------
def test_unknown_vibe_and_length_fall_back_to_defaults():
    p = caption.caption_prompt('nope', 'nope')
    assert caption.VIBE_PROMPTS['casual'] in p
    assert caption.LENGTH_RULES['medium'] in p


def test_caption_prompt_mentions_every_rule():
    p = caption.caption_prompt('hype', 'long')
    assert 'rooftop' in p                       # hype tone reached the prompt
    assert 'between 200 and 280 characters.' in p


def test_outfit_tidy_strips_markdown_and_truncates():
    messy = "**Bold** look\n# A heading\n- item one\n- item two   " + "word " * 200
    out = outfit._tidy(messy)
    assert '**' not in out
    assert '#' not in out
    assert not out.startswith('-')
    assert len(out) <= outfit.MAX_DESCRIPTION_CHARS + 1


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
    monkeypatch.setattr(caption, 'resolve_model', lambda m: None)
    with pytest.raises(RuntimeError):
        caption.write_caption(_FakeStudio(), str(_img(tmp_path)))


def test_outfit_reports_a_missing_model(tmp_path, monkeypatch):
    monkeypatch.setattr(outfit, 'resolve_model', lambda m: None)
    with pytest.raises(RuntimeError):
        outfit.describe_outfit(_FakeStudio(), str(_img(tmp_path)))


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
