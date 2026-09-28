"""Persistence rules for the Ollama Cloud key.

The Settings panel can save a key, refuse to blank it (an empty field means
"no change"), and remove it via an explicit flag. All three paths need to stay
distinguishable, so each is pinned here.
"""
import json

import pytest

import studio.ollama as ollama_mod
import studio.settings as settings_mod
from studio.studio import Studio


def make_studio(monkeypatch, tmp_path, key=None):
    """A Studio whose settings file is isolated in tmp_path.

    `key=None` leaves whatever the settings file provides alone, which is what
    the reload tests need. Passing a key overrides the loaded value.
    """
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(ollama_mod, "_cloud_api_key", '')
    st = Studio()
    if key is not None:
        st.cloud_api_key = key
        ollama_mod.set_cloud_key(key)
    return st


def test_key_survives_save_and_reload(monkeypatch, tmp_path):
    st = make_studio(monkeypatch, tmp_path, 'secret-key-123')
    st.save_settings()

    on_disk = json.loads((tmp_path / 'settings.json').read_text(encoding='utf-8'))
    assert on_disk['cloud_api_key'] == 'secret-key-123'

    fresh = make_studio(monkeypatch, tmp_path)
    assert fresh.cloud_api_key == 'secret-key-123'


def test_new_key_replaces_old(monkeypatch, tmp_path):
    st = make_studio(monkeypatch, tmp_path, 'old-key')
    st.apply_updates({'cloud_api_key': 'new-key'})
    assert st.cloud_api_key == 'new-key'
    assert ollama_mod._cloud_api_key == 'new-key'


def test_empty_string_means_no_change(monkeypatch, tmp_path):
    """The browser clears the field after a save, so "" must not wipe the key."""
    st = make_studio(monkeypatch, tmp_path, 'keep-me')
    st.apply_updates({'cloud_api_key': ''})
    assert st.cloud_api_key == 'keep-me'
    assert ollama_mod._cloud_api_key == 'keep-me'


def test_absent_key_field_means_no_change(monkeypatch, tmp_path):
    st = make_studio(monkeypatch, tmp_path, 'keep-me')
    st.apply_updates({'selected_model': 'gemma4:31b'})
    assert st.cloud_api_key == 'keep-me'


def test_clear_flag_removes_key(monkeypatch, tmp_path):
    st = make_studio(monkeypatch, tmp_path, 'remove-me')
    st.apply_updates({'clear_cloud_key': True})
    assert st.cloud_api_key == ''
    assert ollama_mod._cloud_api_key == ''


def test_clear_flag_persists_across_reload(monkeypatch, tmp_path):
    st = make_studio(monkeypatch, tmp_path, 'remove-me')
    st.apply_updates({'clear_cloud_key': True})
    assert json.loads((tmp_path / 'settings.json').read_text(encoding='utf-8'))['cloud_api_key'] == ''

    fresh = make_studio(monkeypatch, tmp_path)
    assert fresh.cloud_api_key == ''


def test_clear_flag_wins_over_a_supplied_key(monkeypatch, tmp_path):
    st = make_studio(monkeypatch, tmp_path, 'old-key')
    st.apply_updates({'clear_cloud_key': True, 'cloud_api_key': 'ignored'})
    assert st.cloud_api_key == ''


def test_falsy_clear_flag_does_not_remove_key(monkeypatch, tmp_path):
    st = make_studio(monkeypatch, tmp_path, 'keep-me')
    st.apply_updates({'clear_cloud_key': False})
    assert st.cloud_api_key == 'keep-me'


def test_key_is_stripped(monkeypatch, tmp_path):
    st = make_studio(monkeypatch, tmp_path)
    st.apply_updates({'cloud_api_key': '  padded-key \n'})
    assert st.cloud_api_key == 'padded-key'


def test_non_string_key_is_coerced(monkeypatch, tmp_path):
    st = make_studio(monkeypatch, tmp_path)
    st.apply_updates({'cloud_api_key': 12345})
    assert st.cloud_api_key == '12345'
