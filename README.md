# ePersona Studio

Turn a reference photo into a detailed, editable image-generation prompt — from a
desktop GUI or the terminal.

You drop in a photo, pick a vision model, and it writes you a prompt describing
the person: pose, hair, skin tone, lighting, camera, composition. You then tune
it with sliders, save presets, and copy it out to whatever image generator you
use. The tool never generates images itself — it produces the *prompt*.

Both front ends drive the same engine, so a preset saved in the GUI works
identically from the CLI.

---

## What it does

- **Vision-to-prompt** — Ollama (multimodal) or Florence-2 describe your photo.
- **Editable output** — body proportion, hair, skin tone, and 8 render toggles,
  all live-adjustable. The prompt is regenerated around your edits, not rebuilt
  from scratch.
- **Targeted edits, not rewrites** — changing one slider patches the relevant
  section of the existing prompt and leaves the rest of it intact.
- **Presets** — save named templates and recall them with `--preset`.
- **Caption generator** — tone + length selectors for a Twitter/X caption with
  a rule-enforced emoji and hashtag format.
- **Outfit description** — a structured 7-category description for consistent
  clothing across renders.
- **Text-to-speech** — speak a draft aloud for hands-free review.
- **Local-first** — binds to `127.0.0.1` by default. Your photos and API keys
  stay on your machine.

---

## Requirements

- Python 3.11+ (developed and tested on 3.14.6)
- [Ollama](https://ollama.com) — either running locally, or an Ollama Cloud key
- Windows / macOS / Linux
- ~8 GB RAM minimum; 16 GB+ if using a 31B model

```bash
pip install -r requirements.txt
```

> **Florence-2 note:** `transformers` 4.57.6 changed an internal Florence-2
> attention call. `patch_florence2.py` handles the compatibility shim, and
> `ensure_deps.py` applies it automatically during setup. Don't remove it.

---

## Quick start

### Desktop GUI

```bash
python main.py
```

Or double-click **`RUN.bat`** on Windows — it installs missing dependencies,
applies the Florence-2 patch, and launches.

### CLI

```bash
python cli.py generate photo.jpg > prompt.txt
```

On Windows, `CLI.bat` runs it with a double-click. The result goes to **stdout**
and progress to **stderr**, so redirects and pipes work as expected:

```bash
studio generate photo.jpg --hair-preset "Auburn Red" --breast 70 > prompt.txt
studio caption photo.jpg --vibe hype --length short | pbcopy
studio tts --file draft.txt --no-hdr
```

---

## CLI reference

| Command | Purpose |
|---|---|
| `generate` | Full prompt from a photo |
| `caption` | Twitter/X caption with tone + length |
| `outfit` | Structured clothing description |
| `refine` | Re-patch an existing prompt with new settings |
| `tts` | Speak a draft aloud |
| `inject` | Insert text into a prompt at a section |
| `avatar` | Save a placeholder portrait |
| `models` | List locally available Ollama models |
| `backend` | Backend health + diagnostic report |
| `config` | `show` / `set` / `set-key` / `clear-key` |
| `history` | `list` / `clear` generated prompts |
| `templates` | `list` / `save` / `load` / `delete` presets |

Shared flags: `-o/--out FILE` (write to file), `--json` (machine-readable),
`-q/--quiet` (suppress progress), `--model`, `--pose-model`, `--backend`.

`--no-<flag>` turns off any boolean enhancement (`--no-dof`, `--no-hdr`,
`--no-realism`, `--no-tattoos`, `--no-safe`, …).

```bash
studio generate photo.jpg --json | jq .prompt
studio backend --json          # is Ollama up? which models exist?
studio config set --breast 70 --hair-length 40
```

**Keys never appear in output.** `config show` prints `has_cloud_key: true/false`;
`config set-key` reads via hidden input or `$GEMMA_CLOUD_API_KEY`, so the key
stays out of your shell history.

---

## Configuration

Settings live in `settings.json` (gitignored, created on first run).

| Group | Keys |
|---|---|
| Models | `selected_model`, `pose_model`, `vlm_backend`, `num_ctx` |
| Appearance | `breast_size`, `hip_size`, `hair_length`, `hair_brightness`, `hair_base_color`, `hairstyle`, `skin_tone` |
| Render toggles | `opt_noise`, `opt_dof`, `opt_realism`, `opt_hdr`, `opt_no_tattoos`, `opt_naked`, `opt_safe`, `opt_compact`, `use_default_details` |
| Content | `prompt_template`, `user_notes` |
| Credentials | `cloud_api_key` |

`user_notes` is treated as highest-priority ground truth: whatever you write
there overrides what the vision model inferred.

> **Note on `opt_safe`:** the safety filter defaults to **off**. If you want
> prompts to be steered away from explicit content, turn it on with
> `--safe` in the CLI or the GUI toggle. This is a prompt-steering flag only —
> it does not filter the reference photo.

---

## How it works

```
   photo.jpg
       │
       ├──► vision backend ──► raw description
       │     (Ollama VLM / Florence-2)
       │            │
       │            ▼
       │     prompt_builder ──► structured prompt
       │            │            (subject, wardrobe, lighting, camera…)
       │            │
       │            ▼
       │     inject ──────────► targeted edits, rest of prompt preserved
       │            │
       ▼            ▼
   caption      outfit ──────► structured text
   (own prompt) (own prompt)
       │            │
       └──────┬─────┘
              ▼
        stdout / GUI / clipboard
```

The caption and outfit prompts are **single shared modules**, not copies in the
HTTP layer and the CLI. `tests/test_caption_prompts.py` diffs them against the
version in git history, so a refactor that rewords a prompt fails a test rather
than quietly changing output.

### Layout

| Path | Role |
|---|---|
| `main.py` / `server.py` | Entry points — pywebview window, or uvicorn |
| `studio/studio.py` | Facade holding settings + model clients |
| `studio/pipeline.py` | Orchestrates a generation run |
| `studio/prompt_builder.py` | Composes the structured prompt |
| `studio/inject.py` | Applies targeted edits to an existing prompt |
| `studio/vlm_ollama.py`, `studio/vlm_florence.py` | Vision backends |
| `studio/caption.py`, `studio/outfit.py` | Shared caption / outfit prompts |
| `studio/routes.py` | FastAPI HTTP layer |
| `studio/cli.py` | argparse CLI |
| `static/` | GUI — vanilla JS, no build step |
| `tests/` | 174 tests |

The GUI is dependency-free vanilla JS served straight from `static/` — no
bundler, no `node_modules`, no build step to break.

---

## Models

Defaults target Ollama Cloud, but local models work too:

- `gemma4:31b` — default generator
- `minicpm-v4.6:latest` — default pose/detail specialist (`--pose-model none` to disable)
- `gemma3:4b` — lighter local option

```bash
ollama pull gemma3:4b
studio generate photo.jpg --model gemma3:4b
```

Set a key once with `studio config set-key`; it persists to `settings.json`.

---

## Testing

```bash
python -m pytest -q          # 174 tests
python _check_encoding.py    # UTF-8 / mojibake guard
python _precommit_secrets.py # staged + history credential scan
```

The suite covers backend timeouts, prompt fidelity, HTTP status mapping, CLI
parsing and output routing, exit codes, and that the cloud key can never be
printed.

`tests/prompt_golden.json` holds the caption and outfit prompts byte for byte as
they were before they were extracted into shared modules.
`tests/test_caption_prompts.py` asserts the current code still renders them
identically, so a refactor that rewords a prompt fails a test instead of quietly
changing output. If you change a prompt deliberately, regenerate and review the
diff:

```bash
python _make_golden.py
```

---

## Security

- `settings.json` is gitignored and holds the API key. `_precommit_secrets.py`
  scans the staged diff **and the entire git history** for the live key and its
  prefix, and fails the commit on a hit.
- `/api/state` exposes only `has_cloud_key: true|false`. The key itself is never
  in the state payload.
- The server binds to `127.0.0.1`. If you expose it, it does not authenticate —
  put it behind a reverse proxy with auth first.
- `uploads/` is gitignored so reference photos aren't committed by accident.

---

## License

Not yet specified. Until a license is added, the default is "all rights
reserved" — add one before distributing.

## Contributing

Open an issue or PR. Please run `python -m pytest -q` and
`python _check_encoding.py` before submitting — both should pass.
