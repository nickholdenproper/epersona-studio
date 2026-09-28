"""Persistent settings layer for the Studio singleton.

Mixin keeps `self` working exactly as the original Studio methods did. The
frontend already debounces rapid slider updates before POSTing them, so writes
go straight to disk - an earlier time-based throttle here silently dropped any
change made within its window, because the "dirty" flag it set was never read.
"""
import json
import os
import re

from . import log
from .config import (GPU_OPTIONS, HAIRSTYLES, PROMPT_TEMPLATE_DEFAULT,
                     PROMPT_TEMPLATES, SETTINGS_PATH, SKIN_TONES)
from .ollama import set_cloud_key

logger = log.get_logger(__name__)


class SettingsMixin:

    def load_settings(self):
        if not os.path.exists(SETTINGS_PATH):
            self.save_settings()
            return
        try:
            with open(SETTINGS_PATH, 'r') as f:
                data = json.load(f)
            self.templates = data.get('templates', {})
            self.selected_model = data.get('selected_model', self.selected_model)
            self.num_ctx = max(int(data.get('num_ctx', self.num_ctx)), 8192)
            GPU_OPTIONS['num_ctx'] = self.num_ctx
            hc = data.get('hair_base_color', '')
            if re.match(r'^#[0-9A-Fa-f]{6}$', str(hc)):
                self.hair_base_color = str(hc).upper()
            if data.get('skin_tone') in SKIN_TONES:
                self.skin_tone = data['skin_tone']
            if data.get('hairstyle') in HAIRSTYLES:
                self.hairstyle = data['hairstyle']
            self.selected_pose_model = data.get('pose_model', '')
            if data.get('vlm_backend') in self.VLM_BACKENDS:
                self.vlm_backend = data['vlm_backend']
            key = str(data.get('cloud_api_key', self.cloud_api_key) or '').strip()
            if key:
                self.cloud_api_key = key
            set_cloud_key(self.cloud_api_key)
            self.user_notes = str(data.get('user_notes', '') or '')[:1200]
            self.opt_compact = bool(data.get('opt_compact', False))
            # --- Enhancement toggles (previously not persisted) ---
            self.opt_noise = bool(data.get('opt_noise', True))
            self.opt_dof = bool(data.get('opt_dof', True))
            self.opt_realism = bool(data.get('opt_realism', True))
            self.opt_hdr = bool(data.get('opt_hdr', False))
            self.opt_no_tattoos = bool(data.get('opt_no_tattoos', False))
            self.opt_naked = bool(data.get('opt_naked', False))
            self.opt_safe = bool(data.get('opt_safe', False))
            self.use_default_details = bool(data.get('use_default_details', True))
            # --- Prompt template ---
            if data.get('prompt_template') in PROMPT_TEMPLATES:
                self.prompt_template = data['prompt_template']
            # --- Body Studio sliders ---
            self.breast_size = max(0, min(100, int(data.get('breast_size', self.breast_size))))
            self.hip_size = max(0, min(100, int(data.get('hip_size', self.hip_size))))
            self.hair_length = max(0, min(100, int(data.get('hair_length', self.hair_length))))
            self.hair_brightness = max(0, min(100, int(data.get('hair_brightness', self.hair_brightness))))
        except Exception as e:
            logger.error("[SETTINGS] Failed to load: %s", e)

    def save_settings(self):
        try:
            with open(SETTINGS_PATH, 'w') as f:
                json.dump({
                    'templates': self.templates,
                    'selected_model': self.selected_model,
                    'num_ctx': self.num_ctx,
                    'vlm_backend': self.vlm_backend,
                    'hair_base_color': self.hair_base_color,
                    'skin_tone': self.skin_tone,
                    'hairstyle': self.hairstyle,
                    'pose_model': self.selected_pose_model,
                    'cloud_api_key': self.cloud_api_key,
                    'user_notes': self.user_notes,
                    'opt_compact': self.opt_compact,
                    # Enhancement toggles
                    'opt_noise': self.opt_noise,
                    'opt_dof': self.opt_dof,
                    'opt_realism': self.opt_realism,
                    'opt_hdr': self.opt_hdr,
                    'opt_no_tattoos': self.opt_no_tattoos,
                    'opt_naked': self.opt_naked,
                    'opt_safe': self.opt_safe,
                    'use_default_details': self.use_default_details,
                    # Prompt template
                    'prompt_template': self.prompt_template,
                    # Body Studio sliders
                    'breast_size': self.breast_size,
                    'hip_size': self.hip_size,
                    'hair_length': self.hair_length,
                    'hair_brightness': self.hair_brightness,
                }, f, indent=2)
        except Exception as e:
            logger.error("[SETTINGS] Failed to save: %s", e)

    def flush_settings(self):
        """Kept for callers that want an explicit save; writes are unconditional
        now, so this is simply an alias of save_settings()."""
        self.save_settings()

    def apply_updates(self, payload: dict):
        simple = {
            'selected_model': 'selected_model',
            'selected_pose_model': 'selected_pose_model',
            'hair_base_color': 'hair_base_color',
            'hairstyle': 'hairstyle',
            'skin_tone': 'skin_tone',
            'vlm_backend': 'vlm_backend',
        }
        for k, attr in simple.items():
            if k in payload and payload[k] is not None:
                v = payload[k]
                if k == 'selected_pose_model' and v == "(None)":
                    v = ''
                    self._vlm_pose_cache.clear()
                    self._vlm_clothing_cache.clear()
                    self._vlm_env_cache.clear()
                if k == 'hairstyle' and v not in HAIRSTYLES:
                    continue
                if k == 'skin_tone' and v not in SKIN_TONES:
                    continue
                if k == 'vlm_backend' and v not in self.VLM_BACKENDS:
                    continue
                if k == 'hair_base_color':
                    v = str(v).upper()
                    if not re.match(r'^#[0-9A-F]{6}$', v):
                        continue
                setattr(self, attr, v)
        # An empty value means "no change" - the browser field is cleared after
        # a successful save, so accepting "" would wipe the stored key. Clearing
        # is therefore an explicit, separate flag rather than a blank field.
        if payload.get('clear_cloud_key'):
            self.cloud_api_key = ''
            set_cloud_key('')
        elif 'cloud_api_key' in payload and payload['cloud_api_key']:
            self.cloud_api_key = str(payload['cloud_api_key']).strip()
            set_cloud_key(self.cloud_api_key)
        for k in ('breast_size', 'hip_size', 'hair_length', 'hair_brightness'):
            if k in payload:
                try:
                    setattr(self, k, max(0, min(100, int(payload[k]))))
                except (TypeError, ValueError):
                    pass
        if 'num_ctx' in payload:
            try:
                self.num_ctx = int(payload['num_ctx'])
                GPU_OPTIONS['num_ctx'] = self.num_ctx
            except (TypeError, ValueError):
                pass
        for k in ('opt_noise', 'opt_dof', 'opt_realism', 'opt_hdr',
                  'opt_no_tattoos', 'opt_naked', 'opt_safe', 'opt_compact',
                  'use_default_details'):
            if k in payload:
                setattr(self, k, bool(payload[k]))
        if 'prompt_template' in payload and payload['prompt_template'] in PROMPT_TEMPLATES:
            self.prompt_template = payload['prompt_template']
        if 'outfit_active' in payload:
            self.outfit_active = bool(payload['outfit_active'])
        if 'user_notes' in payload and payload['user_notes'] is not None:
            self.user_notes = str(payload['user_notes']).strip()[:1200]
        self.save_settings()