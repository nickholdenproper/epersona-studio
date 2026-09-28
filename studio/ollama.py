"""Ollama client helpers - local server first, Ollama Cloud fallback.

Every backend decision funnels through this module so the app keeps working
when the local server is down: the app then transparently talks to Ollama
Cloud (https://ollama.com) using an API key. Model lists are merged so cloud
models show up alongside local ones.
"""
import base64
import io
import re
import time

import ollama
from PIL import Image

from . import log
from .config import (CLOUD_MODELS, CLOUD_POSE_MODEL, DEFAULT_CLOUD_MODEL,
                     MODELS_CACHE_TTL, OLLAMA_CLOUD_API_KEY, OLLAMA_CLOUD_HOST,
                     OLLAMA_HOST)

logger = log.get_logger(__name__)

# The cloud API key is runtime-editable (persisted in settings.json). It starts
# from the config/env default and can be replaced via set_cloud_key().
_cloud_api_key = OLLAMA_CLOUD_API_KEY

# Generations can take minutes; connection probes need to fail fast.
LIST_TIMEOUT = 15.0
GENERATE_TIMEOUT = 600.0
LOCAL_PROBE_TIMEOUT = 5.0
BACKEND_PROBE_TTL = 10.0


# --------------------------------------------------------------------------
# Backend state (cached)
# --------------------------------------------------------------------------
_backends = {
    'local': {'ts': 0.0, 'reachable': False, 'models': []},
    'cloud': {'ts': 0.0, 'reachable': False, 'models': []},
}

_models_cache = {'ts': 0.0, 'items': []}


def set_cloud_key(key):
    """Swap the Ollama Cloud API key and invalidate cached cloud state."""
    global _cloud_api_key
    k = (key or '').strip()
    if k != _cloud_api_key:
        _cloud_api_key = k
        _backends['cloud']['ts'] = 0.0
        _models_cache['ts'] = 0.0


# --------------------------------------------------------------------------
# Client factories
# --------------------------------------------------------------------------
def local_client(timeout=GENERATE_TIMEOUT):
    """Ollama client bound to the local server.

    Defaults to the generation timeout: a 31B model writing a full prompt takes
    far longer than the 5s probe timeout, so reusing LOCAL_PROBE_TIMEOUT here
    made every local generation time out. Probing passes LOCAL_PROBE_TIMEOUT
    explicitly, so an unreachable server still fails fast.
    """
    return ollama.Client(host=OLLAMA_HOST, timeout=timeout)


def cloud_client(timeout=GENERATE_TIMEOUT):
    """Ollama client bound to Ollama Cloud, authenticated with the API key."""
    return ollama.Client(
        host=OLLAMA_CLOUD_HOST,
        headers={'Authorization': 'Bearer ' + _cloud_api_key},
        timeout=timeout,
    )


def cloud_enabled():
    return bool(OLLAMA_CLOUD_HOST and _cloud_api_key)


def _resolve_models(kind):
    """Fetch the live model list for a backend; returns (reachable, models)."""
    if kind == 'cloud' and not cloud_enabled():
        return False, []
    cli = (cloud_client(timeout=LIST_TIMEOUT) if kind == 'cloud'
           else local_client(timeout=LOCAL_PROBE_TIMEOUT))
    ml = cli.list()
    if hasattr(ml, 'models'):
        return True, [m.model for m in ml.models]
    return True, []


def _probe(kind):
    """Cached backend state: (reachable, models). Falls back to the advertised
    cloud catalog when the cloud API is unreachable."""
    st = _backends[kind]
    now = time.time()
    if now - st['ts'] < BACKEND_PROBE_TTL:
        return st['reachable'], list(st['models'])
    st['ts'] = now
    st['models'] = []
    st['reachable'] = False
    try:
        st['reachable'], st['models'] = _resolve_models(kind)
    except Exception as e:
        if kind == 'cloud':
            st['models'] = list(CLOUD_MODELS)
            logger.info("[OLLAMA] Cloud unreachable (%s) - advertising catalog", e)
        else:
            logger.info("[OLLAMA] Local server unreachable (%s)", e)
    return st['reachable'], list(st['models'])


def reset_models_cache():
    """Clear cached backend state and model lists (used by tests / refreshes)."""
    _models_cache['ts'] = 0.0
    _models_cache['items'] = []
    for st in _backends.values():
        st['ts'] = 0.0


def list_models(client_=None):
    """Merged model list with a short TTL cache.

    When an explicit `client_` is passed (tests), that client alone is used.
    Otherwise the union of local + cloud models is returned. On failure the
    last known list is returned; otherwise [] is kept.
    """
    now = time.time()
    if now - _models_cache['ts'] < MODELS_CACHE_TTL:
        return list(_models_cache['items'])
    items = []
    try:
        if client_ is not None:
            ml = client_.list()
            items = [m.model for m in ml.models] if hasattr(ml, 'models') else []
        else:
            items = _model_catalog()
        _models_cache['items'] = list(items)
        _models_cache['ts'] = now
        return items
    except Exception:
        return list(_models_cache['items'])


def _model_catalog():
    items = []
    for kind in ('local', 'cloud'):
        reached, models = _probe(kind)
        items.extend(m for m in models if m not in items)
    return items


def local_reachable():
    return _probe('local')[0]


def cloud_reachable():
    return _probe('cloud')[0]


def model_available(model):
    if not model:
        return False
    return any(model in _probe(kind)[1] for kind in ('local', 'cloud'))


def backend_report():
    """Reachability + model lists for both backends (for /api/state)."""
    l_ok, l_models = _probe('local')
    c_ok, c_models = _probe('cloud')
    if l_ok:
        mode = 'local'
    elif c_ok or cloud_enabled():
        mode = 'cloud'
    else:
        mode = 'off'
    return {
        'mode': mode,
        'local': {'reachable': l_ok, 'models': list(l_models)},
        'cloud': {'reachable': c_ok, 'models': list(c_models), 'enabled': cloud_enabled()},
    }


# --------------------------------------------------------------------------
# Client chooser
# --------------------------------------------------------------------------
def client():
    """Default backend: local when reachable, otherwise Ollama Cloud."""
    if local_reachable():
        return local_client()
    return cloud_client()


def client_for_model(model):
    """Client able to serve `model` - local when installed there, else cloud."""
    if model:
        _, local_models = _probe('local')
        if model in local_models:
            return local_client()
        _, cloud_models = _probe('cloud')
        if model in cloud_models:
            return cloud_client()
    return client()


def resolve_model(model):
    """Model name actually used for generation: `model` when available,
    otherwise the cloud default, otherwise None."""
    if model and model_available(model):
        return model
    if DEFAULT_CLOUD_MODEL and (cloud_reachable() or model_available(DEFAULT_CLOUD_MODEL)):
        logger.info("[OLLAMA] '%s' unavailable - using cloud default '%s'", model, DEFAULT_CLOUD_MODEL)
        return DEFAULT_CLOUD_MODEL
    return None


def scan_client(pm):
    """Client + model for specialist vision scans.

    Prefers the configured model; falls back to the cloud vision model so
    scans keep working when only the cloud is reachable (e.g. a pose model
    that is local-only). Returns (None, None) when nothing can serve.
    """
    if not pm:
        return None, None
    _, local_models = _probe('local')
    _, cloud_models = _probe('cloud')
    for cand in (pm, CLOUD_POSE_MODEL):
        if not cand:
            continue
        if cand in local_models:
            return local_client(), cand
        if cand in cloud_models:
            return cloud_client(), cand
    return None, None


def compress_image_b64(path, size=1280, quality=90):
    with Image.open(path) as img:
        img.thumbnail((size, size), Image.Resampling.BILINEAR)
        buffer = io.BytesIO()
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        img.save(buffer, format="JPEG", quality=quality)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')


def hex_codes(t):
    return set(re.findall(r'#[0-9A-Fa-f]{6}', t))
