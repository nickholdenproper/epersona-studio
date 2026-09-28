"""Command-line interface for ePersona Studio.

Reuses the exact engine the GUI uses (same Studio singleton, same pipeline, same
settings file), so a prompt produced here is identical to one produced in the
browser.

Stream discipline, so the CLI composes in a shell:
  - the result (prompt / caption / description) goes to **stdout**
  - progress, warnings and diagnostics go to **stderr**

So `studio generate photo.jpg > prompt.txt` writes a clean file, and
`studio caption photo.jpg --vibe hype | pbcopy` works on Windows.
"""
import argparse
import json
import os
import sys

from . import log
from .caption import LENGTH_RULES, VIBE_PROMPTS, write_caption
from .config import (HAIR_COLOR_PRESETS, HAIRSTYLES, PROMPT_TEMPLATES,
                     SKIN_TONES)
from .florence import florence_available
from .history import append_history, clear_history, list_history
from .inject import inject_prompt
from .ollama import (backend_report, client_for_model, list_models,
                     resolve_model, set_cloud_key)
from .outfit import describe_outfit
from .pipeline import refine_prompt_text, run_generation
from .tts import tts_transform

logger = log.get_logger(__name__)

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

# Body Studio sliders, all 0-100.
SLIDER_FIELDS = ('breast_size', 'hip_size', 'hair_length', 'hair_brightness')
# Enhancement toggles shared with the GUI. Tri-state flags: --noise/--no-noise.
TOGGLE_FIELDS = ('opt_noise', 'opt_dof', 'opt_realism', 'opt_hdr',
                 'opt_no_tattoos', 'opt_naked', 'opt_safe', 'opt_compact',
                 'use_default_details')

# CLI-friendly aliases for the GUI's opt_* attribute names. Keys are argparse
# dest names, so a dashed flag like --default-details lands here underscored.
TOGGLE_ALIASES = {
    'noise': 'opt_noise', 'dof': 'opt_dof', 'realism': 'opt_realism',
    'hdr': 'opt_hdr', 'tattoos': 'opt_no_tattoos', 'naked': 'opt_naked',
    'safe': 'opt_safe', 'compact': 'opt_compact',
    'default_details': 'use_default_details',
}
# Only the flags whose meaning is inverted relative to the stored attribute.
# --tattoos means "opt_no_tattoos = False". --default-details maps straight
# across, so it must NOT be listed here.
INVERTED_FLAGS = {'tattoos'}
# CLI slider flag -> Studio attribute.
SLIDER_ALIASES = {
    'breast': 'breast_size', 'hips': 'hip_size',
    'hair_length': 'hair_length', 'hair_brightness': 'hair_brightness',
}

# Fields captured by a saved template, mirroring routes.TEMPLATE_FIELDS.
TEMPLATE_FIELDS = list(SLIDER_FIELDS) + [
    'opt_noise', 'opt_dof', 'opt_realism', 'opt_hdr', 'opt_no_tattoos',
    'opt_naked', 'opt_safe', 'opt_compact', 'use_default_details',
    'prompt_template', 'hair_base_color', 'hairstyle', 'skin_tone',
]


class CliError(Exception):
    """A user-facing failure: printed as `error: ...`, exits 1, no traceback."""


# --------------------------------------------------------------------------
# argument helpers
# --------------------------------------------------------------------------
def _pct(value):
    """argparse type for a 0-100 slider."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number")
    if not 0 <= n <= 100:
        raise argparse.ArgumentTypeError(f"must be between 0 and 100 (got {n})")
    return n


def _hexcolor(value):
    v = (value or '').strip()
    if not v.startswith('#') or len(v) != 7:
        raise argparse.ArgumentTypeError("expected a hex colour like #A03A24")
    try:
        int(v[1:], 16)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{v!r} is not a valid hex colour")
    return v.upper()


def _read_text_arg(args, *, prompt="Paste or pipe the prompt text: "):
    """Resolve prompt text from --text, a file, or stdin.

    `-` means stdin, so prompts can be piped without a temp file. Blank input
    is rejected here: the transforms happily turn an empty string into a bare
    body/hair/skin fragment, which is worse than an error.
    """
    if getattr(args, 'text', None) is not None:
        text = args.text
    elif getattr(args, 'file', None) == '-':
        text = sys.stdin.read()
    else:
        text = input(prompt)
    if not text or not text.strip():
        raise CliError("no prompt text given (use --text, --file, or pipe on stdin)")
    return text


def _resolve_image(path, what="image"):
    if not path:
        raise CliError(f"no {what} path given")
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(p):
        raise CliError(f"{what} not found: {p}")
    ext = os.path.splitext(p)[1].lower()
    if ext not in IMAGE_EXTS:
        raise CliError(f"unsupported {what} type '{ext}' (use {', '.join(IMAGE_EXTS)})")
    return p


# --------------------------------------------------------------------------
# settings payload from flags
# --------------------------------------------------------------------------
def payload_from_args(args):
    """Build the settings payload described by the parsed flags.

    Only keys the user actually passed are included, so anything omitted keeps
    the saved profile instead of being reset to a default.
    """
    p = {}
    for flag, attr in (('model', 'selected_model'),
                       ('pose_model', 'selected_pose_model'),
                       ('backend', 'vlm_backend'),
                       ('hair_style', 'hairstyle'),
                       ('skin_tone', 'skin_tone'),
                       ('prompt_template', 'prompt_template'),
                       ('num_ctx', 'num_ctx'),
                       ('notes', 'user_notes')):
        v = getattr(args, flag, None)
        if v is not None:
            p[attr] = v

    for flag, attr in SLIDER_ALIASES.items():
        v = getattr(args, flag, None)
        if v is not None:
            p[attr] = v

    # --hair-preset resolves a name to its hex; --hair-color is the raw escape hatch.
    if getattr(args, 'hair_preset', None):
        wanted = args.hair_preset.strip().lower()
        for name, hexv in HAIR_COLOR_PRESETS:
            if name.lower() == wanted:
                p['hair_base_color'] = hexv
                break
        else:
            raise CliError(f"unknown hair preset {args.hair_preset!r}; "
                           f"see `studio config show`")
    if getattr(args, 'hair_color', None):
        p['hair_base_color'] = args.hair_color

    for flag, attr in TOGGLE_ALIASES.items():
        v = getattr(args, flag, None)
        if v is None:
            continue
        p[attr] = (not v) if flag in INVERTED_FLAGS else v
    return p


def _validate_payload(studio, payload):
    """Reject values the engine would silently drop, rather than ignoring them."""
    checks = (
        ('hairstyle', HAIRSTYLES, 'hairstyle'),
        ('skin_tone', SKIN_TONES, 'skin tone'),
        ('prompt_template', PROMPT_TEMPLATES, 'prompt template'),
        ('vlm_backend', studio.VLM_BACKENDS, 'VLM backend'),
    )
    for key, valid, label in checks:
        if key in payload and payload[key] not in valid:
            close = _suggest(payload[key], list(valid))
            raise CliError(f"unknown {label} {payload[key]!r}"
                           + (f" - did you mean {close!r}?" if close else ""))


def _suggest(value, options):
    """Cheap 'did you mean' match, so a typo in a long hairstyle name is obvious."""
    v = (value or '').strip().lower()
    if not v:
        return None
    for o in options:
        if o.lower() == v:
            return o
    hits = [o for o in options if v in o.lower() or o.lower() in v]
    return hits[0] if len(hits) == 1 else None


def _apply(studio, args, persist=False):
    payload = payload_from_args(args)
    _validate_payload(studio, payload)
    if getattr(args, 'preset', None):
        name = args.preset
        if name not in studio.templates:
            raise CliError(f"no saved template named {name!r}; "
                           f"see `studio templates list`")
        payload.update(studio.templates[name])
        _validate_payload(studio, payload)
    if payload:
        studio.apply_updates(payload, persist=persist)
    return payload


# --------------------------------------------------------------------------
# commands - each returns a dict payload
# --------------------------------------------------------------------------
def cmd_generate(args, studio):
    path = _resolve_image(args.image)
    _apply(studio, args)

    if getattr(args, 'outfit', None):
        studio.outfit_description = _read_outfit_text(args.outfit)
        studio.outfit_active = True

    studio.image_path = path
    for cache in (studio._vlm_pose_cache, studio._vlm_clothing_cache, studio._vlm_env_cache):
        cache.clear()
    studio.last_pose_gt, studio.last_clothing_gt, studio.last_env_gt = {}, None, None
    studio.detected_colors = studio.extract_colors(path)

    result = run_generation(studio)
    prompt = result.get('prompt') or ''
    append_history('generate', prompt, studio.prompt_template)
    return {'prompt': prompt, 'description': result.get('description', '')}


def _read_outfit_text(value):
    """--outfit takes a description string, a file path, or '-' for stdin."""
    if value == '-':
        return sys.stdin.read().strip()
    if os.path.isfile(value):
        with open(value, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return value.strip()


def cmd_caption(args, studio):
    path = _resolve_image(args.image)
    _apply(studio, args)
    caption = write_caption(studio, path, args.vibe, args.length)
    append_history('caption', caption, studio.prompt_template)
    return {'caption': caption}


def cmd_outfit(args, studio):
    path = _resolve_image(args.image, "outfit image")
    _apply(studio, args)
    desc = describe_outfit(studio, path)
    append_history('outfit', desc, studio.prompt_template)
    return {'description': desc}


def cmd_refine(args, studio):
    _apply(studio, args)
    text = _read_text_arg(args).strip()
    model = resolve_model(studio.selected_model)
    if not model:
        raise CliError(f"{studio.selected_model} is not available locally or on "
                       f"Ollama Cloud; run: ollama pull {studio.selected_model}")
    refined, status = refine_prompt_text(client_for_model(model), model, text)
    append_history('refine', refined, studio.prompt_template)
    # The engine keeps the original when the polish fails a safety guard; say so
    # rather than letting it look like the rewrite worked.
    return {'prompt': refined, 'status': status, 'changed': status == 'ok'}


def cmd_tts(args, studio):
    _apply(studio, args)
    text = _read_text_arg(args)
    result = tts_transform(studio, text)
    append_history('tts', result.get('result'), studio.prompt_template)
    return {'result': result.get('result', '')}


def cmd_inject(args, studio):
    _apply(studio, args)
    text = _read_text_arg(args)
    model = resolve_model(studio.selected_model)
    # inject_prompt copes with client_=None by falling back to local rules.
    res = inject_prompt(studio, client_for_model(model) if model else None, text, model=model)
    append_history('inject', res.get('result'), studio.prompt_template)
    return res


def cmd_avatar(args, studio):
    _apply(studio, args)
    png = studio.avatar_png()
    out = args.out or 'avatar.png'
    with open(out, 'wb') as f:
        f.write(png)
    return {'file': os.path.abspath(out), 'bytes': len(png)}


def cmd_models(args, studio):
    models = list_models()
    if args.json:
        return {'models': models}
    if not models:
        return {'models': [], 'text': 'no models found - is ollama running? (ollama serve)'}
    return {'models': models,
            'text': '\n'.join(models)}


def cmd_backend(args, studio):
    report = backend_report()
    if args.json:
        return {'backend': report}
    lines = [f"mode: {report['mode']}"]
    for kind in ('local', 'cloud'):
        info = report[kind]
        state = 'up' if info['reachable'] else 'down'
        extra = ' (key loaded)' if kind == 'cloud' and info.get('enabled') else ''
        lines.append(f"{kind:>6}: {state}{extra}  {len(info['models'])} model(s)")
    lines.append(f"florence: {'available' if florence_available() else 'not loaded'}")
    return {'backend': report, 'text': '\n'.join(lines)}


def cmd_config_show(args, studio):
    d = {
        'model': studio.selected_model,
        'pose_model': studio.selected_pose_model or '(none)',
        'backend': studio.vlm_backend,
        'num_ctx': studio.num_ctx,
        'prompt_template': studio.prompt_template,
        'hair_base_color': studio.hair_base_color,
        'hairstyle': studio.hairstyle,
        'skin_tone': studio.skin_tone,
        'user_notes': studio.user_notes,
        **{f: getattr(studio, f) for f in SLIDER_FIELDS + TOGGLE_FIELDS},
        # Never print the key. `config set-key` writes it; this only reports
        # whether one is present, so a shared terminal / CI log stays safe.
        'has_cloud_key': bool(studio.cloud_api_key),
        'florence_available': florence_available(),
    }
    if args.json:
        return d
    lines = [f"{k:>20}: {v}" for k, v in d.items()]
    lines += ['', 'valid values:',
              f"  backend        : {', '.join(studio.VLM_BACKENDS)}",
              f"  prompt template: {', '.join(PROMPT_TEMPLATES)}",
              f"  skin tone      : {', '.join(SKIN_TONES)}",
              f"  hairstyle      : {', '.join(HAIRSTYLES)}",
              f"  hair preset    : {', '.join(n for n, _ in HAIR_COLOR_PRESETS)}",
              f"  caption vibe   : {', '.join(VIBE_PROMPTS)}",
              f"  caption length : {', '.join(LENGTH_RULES)}"]
    return {'text': '\n'.join(lines)}


def cmd_config_set(args, studio):
    """Persist the current settings (optionally after applying flags)."""
    payload = payload_from_args(args)
    if not payload:
        raise CliError("nothing to set; pass a flag such as --model, or run "
                       "`studio config show`")
    _validate_payload(studio, payload)
    studio.apply_updates(payload, persist=True)
    return {'saved': sorted(payload)}


def cmd_config_set_key(args, studio):
    """Store the Ollama Cloud key without putting it in shell history.

    Reads GEMMA_CLOUD_API_KEY when set, otherwise prompts with echo off.
    """
    key = (os.environ.get('GEMMA_CLOUD_API_KEY') or '').strip()
    if args.stdin:
        key = sys.stdin.read().strip()
    elif not key:
        import getpass
        key = getpass.getpass('Ollama Cloud API key (input hidden): ').strip()
    if not key:
        raise CliError("no key given (set GEMMA_CLOUD_API_KEY or type it at the prompt)")
    studio.apply_updates({'cloud_api_key': key}, persist=True)
    set_cloud_key(studio.cloud_api_key)
    return {'saved': 'cloud_api_key', 'length': len(key)}


def cmd_config_clear_key(args, studio):
    studio.apply_updates({'clear_cloud_key': True}, persist=True)
    set_cloud_key('')
    return {'cleared': 'cloud_api_key'}


def cmd_history(args, studio):
    if args.clear:
        clear_history()
        return {'cleared': True, 'text': 'history cleared'}
    items = list_history(args.limit)
    if args.json:
        return {'items': items}
    if not items:
        return {'items': [], 'text': 'no history yet'}
    lines = []
    for it in items:
        body = ' '.join((it.get('prompt') or '').split())
        if args.full:
            body = it.get('prompt') or ''
        elif len(body) > 72:
            body = body[:69] + '...'
        lines.append(f"{it.get('ts','')}  [{it.get('kind','')}]  {body}")
    return {'items': items, 'text': '\n'.join(lines)}


def cmd_templates_list(args, studio):
    names = sorted(studio.templates)
    if args.json:
        return {'templates': names}
    if not names:
        return {'templates': [], 'text': 'no saved templates'}
    return {'templates': names, 'text': '\n'.join(names)}


def cmd_templates_save(args, studio):
    _apply(studio, args)
    name = args.name.strip()
    if not name:
        raise CliError("template name required")
    studio.templates[name] = {f: getattr(studio, f) for f in TEMPLATE_FIELDS}
    studio.save_settings()
    return {'saved': name, 'templates': sorted(studio.templates)}


def cmd_templates_load(args, studio):
    if args.name not in studio.templates:
        raise CliError(f"no saved template named {args.name!r}")
    studio.apply_updates(studio.templates[args.name], persist=True)
    return {'loaded': args.name}


def cmd_templates_delete(args, studio):
    if args.name not in studio.templates:
        raise CliError(f"no saved template named {args.name!r}")
    del studio.templates[args.name]
    studio.save_settings()
    return {'deleted': args.name, 'templates': sorted(studio.templates)}


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def _studio_options():
    """Flags shared by every command that touches the engine."""
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group('body studio')
    g.add_argument('-m', '--model', help='generation model (default: saved setting)')
    g.add_argument('-p', '--pose-model', default=argparse.SUPPRESS,
                   metavar='MODEL', help="specialist vision model; 'none' to disable")
    g.add_argument('--backend', choices=['Ollama', 'Florence-2'],
                   help='vision backend')
    g.add_argument('--preset', help='load a saved template before running')
    g.add_argument('--notes', help='user notes; treated as highest-priority ground truth')

    g = p.add_argument_group('appearance')
    g.add_argument('--breast', type=_pct, metavar='0-100')
    g.add_argument('--hips', type=_pct, metavar='0-100')
    g.add_argument('--hair-length', type=_pct, metavar='0-100')
    g.add_argument('--hair-brightness', type=_pct, metavar='0-100')
    g.add_argument('--hair-color', type=_hexcolor, metavar='#RRGGBB')
    g.add_argument('--hair-preset', metavar='NAME', help='hair colour by preset name')
    g.add_argument('--hair-style', metavar='NAME', help='hairstyle name')
    g.add_argument('--skin-tone', metavar='NAME', help='skin tone name')
    g.add_argument('--prompt-template', metavar='NAME', help='prompt template name')
    g.add_argument('--num-ctx', type=int, metavar='N', help='context window (min 8192)')

    g = p.add_argument_group('enhancements (--no-X turns one off)')
    for flag, attr in TOGGLE_ALIASES.items():
        # argparse turns dashes back into underscores for dest, so --default-details
        # lands on args.default_details, which is what TOGGLE_ALIASES is keyed by.
        g.add_argument(f'--{flag.replace("_", "-")}',
                       action=argparse.BooleanOptionalAction,
                       default=None, help=attr.replace('_', ' ').replace('opt ', ''))
    return p


def _output_options():
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group('output')
    g.add_argument('-o', '--out', metavar='FILE', help='write the result to FILE')
    g.add_argument('--json', action='store_true', help='machine-readable output')
    g.add_argument('-q', '--quiet', action='store_true',
                   help='suppress progress on stderr')
    return p


def _text_options():
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group('input text')
    g.add_argument('--text', help='prompt text (skips the interactive prompt)')
    g.add_argument('--file', help='read the text from FILE, or - for stdin')
    return p


def build_parser():
    shared = _studio_options()
    out = _output_options()
    text = _text_options()
    both = [shared, out]

    ap = argparse.ArgumentParser(
        prog='studio',
        description='ePersona Studio command line.',
        epilog='Result goes to stdout; progress and diagnostics go to stderr.',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='command', metavar='<command>')

    def add(name, func, parents, help_):
        p = sub.add_parser(name, parents=parents, help=help_, description=help_)
        p.set_defaults(func=func)
        return p

    p = add('generate', cmd_generate, both,
            'Turn a photo into a detailed image-generation prompt.')
    p.add_argument('image', help='source photo')
    p.add_argument('--outfit', metavar='TEXT|FILE|-',
                   help='outfit description to inject (text, file, or - for stdin)')

    p = add('caption', cmd_caption, both,
            'Write a Twitter/X caption for a photo.')
    p.add_argument('image')
    p.add_argument('--vibe', default='casual', metavar='NAME',
                   help='tone (see `studio config show`)')
    p.add_argument('--length', default='medium', metavar='NAME',
                   help='short | medium | long')

    p = add('outfit', cmd_outfit, both,
            'Describe the outfit in a flat-lay or clothing photo.')
    p.add_argument('image')

    p = add('refine', cmd_refine, both + [text],
            'Polish an existing prompt for focus and consistency.')

    p = add('tts', cmd_tts, both + [text],
            'Strip body/hair from a prompt and re-inject current settings.')

    p = add('inject', cmd_inject, both + [text],
            'Rewrite an external prompt with the current Body Studio settings.')

    p = add('avatar', cmd_avatar, both,
            'Render the avatar preview to a PNG (default: avatar.png).')
    # NB: no p.set_defaults(out=...) here. argparse implements set_defaults by
    # mutating action.default, and parents= SHARES those action objects across
    # every subparser - so that would silently give every other command an
    # --out default of avatar.png. The default is applied in cmd_avatar instead.

    add('models', cmd_models, [out], 'List models available locally and on the cloud.')
    add('backend', cmd_backend, [out], 'Show which backend is reachable.')

    p = sub.add_parser('config', help='Inspect or change saved settings.')
    csub = p.add_subparsers(dest='subcommand', metavar='<subcommand>')
    q = csub.add_parser('show', parents=[out], help='print current settings (key masked)')
    q.set_defaults(func=cmd_config_show)
    q = csub.add_parser('set', parents=[shared], help='save settings from flags')
    q.set_defaults(func=cmd_config_set)
    q = csub.add_parser('set-key', help='store the Ollama Cloud key (input hidden)')
    q.add_argument('--stdin', action='store_true', help='read the key from stdin')
    q.set_defaults(func=cmd_config_set_key)
    q = csub.add_parser('clear-key', help='forget the stored Ollama Cloud key')
    q.set_defaults(func=cmd_config_clear_key)
    p.set_defaults(func=cmd_config_show, json=False)

    p = sub.add_parser('history', help='Browse the prompt history.')
    hsub = p.add_subparsers(dest='subcommand', metavar='<subcommand>')
    q = hsub.add_parser('list', parents=[out], help='list past prompts')
    q.add_argument('-n', '--limit', type=int, default=20, metavar='N')
    q.add_argument('--full', action='store_true', help='do not truncate prompts')
    q.set_defaults(func=cmd_history)
    q = hsub.add_parser('clear', help='delete the history file')
    q.set_defaults(func=cmd_history, clear=True, limit=0, json=False, full=False)
    p.set_defaults(func=cmd_history, limit=20, full=False, json=False)

    p = sub.add_parser('templates', help='Manage saved Body Studio templates.')
    tsub = p.add_subparsers(dest='subcommand', metavar='<subcommand>')
    q = tsub.add_parser('list', parents=[out], help='list saved templates')
    q.set_defaults(func=cmd_templates_list)
    q = tsub.add_parser('save', parents=[shared], help='save current settings as a template')
    q.add_argument('name')
    q.set_defaults(func=cmd_templates_save)
    q = tsub.add_parser('load', help='apply a saved template')
    q.add_argument('name')
    q.set_defaults(func=cmd_templates_load)
    q = tsub.add_parser('delete', help='delete a saved template')
    q.add_argument('name')
    q.set_defaults(func=cmd_templates_delete)
    p.set_defaults(func=cmd_templates_list, json=False)

    return ap


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
# Payload keys that are the actual result, in preference order.
RESULT_KEYS = ('prompt', 'caption', 'result', 'description', 'text')


def _primary(result):
    for k in RESULT_KEYS:
        v = result.get(k)
        if isinstance(v, str) and v:
            return v
    return ''


def _write_out(result, args):
    """Result -> stdout, or to --out. Metadata goes to stderr so a redirected
    file stays exactly the prompt."""
    text = _primary(result)
    if getattr(args, 'out', None) and 'file' not in result:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(text + ('\n' if text and not text.endswith('\n') else ''))
        print(f"wrote {args.out} ({len(text)} chars)", file=sys.stderr)
        return
    if args.json:
        printable = {k: v for k, v in result.items() if k != 'text'}
        print(json.dumps(printable, indent=2, ensure_ascii=False))
    elif text:
        print(text)


def _emit_notes(result, args):
    """Non-result diagnostics. Only shown when not writing a clean file."""
    if getattr(args, 'out', None) and 'file' not in result:
        return
    if not args.quiet:
        if result.get('status') and result['status'] != 'ok':
            print(f"note: kept the original prompt ({result['status']})", file=sys.stderr)
        if result.get('description') and not result.get('prompt'):
            print(result['description'], file=sys.stderr)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def run(argv, studio, stdout=None, stderr=None):
    """Parse and execute. Returns an exit code; never raises for user errors."""
    ap = build_parser()
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        # argparse has already printed the problem (bad int, unknown flag, or
        # --help). Convert to a return code so run() always yields an int.
        return int(e.code) if e.code is not None else 0

    if not getattr(args, 'command', None):
        ap.print_help(stderr or sys.stderr)
        return 2

    # Not every subcommand inherits the same groups, and a group-level parent
    # (e.g. bare `history`) only gets the defaults it declared. Normalise every
    # flag the command bodies and printers read, so no command trips over a
    # missing attribute.
    for name, default in (('json', False), ('quiet', False), ('out', None),
                          ('clear', False), ('full', False), ('limit', 20)):
        if not hasattr(args, name):
            setattr(args, name, default)

    if args.json:
        args.quiet = True

    def step(step_text):
        if not args.quiet:
            print(f"  ... {step_text}", file=stderr or sys.stderr)

    from . import pipeline
    previous_hook, pipeline.STEP_HOOK = pipeline.STEP_HOOK, step
    try:
        result = args.func(args, studio)
    except CliError as e:
        print(f"error: {e}", file=stderr or sys.stderr)
        return 1
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=stderr or sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=stderr or sys.stderr)
        return 130
    except Exception as e:  # unexpected: log the traceback, it is a real bug
        logger.error("[CLI] %s failed", args.command, exc_info=True)
        print(f"error: {args.command} failed: {e}", file=stderr or sys.stderr)
        return 1
    finally:
        pipeline.STEP_HOOK = previous_hook

    _write_out(result, args)
    _emit_notes(result, args)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    # Imported late: constructing STUDIO reads settings.json, which is wasted
    # work for `studio --help`.
    from .studio import STUDIO

    return run(argv, STUDIO)


if __name__ == '__main__':
    sys.exit(main())
