"""Tests for the cloud-key reveal endpoint.

GET /api/settings/cloud-key hands the stored key to the Settings panel so it
can be displayed masked. It must report the same value Studio holds, must not
lie when no key is set, and must stay off /api/state (the polling path).
"""
import pytest
from fastapi.testclient import TestClient

import studio.ollama as ollama_mod
import studio.settings as settings_mod
import studio.routes as routes_mod
from studio.studio import Studio


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(ollama_mod, "_cloud_api_key", '')
    monkeypatch.setattr(routes_mod, "STUDIO", Studio())
    return TestClient(routes_mod.app)


def test_returns_stored_key(client):
    routes_mod.STUDIO.cloud_api_key = 'sk-abc-123'
    r = client.get('/api/settings/cloud-key')
    assert r.status_code == 200
    assert r.json() == {'key': 'sk-abc-123', 'has_key': True}


def test_reports_empty_when_unset(client):
    r = client.get('/api/settings/cloud-key')
    assert r.status_code == 200
    assert r.json() == {'key': '', 'has_key': False}


def test_reflects_a_cleared_key(client):
    routes_mod.STUDIO.apply_updates({'cloud_api_key': 'sk-temp'})
    routes_mod.STUDIO.apply_updates({'clear_cloud_key': True})
    assert client.get('/api/settings/cloud-key').json() == {'key': '', 'has_key': False}


def test_state_endpoint_does_not_leak_the_key(client):
    routes_mod.STUDIO.cloud_api_key = 'sk-secret-value'
    body = client.get('/api/state').text
    assert 'sk-secret-value' not in body
    assert client.get('/api/state').json()['has_cloud_key'] is True
