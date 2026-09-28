"""Template save / load / delete.

These routes used to call st.save_settings(force=True) while save_settings
takes no arguments, so every save and delete raised TypeError and returned a
500 - the UI swallowed it in a toast, which is why it went unnoticed. The
explicit 200-status assertions below pin that regression shut.
"""
import json

import pytest
from fastapi.testclient import TestClient

import studio.ollama as ollama_mod
import studio.settings as settings_mod
import studio.routes as routes_mod
from studio.studio import Studio


@pytest.fixture
def env(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", str(path))
    monkeypatch.setattr(ollama_mod, "_cloud_api_key", '')
    monkeypatch.setattr(routes_mod, "STUDIO", Studio())
    return routes_mod.STUDIO, path


@pytest.fixture
def client(env):
    return TestClient(routes_mod.app)


def on_disk(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_save_creates_template(client, env):
    st, path = env
    r = client.post('/api/templates/save', json={'name': 'Sunset'})
    assert r.status_code == 200, r.text
    assert 'Sunset' in r.json()['templates']
    assert 'Sunset' in on_disk(path)['templates']


def test_save_persists_current_slider_state(client, env):
    st, _ = env
    st.breast_size = 77
    client.post('/api/templates/save', json={'name': 'Big'})
    tmpl = st.templates['Big']
    assert tmpl['breast_size'] == 77
    assert 'hair_base_color' in tmpl and 'prompt_template' in tmpl


def test_save_requires_a_name(client):
    assert client.post('/api/templates/save', json={'name': '   '}).status_code == 400


def test_save_overwrites_same_name(client, env):
    st, _ = env
    st.hip_size = 10
    client.post('/api/templates/save', json={'name': 'Same'})
    st.hip_size = 90
    client.post('/api/templates/save', json={'name': 'Same'})
    assert st.templates['Same']['hip_size'] == 90
    assert list(st.templates).count('Same') == 1


def test_load_applies_stored_values(client, env):
    st, _ = env
    st.breast_size = 66
    client.post('/api/templates/save', json={'name': 'Loadable'})
    st.breast_size = 5
    r = client.post('/api/templates/load/Loadable')
    assert r.status_code == 200, r.text
    assert st.breast_size == 66


def test_load_unknown_template_404s(client):
    assert client.post('/api/templates/load/nope').status_code == 404


def test_delete_removes_and_persists(client, env):
    st, path = env
    client.post('/api/templates/save', json={'name': 'Temp'})
    r = client.delete('/api/templates/delete/Temp')
    assert r.status_code == 200, r.text
    assert 'Temp' not in st.templates
    assert 'Temp' not in on_disk(path)['templates']


def test_delete_unknown_template_404s(client):
    assert client.delete('/api/templates/delete/nope').status_code == 404


def test_templates_survive_a_restart(client, env):
    st, path = env
    client.post('/api/templates/save', json={'name': 'Persisted'})
    reloaded = Studio()
    reloaded.load_settings()
    assert 'Persisted' in reloaded.templates
