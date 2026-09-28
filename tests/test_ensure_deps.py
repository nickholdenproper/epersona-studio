import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ensure_deps


def test_parses_extras_and_version_specifiers(tmp_path):
    reqs = tmp_path / "requirements.txt"
    reqs.write_text(
        "uvicorn[standard]\n"
        "numpy>=2.0.0\n"
        "transformers>=4.45.0,<5.0.0\n"
        "pillow\n",
        encoding="utf-8",
    )
    assert ensure_deps.parse_requirements(str(reqs)) == [
        "uvicorn",
        "numpy",
        "transformers",
        "pillow",
    ]


def test_skips_comments_blank_lines_and_pip_options(tmp_path):
    reqs = tmp_path / "requirements.txt"
    reqs.write_text(
        "# a comment\n"
        "\n"
        "--extra-index-url https://example.com/whl\n"
        "-r other.txt\n"
        "  numpy  \n",
        encoding="utf-8",
    )
    assert ensure_deps.parse_requirements(str(reqs)) == ["numpy"]


def test_missing_package_is_detected(tmp_path, monkeypatch):
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("numpy\ntotally-fake-pkg-xyz\n", encoding="utf-8")
    monkeypatch.setattr(ensure_deps, "is_installed", lambda name: name == "numpy")
    assert ensure_deps.missing_packages(str(reqs)) == ["totally-fake-pkg-xyz"]


def test_main_returns_zero_when_everything_installed(tmp_path, monkeypatch, capsys):
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("numpy\npillow\n", encoding="utf-8")
    monkeypatch.setattr(ensure_deps, "REQUIREMENTS_PATH", str(reqs))
    monkeypatch.setattr(ensure_deps, "is_installed", lambda name: True)
    assert ensure_deps.main() == 0
    assert "All 2 dependencies present" in capsys.readouterr().out


def test_main_returns_one_and_lists_gaps(tmp_path, monkeypatch, capsys):
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("numpy\npillow\n", encoding="utf-8")
    monkeypatch.setattr(ensure_deps, "REQUIREMENTS_PATH", str(reqs))
    monkeypatch.setattr(ensure_deps, "is_installed", lambda name: name == "numpy")
    assert ensure_deps.main() == 1
    out = capsys.readouterr().out
    assert "Missing 1 of 2" in out
    assert "pillow" in out


def test_main_is_tolerant_of_missing_requirements_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ensure_deps, "REQUIREMENTS_PATH", str(tmp_path / "nope.txt"))
    assert ensure_deps.main() == 0


def test_main_is_tolerant_of_empty_requirements_file(tmp_path, monkeypatch):
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("# only comments\n", encoding="utf-8")
    monkeypatch.setattr(ensure_deps, "REQUIREMENTS_PATH", str(reqs))
    assert ensure_deps.main() == 0


def test_shipped_requirements_all_present():
    """Guards the launcher's fast path against a stale requirements.txt."""
    assert ensure_deps.missing_packages(ensure_deps.REQUIREMENTS_PATH) == []
