'use strict';

const $ = (id) => document.getElementById(id);
const S = {
  imageLoaded: false,
  busy: false,
  polling: false,
  hairColor: '#FFFFFF',
  twitterImageLoaded: false,
};

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-json */ }
  if (!res.ok) {
    let msg = data && data.detail ? data.detail : res.statusText;
    if (Array.isArray(msg)) msg = msg.map(d => d.msg || '').join(', ');
    throw new Error(String(msg));
  }
  return data;
}
const jsonPost = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

function toast(msg, cls) {
  const t = document.createElement('div');
  t.className = 'toast' + (cls ? ' ' + cls : '');
  t.textContent = msg;
  $('toasts').appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

function setStatus(txt, busy) {
  $('job-step').textContent = txt;
  $('job-status').hidden = !busy;
  S.busy = busy;
  updateButtons();
}

function updateButtons() {
  $('btn-generate').disabled = !S.imageLoaded || S.busy;
  $('btn-finalize').disabled = S.busy || !$('prompt-box').value.trim();
  $('btn-tts').disabled = S.busy || !$('prompt-box').value.trim();
  $('btn-outfit-scan').disabled = S.busy || !outfitLoaded;

  // Prompt Injector buttons
  const hasInjectInput = !!($('inject-input') && $('inject-input').value.trim());
  const hasInjectOutput = !!($('inject-output') && $('inject-output').value.trim());
  if ($('btn-inject-run')) $('btn-inject-run').disabled = S.busy || !hasInjectInput;
  if ($('btn-inject-copy')) $('btn-inject-copy').disabled = !hasInjectOutput;
  if ($('btn-inject-save')) $('btn-inject-save').disabled = !hasInjectOutput;

  // Twitter Caption buttons
  const hasTwitterOutput = !!($('twitter-output') && $('twitter-output').value.trim());
  if ($('btn-twitter-gen')) $('btn-twitter-gen').disabled = S.busy || !S.twitterImageLoaded;
  if ($('btn-twitter-copy')) $('btn-twitter-copy').disabled = !hasTwitterOutput;
  if ($('btn-twitter-save')) $('btn-twitter-save').disabled = !hasTwitterOutput;
}

/* ---------- settings sync ---------- */
let pushTimer = null;
const pending = {};
function queueSetting(patch) {
  Object.assign(pending, patch);
  clearTimeout(pushTimer);
  pushTimer = setTimeout(async () => {
    const payload = Object.assign({}, pending);
    for (const k of Object.keys(pending)) delete pending[k];
    try { await jsonPost('/api/settings', payload); }
    catch (e) { toast('Settings: ' + e.message, 'err'); }
  }, 300);
}

/* ---------- avatar ---------- */
let avTimer = null;
function refreshAvatar() {
  const q = new URLSearchParams({
    b: $('sl-bust').value,
    h: $('sl-hips').value,
    l: $('sl-len').value,
    br: $('sl-bright').value,
    color: S.hairColor,
    _: Date.now(),
  });
  $('avatar-img').src = '/api/avatar?' + q;
}
function refreshAvatarSoon() {
  clearTimeout(avTimer);
  avTimer = setTimeout(refreshAvatar, 90);
}

/* ---------- palette ---------- */
function renderColors(colors) {
  const strip = $('color-strip');
  strip.innerHTML = '';
  strip.classList.toggle('empty', !(colors && colors.length));
  if (!colors || !colors.length) {
    strip.textContent = 'No image analyzed yet';
    return;
  }
  for (const hex of colors) {
    const d = document.createElement('div');
    d.className = 'swatch';
    d.style.background = hex;
    d.title = hex;
    d.onclick = () => copyText(hex.toUpperCase());
    strip.appendChild(d);
  }
}

/* ---------- hair presets ---------- */
function renderHairPresets(presets) {
  const wrap = $('hair-presets');
  wrap.innerHTML = '';
  for (const p of presets) {
    const el = document.createElement('div');
    el.className = 'preset';
    el.innerHTML = `<i style="background:${p.hex}"></i><span>${p.name}</span>`;
    el.dataset.hex = p.hex.toUpperCase();
    el.onclick = () => setHairColor(p.hex.toUpperCase());
    wrap.appendChild(el);
  }
  markPresetSel();
}
function markPresetSel() {
  document.querySelectorAll('.preset').forEach(p =>
    p.classList.toggle('sel', p.dataset.hex === S.hairColor.toUpperCase()));
}
function setHairColor(hex) {
  S.hairColor = hex.toUpperCase();
  $('hair-color').value = '#' + S.hairColor.slice(1).toLowerCase();
  $('hair-color-label').textContent = S.hairColor;
  markPresetSel();
  refreshAvatarSoon();
  queueSetting({ hair_base_color: S.hairColor });
}

/* ---------- uploads ---------- */
function wireDrop(dropEl, inputEl, handler) {
  dropEl.onclick = () => inputEl.click();
  inputEl.onchange = () => { handler(inputEl.files[0]); inputEl.value = ''; };
  dropEl.addEventListener('dragover', e => { e.preventDefault(); dropEl.classList.add('drag'); });
  dropEl.addEventListener('dragleave', () => dropEl.classList.remove('drag'));
  dropEl.addEventListener('drop', e => {
    e.preventDefault();
    dropEl.classList.remove('drag');
    if (e.dataTransfer.files.length) handler(e.dataTransfer.files[0]);
  });
}

let outfitLoaded = false;
let florencePollTimer = null;

async function handleSourceFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  setStatus('Reading image...', true);
  try {
    const r = await api('/api/upload', { method: 'POST', body: fd });
    $('src-thumb').src = r.thumb;
    $('src-thumb').hidden = false;
    $('dz-hint').style.display = 'none';
    renderColors(r.colors);
    const chip = $('pose-chip');
    chip.hidden = !r.pose;
    chip.querySelector('span').textContent = r.pose;
    chip.title = r.pose;
    S.imageLoaded = true;
    $('user-notes').value = '';
    toast('Image loaded', 'good');

    // Start polling for Florence-2 scan results
    const vlmSel = $('sel-vlm');
    if (vlmSel.value === 'Florence-2') {
      startFlorencePoll();
    }
  } catch (e) {
    toast('Upload failed: ' + e.message, 'err');
  }
  setStatus('Ready', false);
}

function startFlorencePoll() {
  if (florencePollTimer) clearInterval(florencePollTimer);
  let tries = 0;
  florencePollTimer = setInterval(async () => {
    tries++;
    try {
      const st = await api('/api/state');
      applyState(st);
      const status = (st.florence_scan || {}).status || '';
      if (status.includes('complete') || status.includes('failed') || tries > 60) {
        clearInterval(florencePollTimer);
        florencePollTimer = null;
        if (status.includes('complete')) toast('Florence-2 scan done', 'good');
      }
    } catch (e) { /* ignore */ }
  }, 2000);
}

async function handleOutfitFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await api('/api/outfit/upload', { method: 'POST', body: fd });
    $('outfit-thumb').src = r.thumb;
    $('outfit-thumb').hidden = false;
    $('outfit-hint').hidden = true;
    $('outfit-desc').textContent = '';
    outfitLoaded = true;
    updateButtons();
    toast('Outfit photo added — press Scan');
  } catch (e) {
    toast('Outfit upload failed: ' + e.message, 'err');
  }
}

async function handleTwitterFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  setStatus('Uploading image...', true);
  try {
    const r = await api('/api/twitter/upload', { method: 'POST', body: fd });
    $('twitter-thumb').src = r.thumb;
    $('twitter-thumb').hidden = false;
    $('twitter-dz-hint').style.display = 'none';
    S.twitterImageLoaded = true;
    updateButtons();
    toast('Image loaded for Twitter caption', 'good');
  } catch (e) {
    toast('Twitter upload failed: ' + e.message, 'err');
  }
  setStatus('Ready', false);
}

/* ---------- job polling ---------- */
async function pollJob(onDone) {
  if (S.polling) return;
  S.polling = true;
  try {
    for (;;) {
      const j = await api('/api/job');
      setStatus(j.running ? (j.step || 'Working...') : 'Ready', j.running);
      if (!j.running) {
        if (j.error) toast(j.error, 'err');
        else if (onDone) onDone(j.result, j.kind);
        return;
      }
      await sleep(500);
    }
  } catch (e) {
    toast('Job poll failed: ' + e.message, 'err');
    setStatus('Ready', false);
  } finally {
    S.polling = false;
  }
}

/* ---------- clipboard / save ---------- */
function fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); toast('Copied to clipboard', 'good'); }
  catch (_) { toast('Copy failed', 'err'); }
  ta.remove();
}
function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text)
      .then(() => toast('Copied to clipboard', 'good'))
      .catch(() => fallbackCopy(text));
  } else fallbackCopy(text);
}

/* ---------- templates ---------- */
function fillTemplateSelect(names) {
  const sel = $('sel-template');
  sel.innerHTML = '';
  if (!names.length) {
    const o = document.createElement('option');
    o.textContent = '(no templates saved)';
    o.value = '';
    sel.appendChild(o);
    return;
  }
  for (const n of names) {
    const o = document.createElement('option');
    o.value = n; o.textContent = n;
    sel.appendChild(o);
  }
}

/* ---------- prompt history ---------- */
function historyPreview(text, max) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  return t.length > max ? t.slice(0, max) + '…' : t;
}

async function loadHistory() {
  const box = $('history-list');
  let items;
  try {
    const r = await api('/api/history');
    items = r.items || [];
  } catch (e) {
    box.textContent = 'History unavailable: ' + e.message;
    return;
  }
  box.innerHTML = '';
  if (!items.length) {
    const p = document.createElement('p');
    p.className = 'hint';
    p.textContent = 'Generated prompts appear here across sessions.';
    box.appendChild(p);
    return;
  }
  for (const it of items) {
    const card = document.createElement('div');
    card.className = 'hist-item';

    const head = document.createElement('div');
    head.className = 'hist-head';
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = it.kind || 'gen';
    const meta = document.createElement('span');
    meta.textContent = (it.ts || '') + (it.template ? ' · ' + it.template : '');
    head.appendChild(tag);
    head.appendChild(meta);
    card.appendChild(head);

    const body = document.createElement('div');
    body.className = 'hist-body';
    body.textContent = historyPreview(it.prompt, 260);
    body.title = it.prompt || '';
    card.appendChild(body);

    const row = document.createElement('div');
    row.className = 'row';
    const load = document.createElement('button');
    load.className = 'btn small';
    load.textContent = 'Load';
    load.onclick = () => {
      $('prompt-box').value = it.prompt || '';
      $('prompt-box').scrollTop = 0;
      updateButtons();
      toast('Prompt loaded');
    };
    const copy = document.createElement('button');
    copy.className = 'btn small ghost';
    copy.textContent = 'Copy';
    copy.onclick = () => { if (it.prompt) copyText(it.prompt); };
    row.appendChild(load);
    row.appendChild(copy);
    card.appendChild(row);

    box.appendChild(card);
  }
}

async function reloadState() {
  const st = await api('/api/state');
  applyState(st);
}

/* ---------- state application ---------- */
function fillSelect(sel, items, current) {
  sel.innerHTML = '';
  for (const it of items) {
    const o = document.createElement('option');
    o.value = it; o.textContent = it;
    sel.appendChild(o);
  }
  if (current !== undefined && items.includes(current)) sel.value = current;
}

function applyState(st) {
  fillSelect($('sel-model'), st.models.length ? st.models : [st.selected_model], st.selected_model);
  fillSelect($('sel-pose'), st.pose_values, st.pose_model);
  $('num-ctx').value = st.num_ctx;

  // VLM backend selector
  const vlmSel = $('sel-vlm');
  vlmSel.value = st.vlm_backend || 'Ollama';
  vlmSel.title = st.florence_available
    ? 'Florence-2: local model (loaded on demand)'
    : 'Florence-2: transformers not installed';

  const bk = st.backend || {};
  const online = st.models.length > 0;
  $('conn-dot').classList.toggle('ok', online);
  const src = bk.mode === 'cloud' ? 'Ollama Cloud' : (bk.mode === 'local' ? 'Ollama local' : 'Ollama');
  $('conn-dot').title = online
    ? src + ' connected (' + st.models.length + ' models)'
    : 'Ollama unreachable';
  $('conn-label').textContent = online ? src + ' connected' : 'Offline';

  // /api/state only reports whether a key exists. The value itself is fetched
  // separately when the Settings panel opens, so it stays off the polling path.
  renderKeyState(st.has_cloud_key);

  $('conn-detail').innerHTML = '';
  const rows = [
    ['Status', online ? 'Connected' : 'Unreachable'],
    ['Backend', src],
    ['Models available', String(st.models.length)],
    ['Main model', st.selected_model],
    ['VLM engine', (st.vlm_backend || 'Ollama') + (st.florence_available ? '' : ' (Florence-2 unavailable)')],
    ['Cloud key', st.has_cloud_key ? 'Set' : 'Not set'],
  ];
  for (const [k, v] of rows) {
    const kEl = document.createElement('div');
    kEl.className = 'k'; kEl.textContent = k;
    const vEl = document.createElement('div');
    vEl.className = 'v'; vEl.textContent = v;
    $('conn-detail').append(kEl, vEl);
  }

  $('sl-bust').value = st.sliders.breast_size;   $('val-bust').textContent = st.sliders.breast_size;
  $('sl-hips').value = st.sliders.hip_size;      $('val-hips').textContent = st.sliders.hip_size;
  $('sl-len').value = st.sliders.hair_length;    $('val-len').textContent = st.sliders.hair_length;
  $('sl-bright').value = st.sliders.hair_brightness; $('val-bright').textContent = st.sliders.hair_brightness;

  renderHairPresets(st.hair_presets);
  setHairColor(st.hair_base_color);

  fillSelect($('sel-hairstyle'), st.hairstyles, st.hairstyle);
  fillSelect($('sel-skin'), st.skin_tones, st.skin_tone);

  for (const k of ['opt_noise', 'opt_dof', 'opt_realism', 'opt_hdr',
                   'opt_no_tattoos', 'opt_naked', 'opt_safe', 'opt_compact',
                   'use_default_details']) {
    $(k).checked = !!st.opts[k];
  }

  document.querySelectorAll('#fmt-seg button').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === st.template_mode));

  fillTemplateSelect(st.templates);
  $('user-notes').value = st.user_notes || '';

  if (st.image.loaded && st.image.thumb) {
    $('src-thumb').src = st.image.thumb;
    $('src-thumb').hidden = false;
    $('dz-hint').style.display = 'none';
    S.imageLoaded = true;
    renderColors(st.image.colors);
    const chip = $('pose-chip');
    chip.hidden = !st.image.pose;
    chip.querySelector('span').textContent = st.image.pose;
  }

  // Florence-2 scan status
  const floDiv = $('florence-scan');
  const floStatus = $('florence-status');
  const floResult = $('florence-result');
  const scan = st.florence_scan || {};
  const statusText = scan.status || '';
  if (statusText) {
    floDiv.hidden = false;
    floStatus.textContent = statusText;
    if (scan.result) {
      const r = scan.result;
      let txt = '';
      if (r.pose) txt += 'Pose: ' + (typeof r.pose === 'object' ? JSON.stringify(r.pose, null, 2) : r.pose) + '\n';
      if (r.clothing) txt += 'Clothing: ' + (typeof r.clothing === 'object' ? JSON.stringify(r.clothing, null, 2) : r.clothing) + '\n';
      if (r.environment) txt += 'Environment: ' + (typeof r.environment === 'object' ? JSON.stringify(r.environment, null, 2) : r.environment) + '\n';
      if (r.elapsed) txt += 'Time: ' + r.elapsed + 's';
      floResult.textContent = txt.trim();
      floResult.style.display = 'block';
    } else if (statusText.includes('failed')) {
      floResult.style.display = 'none';
    } else {
      // Scan still in progress — show spinner
      floResult.textContent = '...scanning';
      floResult.style.display = 'block';
    }
  } else {
    floDiv.hidden = true;
  }

  outfitLoaded = !!st.outfit.loaded;
  if (outfitLoaded) {
    $('outfit-hint').textContent = 'Outfit photo loaded';
    $('outfit-desc').textContent = st.outfit.has_description ? 'Outfit description ready.' : 'Not scanned yet.';
  } else {
    $('outfit-hint').textContent = '+ Add outfit photo';
    $('outfit-desc').textContent = '';
  }
  $('outfit-thumb').hidden = !outfitLoaded;
  $('outfit-active').checked = !!st.outfit.active;
  $('btn-outfit-clear').disabled = !outfitLoaded;

  updateButtons();
  refreshAvatar();
}

/* ---------- event wiring ---------- */
/* ---------- settings overlay ---------- */
let keyFetched = false;

// Key status is rendered from whichever source knows it, rather than only
// /api/state: that endpoint probes Ollama with multi-second timeouts, so waiting
// on it left the badge stale for seconds after a save or remove.
function renderKeyState(hasKey) {
  const keyField = $('cloud-key');
  keyField.placeholder = hasKey
    ? 'Key saved - type a new one to replace'
    : 'ollama.com API key (used when local is down)';
  keyField.title = hasKey ? 'A cloud API key is saved on this machine' : 'No cloud API key set';
  const keyBadge = $('key-status');
  keyBadge.textContent = hasKey ? 'Key saved on this machine' : 'No key set';
  keyBadge.classList.toggle('ok', !!hasKey);
  $('btn-key-clear').disabled = !hasKey;
}

// The key is only pulled over the wire when the panel is actually opened, and
// never while the field has focus, so a background state refresh can't wipe
// out a key that is mid-typing.
async function loadKeyIntoField(force) {
  const f = $('cloud-key');
  if (!force && (keyFetched || document.activeElement === f)) return;
  let data;
  try {
    data = await api('/api/settings/cloud-key');
  } catch (e) {
    return;
  }
  keyFetched = true;
  renderKeyState(data && data.has_key);
  if (document.activeElement === f) return;
  f.value = data && data.key ? data.key : '';
  f.type = 'password';
}

const SUPPORTS_INERT = typeof HTMLElement !== 'undefined' && 'inert' in HTMLElement.prototype;

function dialogFocusables() {
  return Array.prototype.filter.call(
    document.querySelectorAll('#settings-panel button, #settings-panel input, #settings-panel select, #settings-panel textarea'),
    (el) => !el.disabled && el.offsetParent !== null
  );
}

function trapTab(e) {
  const items = dialogFocusables();
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

function setBackgroundInert(on) {
  // Chromium (pywebview) supports inert, which also removes the background from
  // the tab order. Older engines fall back to the explicit trap in trapTab.
  for (const el of [$('topbar'), $('grid')]) {
    if (!el) continue;
    if (on && SUPPORTS_INERT) el.setAttribute('inert', '');
    else el.removeAttribute('inert');
  }
}

function openSettings() {
  $('settings-overlay').hidden = false;
  setBackgroundInert(true);
  $('btn-settings-close').focus();
  loadKeyIntoField(false);
}
function closeSettings() {
  $('settings-overlay').hidden = true;
  setBackgroundInert(false);
  $('cloud-key').value = '';
  keyFetched = false;
  $('btn-settings').focus();
}
function wireSettings() {
  $('btn-settings').onclick = openSettings;
  $('btn-settings-close').onclick = closeSettings;
  $('settings-overlay').addEventListener('mousedown', (e) => {
    if (e.target === $('settings-overlay')) closeSettings();
  });
  document.addEventListener('keydown', (e) => {
    if ($('settings-overlay').hidden) return;
    if (e.key === 'Escape') { e.preventDefault(); closeSettings(); }
    else if (e.key === 'Tab' && !SUPPORTS_INERT) trapTab(e);
  });
}

function wire() {
  wireSettings();
  wireDrop($('dropzone'), $('file-input'), handleSourceFile);
  wireDrop($('outfit-drop'), $('outfit-input'), handleOutfitFile);
  wireDrop($('twitter-dropzone'), $('twitter-file-input'), handleTwitterFile);

  $('sel-model').onchange = () => queueSetting({ selected_model: $('sel-model').value });
  $('sel-vlm').onchange = () => queueSetting({ vlm_backend: $('sel-vlm').value });
  $('sel-pose').onchange = () => queueSetting({ selected_pose_model: $('sel-pose').value });
  $('num-ctx').onchange = () => queueSetting({ num_ctx: parseInt($('num-ctx').value, 10) || 2048 });

  $('cloud-key').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); $('btn-key-save').click(); }
  });

  $('btn-key-save').onclick = async () => {
    const key = $('cloud-key').value.trim();
    if (!key) { toast('Enter a key first', 'err'); return; }
    queueSetting({ cloud_api_key: key });
    renderKeyState(true);
    toast('Key saved');
    // The panel keeps showing the stored key, so the field is left in place
    // and re-read from the backend once the write lands.
    setTimeout(() => { keyFetched = false; loadKeyIntoField(true); reloadState(); }, 600);
  };

  $('btn-key-clear').onclick = async () => {
    queueSetting({ clear_cloud_key: true });
    $('cloud-key').value = '';
    keyFetched = false;
    renderKeyState(false);
    toast('Key removed');
    setTimeout(() => { loadKeyIntoField(true); reloadState(); }, 600);
  };

  $('btn-key-reveal').onclick = () => {
    const f = $('cloud-key');
    f.type = f.type === 'password' ? 'text' : 'password';
  };

  const sliderBind = (id, valId, key) => {
    $(id).addEventListener('input', () => {
      $(valId).textContent = $(id).value;
      refreshAvatarSoon();
    });
    $(id).addEventListener('change', () => queueSetting({ [key]: parseInt($(id).value, 10) }));
  };
  sliderBind('sl-bust', 'val-bust', 'breast_size');
  sliderBind('sl-hips', 'val-hips', 'hip_size');
  sliderBind('sl-len', 'val-len', 'hair_length');
  sliderBind('sl-bright', 'val-bright', 'hair_brightness');

  $('hair-color').addEventListener('input', () => setHairColor($('hair-color').value));

  $('sel-hairstyle').onchange = () => queueSetting({ hairstyle: $('sel-hairstyle').value });
  $('sel-skin').onchange = () => queueSetting({ skin_tone: $('sel-skin').value });

  $('user-notes').addEventListener('input', () =>
    queueSetting({ user_notes: $('user-notes').value }));

  for (const k of ['opt_noise', 'opt_dof', 'opt_realism', 'opt_hdr',
                   'opt_no_tattoos', 'opt_naked', 'opt_safe', 'opt_compact',
                   'use_default_details']) {
    $(k).addEventListener('change', () => queueSetting({ [k]: $(k).checked }));
  }

  document.querySelectorAll('#fmt-seg button').forEach(b => b.onclick = () => {
    document.querySelectorAll('#fmt-seg button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    queueSetting({ prompt_template: b.dataset.mode });
  });

  $('outfit-active').addEventListener('change', () =>
    queueSetting({ outfit_active: $('outfit-active').checked }));

  $('btn-generate').onclick = async () => {
    try {
      await jsonPost('/api/generate');
      setStatus('Starting generation...', true);
      pollJob(res => {
        if (res && res.prompt) {
          $('prompt-box').value = res.prompt;
          toast('Prompt generated', 'good');
        }
        updateButtons();
      });
    } catch (e) {
      toast(e.message, 'err');
      setStatus('Ready', false);
    }
  };

  $('btn-copy').onclick = () => {
    const t = $('prompt-box').value.trim();
    if (t) copyText(t); else toast('Nothing to copy', 'err');
  };

  $('btn-save').onclick = () => {
    const t = $('prompt-box').value.trim();
    if (!t) { toast('Nothing to save', 'err'); return; }
    const blob = new Blob([t], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'epersona_prompt.txt';
    a.click();
    URL.revokeObjectURL(a.href);
  };

  $('btn-finalize').onclick = async () => {
    const text = $('prompt-box').value.trim();
    if (!text) return;
    try {
      await jsonPost('/api/finalize', { text });
      setStatus('Finalizing...', true);
      pollJob(res => {
        if (res && res.prompt) {
          $('prompt-box').value = res.prompt;
          toast('Prompt finalized', 'good');
        }
        updateButtons();
      });
    } catch (e) { toast(e.message, 'err'); setStatus('Ready', false); }
  };

  $('btn-tts').onclick = async () => {
    const text = $('prompt-box').value.trim();
    if (!text) return;
    try {
      const r = await jsonPost('/api/tts', { text });
      $('prompt-box').value = r.result;
      $('tts-note').hidden = false;
      toast('TTS conversion applied', 'good');
      updateButtons();
    } catch (e) { toast(e.message, 'err'); }
  };

  $('btn-outfit-scan').onclick = async () => {
    try {
      await jsonPost('/api/outfit/scan');
      setStatus('Scanning outfit...', true);
      pollJob(res => {
        if (res && res.description) {
          $('outfit-desc').textContent = res.description;
          $('outfit-desc').title = res.description;
          $('outfit-active').checked = true;
          queueSetting({ outfit_active: true });
          toast('Outfit scanned & applied', 'good');
        }
        updateButtons();
      });
    } catch (e) { toast(e.message, 'err'); }
  };

  $('btn-outfit-clear').onclick = async () => {
    try {
      await jsonPost('/api/outfit/clear');
      outfitLoaded = false;
      $('outfit-thumb').hidden = true;
      $('outfit-thumb').removeAttribute('src');
      $('outfit-hint').hidden = false;
      $('outfit-hint').textContent = '+ Add outfit photo';
      $('outfit-desc').textContent = '';
      $('outfit-active').checked = false;
      updateButtons();
      toast('Outfit cleared');
    } catch (e) { toast(e.message, 'err'); }
  };

  $('btn-tmpl-save').onclick = async () => {
    const name = $('tmpl-name').value.trim();
    if (!name) { toast('Enter a template name first', 'err'); return; }
    try {
      const r = await jsonPost('/api/templates/save', { name });
      fillTemplateSelect(r.templates);
      $('sel-template').value = name;
      $('tmpl-name').value = '';
      toast(`Template "${name}" saved`, 'good');
    } catch (e) { toast(e.message, 'err'); }
  };

  $('btn-tmpl-load').onclick = async () => {
    const name = $('sel-template').value;
    if (!name) return;
    try {
      await jsonPost('/api/templates/load/' + encodeURIComponent(name));
      await reloadState();
      toast(`Template "${name}" applied`, 'good');
    } catch (e) { toast(e.message, 'err'); }
  };

  $('btn-tmpl-del').onclick = async () => {
    const name = $('sel-template').value;
    if (!name) return;
    try {
      const r = await api('/api/templates/delete/' + encodeURIComponent(name), { method: 'DELETE' });
      fillTemplateSelect(r.templates);
      toast(`Template "${name}" deleted`);
    } catch (e) { toast(e.message, 'err'); }
  };

  $('prompt-box').addEventListener('input', updateButtons);

  // --- Prompt History wiring ---
  $('btn-history-refresh').onclick = loadHistory;
  $('btn-history-clear').onclick = async () => {
    if (!confirm('Delete all prompt history?')) return;
    try {
      await api('/api/history', { method: 'DELETE' });
      loadHistory();
      toast('History cleared');
    } catch (e) { toast(e.message, 'err'); }
  };

  // --- Prompt Injector wiring ---
  $('inject-input').addEventListener('input', updateButtons);

  $('btn-inject-clear').onclick = () => {
    $('inject-input').value = '';
    $('inject-output').value = '';
    updateButtons();
  };

  $('btn-inject-run').onclick = async () => {
    const text = $('inject-input').value.trim();
    if (!text) return;
    setStatus('Injecting settings...', true);
    try {
      const res = await jsonPost('/api/inject', { text });
      if (res && res.result) {
        $('inject-output').value = res.result;
        toast('Settings injected successfully', 'good');
      }
    } catch (e) {
      toast('Injection failed: ' + e.message, 'err');
    } finally {
      setStatus('Ready', false);
    }
  };

  $('btn-inject-copy').onclick = () => {
    const t = $('inject-output').value.trim();
    if (t) copyText(t); else toast('Nothing to copy', 'err');
  };

  $('btn-inject-save').onclick = () => {
    const t = $('inject-output').value.trim();
    if (!t) { toast('Nothing to save', 'err'); return; }
    const blob = new Blob([t], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'injected_prompt.txt';
    a.click();
    URL.revokeObjectURL(a.href);
  };

  // --- Twitter Caption wiring ---
  document.querySelectorAll('#twitter-vibe-seg button').forEach(b => b.onclick = () => {
    document.querySelectorAll('#twitter-vibe-seg button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
  });
  document.querySelectorAll('#twitter-len-seg button').forEach(b => b.onclick = () => {
    document.querySelectorAll('#twitter-len-seg button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
  });

  $('btn-twitter-gen').onclick = async () => {
    if (!S.twitterImageLoaded) return;
    const vibe = document.querySelector('#twitter-vibe-seg button.active')?.dataset.val || 'casual';
    const length = document.querySelector('#twitter-len-seg button.active')?.dataset.val || 'medium';
    setStatus('Generating caption...', true);
    try {
      const res = await jsonPost('/api/twitter-caption', { vibe, length });
      if (res && res.caption) {
        $('twitter-output').value = res.caption;
        toast('Caption generated', 'good');
      }
    } catch (e) {
      toast('Caption generation failed: ' + e.message, 'err');
    } finally {
      setStatus('Ready', false);
    }
  };

  $('btn-twitter-clear').onclick = () => {
    $('twitter-thumb').hidden = true;
    $('twitter-thumb').removeAttribute('src');
    $('twitter-dz-hint').style.display = '';
    $('twitter-output').value = '';
    S.twitterImageLoaded = false;
    updateButtons();
  };

  $('btn-twitter-copy').onclick = () => {
    const t = $('twitter-output').value.trim();
    if (t) copyText(t); else toast('Nothing to copy', 'err');
  };

  $('btn-twitter-save').onclick = () => {
    const t = $('twitter-output').value.trim();
    if (!t) { toast('Nothing to save', 'err'); return; }
    const blob = new Blob([t], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'twitter_caption.txt';
    a.click();
    URL.revokeObjectURL(a.href);
  };
}

/* ---------- tab switcher ---------- */
function switchRightTab(mode) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.id === `tab-btn-${mode}`);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.id === `pane-${mode}`);
  });
  updateButtons();
}

/* ---------- boot ---------- */
(async function init() {
  wire();
  setStatus('Connecting...', true);
  try {
    await reloadState();
    loadHistory();
    setStatus('Ready', false);
  } catch (e) {
    toast('Failed to reach backend: ' + e.message, 'err');
    setStatus('Backend unreachable', false);
  }
})();

