"""Two backend contracts that were silently broken.

1. local_client() hardcoded LOCAL_PROBE_TIMEOUT, so every local generation used
   a 5s budget while the cloud client got GENERATE_TIMEOUT (600s). Probing still
   needs to fail fast, so the timeout has to be chosen per call site.

2. routes.py did `from .florence import FLORENCE_AVAILABLE`, binding the value
   False that the module starts with. The flag only flips once transformers is
   imported lazily, so the pre-scan could never become eligible. Callers must
   read it through florence_available() at call time.
"""
import types

import pytest

from studio import florence as florence_mod
from studio import ollama as ollama_mod


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def list(self):
        return types.SimpleNamespace(models=[])


class _Recorder:
    def __init__(self):
        self.kwargs = None

    def __call__(self, *args, **kwargs):
        self.kwargs = kwargs
        return _FakeClient(*args, **kwargs)


# --------------------------------------------------------------------------
# local_client timeouts
# --------------------------------------------------------------------------
def test_local_client_defaults_to_generation_timeout(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(ollama_mod.ollama, "Client", rec)
    ollama_mod.local_client()
    assert rec.kwargs["timeout"] == ollama_mod.GENERATE_TIMEOUT
    assert rec.kwargs["timeout"] > 60


def test_local_client_honours_an_explicit_timeout(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(ollama_mod.ollama, "Client", rec)
    ollama_mod.local_client(timeout=1.5)
    assert rec.kwargs["timeout"] == 1.5


def test_probing_uses_the_short_timeout(monkeypatch):
    """A dead local server must still fail fast rather than hang 10 minutes."""
    rec = _Recorder()
    monkeypatch.setattr(ollama_mod.ollama, "Client", rec)
    monkeypatch.setitem(ollama_mod._backends["local"], "ts", 0.0)
    monkeypatch.setitem(ollama_mod._backends["local"], "reachable", False)
    ollama_mod._resolve_models("local")
    assert rec.kwargs["timeout"] == ollama_mod.LOCAL_PROBE_TIMEOUT
    assert ollama_mod.LOCAL_PROBE_TIMEOUT < ollama_mod.GENERATE_TIMEOUT


def test_generation_path_is_not_given_the_probe_timeout(monkeypatch):
    """client() must never hand back a 5s-budget client for real work."""
    rec = _Recorder()
    monkeypatch.setattr(ollama_mod.ollama, "Client", rec)
    monkeypatch.setattr(ollama_mod, "local_reachable", lambda: True)
    ollama_mod.client()
    assert rec.kwargs["timeout"] == ollama_mod.GENERATE_TIMEOUT


# --------------------------------------------------------------------------
# florence availability is read at call time
# --------------------------------------------------------------------------
def test_florence_available_reflects_a_late_flip(monkeypatch):
    monkeypatch.setattr(florence_mod, "FLORENCE_AVAILABLE", False)
    assert florence_mod.florence_available() is False
    monkeypatch.setattr(florence_mod, "FLORENCE_AVAILABLE", True)
    assert florence_mod.florence_available() is True


def test_routes_does_not_pin_the_availability_flag():
    """A from-import would snapshot False into routes' namespace forever."""
    import inspect

    import studio.routes as routes_mod

    src = inspect.getsource(routes_mod)
    assert "import FLORENCE_AVAILABLE" not in src, (
        "routes must not from-import the lazily-set FLORENCE_AVAILABLE flag"
    )
    assert "florence_available()" in src
