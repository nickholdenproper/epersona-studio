import types

from studio import ollama as ollama_mod


def _cli():
    class Cli:
        def __init__(self):
            self.n = 0

        def list(self):
            self.n += 1
            return types.SimpleNamespace(
                models=[types.SimpleNamespace(model="a:latest"),
                        types.SimpleNamespace(model="b:7b")]
            )

    return Cli()


def test_list_models_cached(monkeypatch):
    monkeypatch.setattr(ollama_mod, "MODELS_CACHE_TTL", 60)
    ollama_mod.reset_models_cache()
    cli = _cli()
    first = ollama_mod.list_models(cli)
    second = ollama_mod.list_models(cli)
    assert first == ["a:latest", "b:7b"]
    assert second == first
    assert cli.n == 1


def test_list_models_stale_on_failure(monkeypatch):
    monkeypatch.setattr(ollama_mod, "MODELS_CACHE_TTL", 60)
    ollama_mod.reset_models_cache()
    assert ollama_mod.list_models(_cli()) == ["a:latest", "b:7b"]

    class Boom:
        def list(self):
            raise RuntimeError("down")

    assert ollama_mod.list_models(Boom()) == ["a:latest", "b:7b"]


def test_list_models_empty_fallback(monkeypatch):
    monkeypatch.setattr(ollama_mod, "MODELS_CACHE_TTL", 60)
    ollama_mod.reset_models_cache()

    class Empty:
        def list(self):
            return types.SimpleNamespace(models=[])

    assert ollama_mod.list_models(Empty()) == []