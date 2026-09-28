"""Shared fixtures — an isolated Studio instance that never touches the real
settings.json file or the Ollama host."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import studio.settings as settings_mod
from studio.studio import Studio


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    return Studio()