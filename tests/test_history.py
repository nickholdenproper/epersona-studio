from studio import history


def _setup(tmp_path, monkeypatch, limit=None):
    monkeypatch.setattr(history, "HISTORY_PATH", str(tmp_path / "history.jsonl"))
    if limit is not None:
        monkeypatch.setattr(history, "HISTORY_LIMIT", limit)
    history.clear_history()


def test_history_append_and_list(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    history.append_history("gen", "hello world", "soul")
    history.append_history("inject", "second", "")
    items = history.list_history()
    assert len(items) == 2
    assert items[0]["kind"] == "inject"
    assert items[0]["prompt"] == "second"
    assert items[1]["prompt"] == "hello world"
    assert items[1]["template"] == "soul"


def test_history_ignores_empty(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    history.append_history("gen", "")
    history.append_history("gen", "   ")
    assert history.list_history() == []


def test_history_cap_keeps_newest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, limit=5)
    for i in range(10):
        history.append_history("gen", f"prompt-{i}")
    items = history.list_history(50)
    assert len(items) == 5
    assert [it["prompt"] for it in items] == [
        f"prompt-{i}" for i in range(9, 4, -1)
    ]


def test_history_clear(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    history.append_history("gen", "hello")
    history.clear_history()
    assert history.list_history() == []