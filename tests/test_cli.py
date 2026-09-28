"""CLI tests.

The point of these is the CLI's own contract - flag mapping, stream
separation, exit codes, and above all that the cloud key never reaches a
terminal. Model calls are stubbed at studio.ollama so the real resolve_model /
client_for_model plumbing is exercised without a network.
"""
import io
import json
import os
import sys

import pytest
from PIL import Image

import studio.history as history_mod
import studio.ollama as ollama_mod
import studio.settings as settings_mod
from studio import cli
from studio.studio import Studio


class StubClient:
    def generate(self, **kw):
        return {"response": "STUB: a woman in a red dress under warm light."}

    def list(self):
        import types
        return types.SimpleNamespace(models=[types.SimpleNamespace(model="stub-model")])


@pytest.fixture
def cli_studio(tmp_path, monkeypatch):
    """A Studio on a throwaway settings file, with the model layer stubbed."""
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(history_mod, "HISTORY_PATH", str(tmp_path / "history.jsonl"))
    st = Studio()
    st.selected_model = "stub-model"

    # Stub at the source: caption/outfit/inject/pipeline each import these names
    # into their own namespace, so patching the consumers would miss them.
    monkeypatch.setattr(ollama_mod, "_probe",
                        lambda kind: (True, ["stub-model"]) if kind == "local" else (False, []))
    monkeypatch.setattr(ollama_mod, "local_client", lambda **kw: StubClient())
    monkeypatch.setattr(ollama_mod, "cloud_client", lambda **kw: StubClient())
    return st


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "photo.png"
    Image.new("RGB", (48, 64), (180, 120, 90)).save(p)
    return str(p)


def run(argv, studio, capsys):
    """Run the CLI and return (exit_code, stdout, stderr)."""
    code = cli.run(argv, studio)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def test_no_command_prints_help_and_exits_2(cli_studio, capsys):
    code, out, err = run([], cli_studio, capsys)
    assert code == 2
    assert "usage:" in err


def test_help_exits_zero(cli_studio, capsys):
    assert cli.run(["--help"], cli_studio) == 0
    assert "usage:" in capsys.readouterr().out


def test_bad_flag_exits_2_without_traceback(cli_studio, capsys):
    assert cli.run(["generate", "x.png", "--nonsense"], cli_studio) == 2
    assert "usage:" in capsys.readouterr().err


# --------------------------------------------------------------------------
# flag mapping
# --------------------------------------------------------------------------
def test_slider_flags_map_to_studio_fields(cli_studio, photo, capsys):
    run(["generate", photo, "--breast", "70", "--hips", "20",
         "--hair-length", "90", "--hair-brightness", "40"], cli_studio, capsys)
    assert cli_studio.breast_size == 70
    assert cli_studio.hip_size == 20
    assert cli_studio.hair_length == 90
    assert cli_studio.hair_brightness == 40


def test_toggle_flags_map_to_opt_fields(cli_studio, photo, capsys):
    run(["generate", photo, "--no-noise", "--hdr", "--safe"], cli_studio, capsys)
    assert cli_studio.opt_noise is False
    assert cli_studio.opt_hdr is True
    assert cli_studio.opt_safe is True


def test_tattoos_flag_is_inverted(cli_studio, photo, capsys):
    """--tattoos must clear opt_no_tattoos, not set it."""
    cli_studio.opt_no_tattoos = True
    run(["generate", photo, "--tattoos"], cli_studio, capsys)
    assert cli_studio.opt_no_tattoos is False
    run(["generate", photo, "--no-tattoos"], cli_studio, capsys)
    assert cli_studio.opt_no_tattoos is True


def test_default_details_flag_maps_straight_across(cli_studio, photo, capsys):
    """Unlike --tattoos, --no-default-details maps directly: False -> False."""
    run(["generate", photo, "--no-default-details"], cli_studio, capsys)
    assert cli_studio.use_default_details is False
    run(["generate", photo, "--default-details"], cli_studio, capsys)
    assert cli_studio.use_default_details is True


def test_omitted_flags_do_not_reset_saved_settings(cli_studio, photo, capsys):
    cli_studio.opt_hdr = True
    cli_studio.breast_size = 88
    run(["generate", photo, "--safe"], cli_studio, capsys)
    assert cli_studio.opt_hdr is True
    assert cli_studio.breast_size == 88


def test_hair_preset_resolves_to_hex(cli_studio, photo, capsys):
    run(["generate", photo, "--hair-preset", "Auburn Red"], cli_studio, capsys)
    assert cli_studio.hair_base_color == "#A03A24"


def test_hair_color_accepts_hex_and_normalises_case(cli_studio, photo, capsys):
    run(["generate", photo, "--hair-color", "#ff8800"], cli_studio, capsys)
    assert cli_studio.hair_base_color == "#FF8800"


def test_generate_does_not_persist_settings(cli_studio, photo, capsys):
    """A one-shot run must not silently rewrite the saved profile."""
    run(["generate", photo, "--breast", "77"], cli_studio, capsys)
    saved = json.loads((cli_studio and open(settings_mod.SETTINGS_PATH).read()))
    assert saved["breast_size"] != 77


def test_config_set_does_persist(cli_studio, capsys):
    run(["config", "set", "--breast", "77"], cli_studio, capsys)
    saved = json.loads(open(settings_mod.SETTINGS_PATH).read())
    assert saved["breast_size"] == 77


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
@pytest.mark.parametrize("flag,value", [
    ("--breast", "500"), ("--breast", "-1"), ("--breast", "abc"),
    ("--hair-color", "zzz"), ("--hair-color", "#12345"),
])
def test_out_of_range_or_malformed_values_exit_2(cli_studio, photo, capsys, flag, value):
    assert cli.run(["generate", photo, flag, value], cli_studio) == 2


def test_unknown_hair_preset_exits_1_with_hint(cli_studio, photo, capsys):
    code, _, err = run(["generate", photo, "--hair-preset", "Chartreuse X"], cli_studio, capsys)
    assert code == 1
    assert "unknown hair preset" in err
    assert "config show" in err


def test_unknown_hairstyle_suggests_a_close_match(cli_studio, photo, capsys):
    code, _, err = run(["generate", photo, "--hair-style", "Loose Tousled Wave"], cli_studio, capsys)
    assert code == 1
    assert "Loose Tousled Waves" in err


def test_unknown_preset_template_exits_1(cli_studio, photo, capsys):
    code, _, err = run(["generate", photo, "--preset", "ghost"], cli_studio, capsys)
    assert code == 1
    assert "no saved template named 'ghost'" in err


def test_missing_image_exits_1(cli_studio, capsys):
    code, _, err = run(["generate", "definitely-missing.png"], cli_studio, capsys)
    assert code == 1
    assert "image not found" in err


def test_blank_text_input_exits_1(cli_studio, capsys):
    code, _, err = run(["tts", "--text", "   "], cli_studio, capsys)
    assert code == 1
    assert "no prompt text" in err


# --------------------------------------------------------------------------
# stream separation
# --------------------------------------------------------------------------
def test_result_goes_to_stdout_and_nothing_else(cli_studio, capsys):
    code, out, err = run(["tts", "--text", "She stands outside."], cli_studio, capsys)
    assert code == 0
    assert "She stands outside." in out
    assert err == ""


def test_out_flag_writes_a_clean_file(cli_studio, tmp_path, capsys):
    dest = tmp_path / "prompt.txt"
    code, out, err = run(["tts", "--text", "She stands outside.", "-o", str(dest)],
                          cli_studio, capsys)
    body = dest.read_text(encoding="utf-8")
    assert code == 0
    assert "She stands outside." in body
    assert "wrote" in err
    assert out == ""


def test_json_output_is_parseable(cli_studio, capsys):
    code, out, _ = run(["history", "list", "--json"], cli_studio, capsys)
    assert code == 0
    assert json.loads(out) == {"items": []}


# --------------------------------------------------------------------------
# the security-critical one
# --------------------------------------------------------------------------
SECRET = "SECRET-KEY-abcdef0123456789"


def test_cloud_key_is_never_printed(cli_studio, capsys):
    cli_studio.cloud_api_key = SECRET
    for argv in (["config", "show"], ["config", "show", "--json"],
                 ["backend"], ["history", "list"], ["models"]):
        code, out, err = run(argv, cli_studio, capsys)
        assert code == 0
        assert SECRET not in out
        assert SECRET not in err


def test_config_show_reports_key_presence_without_the_key(cli_studio, capsys):
    cli_studio.cloud_api_key = SECRET
    code, out, _ = run(["config", "show", "--json"], cli_studio, capsys)
    assert code == 0
    assert json.loads(out)["has_cloud_key"] is True


def test_clear_key_empties_and_persists(cli_studio, capsys):
    cli_studio.cloud_api_key = SECRET
    code, _, _ = run(["config", "clear-key"], cli_studio, capsys)
    assert code == 0
    assert cli_studio.cloud_api_key == ""
    assert json.loads(open(settings_mod.SETTINGS_PATH).read())["cloud_api_key"] == ""


def test_set_key_never_echoes_the_key(cli_studio, monkeypatch, capsys):
    monkeypatch.setenv("GEMMA_CLOUD_API_KEY", SECRET)
    code, out, err = run(["config", "set-key"], cli_studio, capsys)
    assert code == 0
    assert cli_studio.cloud_api_key == SECRET
    assert SECRET not in out
    assert SECRET not in err


# --------------------------------------------------------------------------
# commands that need the model
# --------------------------------------------------------------------------
def test_caption_uses_vibe_and_length(cli_studio, photo, monkeypatch, capsys):
    seen = {}

    class Recorder(StubClient):
        def generate(self, **kw):
            seen.update(kw)
            return super().generate(**kw)

    monkeypatch.setattr(ollama_mod, "local_client", lambda **kw: Recorder())
    code, out, _ = run(["caption", photo, "--vibe", "hype", "--length", "short"],
                       cli_studio, capsys)
    assert code == 0
    assert "STUB:" in out
    assert "rooftop" in seen["prompt"]          # the hype vibe
    assert "under 80 characters" in seen["prompt"]  # the short rule


def test_caption_falls_back_to_defaults_for_unknown_vibe(cli_studio, photo, monkeypatch, capsys):
    seen = {}

    class Recorder(StubClient):
        def generate(self, **kw):
            seen.update(kw)
            return super().generate(**kw)

    monkeypatch.setattr(ollama_mod, "local_client", lambda **kw: Recorder())
    run(["caption", photo, "--vibe", "nonsense", "--length", "nonsense"], cli_studio, capsys)
    assert "just chatting with friends" in seen["prompt"]   # casual default
    assert "between 100 and 200 characters" in seen["prompt"]  # medium default


def test_generate_writes_history(cli_studio, photo, capsys):
    run(["generate", photo], cli_studio, capsys)
    items = history_mod.list_history(10)
    assert items and items[0]["kind"] == "generate"


def test_generate_uses_the_injected_studio_not_the_singleton(cli_studio, photo, capsys):
    """Regression: run_generation used to read the global STUDIO, ignoring the
    instance the CLI passes - so per-invocation flags were silently dropped."""
    from studio.studio import STUDIO
    before = STUDIO.breast_size
    run(["generate", photo, "--breast", "64"], cli_studio, capsys)
    assert cli_studio.breast_size == 64
    assert STUDIO.breast_size == before


def test_refine_reports_when_the_original_was_kept(cli_studio, capsys):
    """A refused polish must be visible, not look like a successful rewrite."""
    text = "A woman standing. HEX VALUES: #A03A24"
    code, out, err = run(["refine", "--text", text], cli_studio, capsys)
    assert code == 0
    assert "note:" in err
    assert "dropped-hex" in err


def test_refine_succeeds_when_output_passes_the_guard(cli_studio, monkeypatch, capsys):
    long_text = "A woman standing in a park. " * 20
    class Ok(StubClient):
        def generate(self, **kw):
            return {"response": long_text + " extra"}
    monkeypatch.setattr(ollama_mod, "local_client", lambda **kw: Ok())
    code, _, err = run(["refine", "--text", long_text], cli_studio, capsys)
    assert code == 0
    assert "note:" not in err


def test_inject_uses_the_stubbed_client(cli_studio, capsys):
    code, out, _ = run(["inject", "--text", "A girl in a park."], cli_studio, capsys)
    assert code == 0
    assert "A girl in a park." in out


def test_outfit_describes_the_image(cli_studio, photo, capsys):
    code, out, _ = run(["outfit", photo], cli_studio, capsys)
    assert code == 0
    assert "STUB:" in out


def test_avatar_writes_a_png(cli_studio, tmp_path, capsys):
    dest = tmp_path / "me.png"
    code, _, _ = run(["avatar", "-o", str(dest), "--breast", "60"], cli_studio, capsys)
    assert code == 0
    assert dest.exists()
    with Image.open(dest) as im:
        assert im.format == "PNG"


# --------------------------------------------------------------------------
# templates & config
# --------------------------------------------------------------------------
def test_template_save_load_delete_roundtrip(cli_studio, photo, capsys):
    run(["templates", "save", "smoke", "--breast", "66", "--hair-style", "Messy Bun"],
        cli_studio, capsys)
    assert "smoke" in cli_studio.templates

    cli_studio.breast_size = 10
    cli_studio.hairstyle = "Box Braids"
    run(["templates", "load", "smoke"], cli_studio, capsys)
    assert cli_studio.breast_size == 66
    assert cli_studio.hairstyle == "Messy Bun"

    run(["templates", "delete", "smoke"], cli_studio, capsys)
    assert "smoke" not in cli_studio.templates


def test_config_show_lists_valid_values(cli_studio, capsys):
    code, out, _ = run(["config", "show"], cli_studio, capsys)
    assert code == 0
    assert "valid values:" in out
    assert "hair preset" in out
    assert "caption vibe" in out


def test_config_set_requires_a_flag(cli_studio, capsys):
    code, _, err = run(["config", "set"], cli_studio, capsys)
    assert code == 1
    assert "nothing to set" in err


def test_history_clear_removes_entries(cli_studio, photo, capsys):
    run(["generate", photo], cli_studio, capsys)
    assert history_mod.list_history(5)
    code, out, _ = run(["history", "clear"], cli_studio, capsys)
    assert code == 0
    assert history_mod.list_history(5) == []
    assert "cleared" in out
