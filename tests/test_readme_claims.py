"""Check the README makes no claim the code cannot back up.

Each feature bullet is mapped to the symbol or file that implements it. A
README that advertises a feature nobody wrote is worse than no README, so this
fails when a bullet is added without an implementation to point at.
"""
import json
import pathlib
import re

README = pathlib.Path(__file__).resolve().parent.parent / 'README.md'

text = README.read_text(encoding='utf-8')

# bullet -> substring that must exist somewhere in the repo
CLAIMS = {
    'vision-to-prompt':      'studio/vlm_ollama.py',
    'editable output':       'studio/prompt_builder.py',
    'targeted edits':        'studio/inject.py',
    'presets':               'studio/settings.py',
    'caption':               'studio/caption.py',
    'outfit':                'studio/outfit.py',
    'prompt re-sync':        'studio/tts.py',
    'local-first':           '127.0.0.1',
}

# words that would mean we are claiming audio we do not produce
FORBIDDEN = [
    'text-to-speech', 'text to speech', 'speak a draft', 'spoken aloud',
    'hands-free', 'reads it aloud', 'voice', 'narration',
]

repo = pathlib.Path(__file__).resolve().parent.parent
sources = {p: p.read_text(encoding='utf-8', errors='replace')
           for p in repo.rglob('*.py') if '.git' not in p.parts}
sources.update({p: p.read_text(encoding='utf-8', errors='replace')
                for p in (repo / 'static').rglob('*') if p.is_file()})
corpus = '\n'.join(sources.values()) + text

failures = []


def test_every_feature_bullet_has_an_implementation():
    bullets = re.findall(r'^- \*\*(.+?)\*\*', text, re.M)
    assert len(bullets) >= 7, f'expected the feature list to parse, got {bullets}'
    for b in bullets:
        key = b.lower()
        assert any(k in key for k in CLAIMS), f'unmapped feature bullet: {b!r}'
        needle = next(CLAIMS[k] for k in CLAIMS if k in key)
        assert needle in corpus, f'{b!r} claims {needle!r} but nothing references it'


def test_readme_makes_no_audio_claims():
    # "TTS Mode" is the GUI's own label; allow it only next to the disclaimer.
    for word in FORBIDDEN:
        for m in re.finditer(re.escape(word), text, re.I):
            ctx = text[max(0, m.start() - 160):m.end() + 160].lower()
            assert 'not' in ctx or 'no audio' in ctx, (
                f'readme says {word!r} without the disclaimer: ...{ctx}...')


def test_cli_table_lists_only_real_commands():
    from studio import cli
    real = [a for a in dir(cli) if a.startswith('cmd_')]
    listed = set(re.findall(r'^\| `(\w+)` \|', text, re.M))
    assert listed, 'no command table found in the readme'
    for name in listed:
        # `config`/`history`/`templates` are groups: cmd_config_set, cmd_history_list, ...
        assert any(r.startswith(f'cmd_{name}') for r in real), \
            f'readme lists `{name}` but no cmd_{name}* exists'
