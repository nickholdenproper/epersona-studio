"""Florence-2 local VLM backend (HuggingFace Transformers).

Lazy-loaded singleton so the app starts fast and only pays the ~500MB model
cost when the Florence-2 backend is actually used.
"""
from . import log

logger = log.get_logger(__name__)

FLORENCE_AVAILABLE = False
Florence2Model = None
Florence2Processor = None


def _load_florence_deps():
    global FLORENCE_AVAILABLE, Florence2Model, Florence2Processor
    if FLORENCE_AVAILABLE:
        return
    try:
        from transformers import AutoModelForCausalLM, AutoProcessor
        Florence2Model = AutoModelForCausalLM
        Florence2Processor = AutoProcessor
        FLORENCE_AVAILABLE = True
        logger.info("[FLORENCE] transformers imported successfully")
    except ImportError:
        logger.info("[FLORENCE] transformers not installed — Florence-2 backend unavailable")


def florence_available():
    """Whether Florence-2 can be used, read at call time.

    FLORENCE_AVAILABLE starts False and only flips once transformers has been
    imported by _load_florence_deps(). A `from .florence import
    FLORENCE_AVAILABLE` in another module binds the pre-load value forever, so
    callers must go through this instead.
    """
    return FLORENCE_AVAILABLE


class Florence2Backend:
    """Lazy-loaded Florence-2 local VLM backend via HuggingFace Transformers."""

    def __init__(self):
        self._model = None
        self._processor = None
        self._device = None
        self._model_id = "microsoft/Florence-2-base"
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return True
        _load_florence_deps()
        if not FLORENCE_AVAILABLE:
            raise Exception("transformers package not installed. Run: pip install transformers torch")
        try:
            import torch
            from transformers import AutoConfig
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if self._device == "cuda" else torch.float32
            logger.info("[FLORENCE] Loading %s on %s...", self._model_id, self._device)

            self._processor = Florence2Processor.from_pretrained(self._model_id, trust_remote_code=True)

            config = AutoConfig.from_pretrained(self._model_id, trust_remote_code=True)
            if hasattr(config, 'language_config'):
                if not hasattr(config.language_config, 'forced_bos_token_id'):
                    config.language_config.forced_bos_token_id = None
            if hasattr(config, 'vision_config'):
                if not hasattr(config.vision_config, 'image_size'):
                    config.vision_config.image_size = 768

            self._model = Florence2Model.from_pretrained(
                self._model_id, config=config, dtype=dtype, trust_remote_code=True,
                ignore_mismatched_sizes=True,
            ).to(self._device)
            self._model.eval()

            # Patch any sub-configs missing forced_bos_token_id
            for attr_name in ('language_model', 'vision_model', 'image_projection'):
                sub = getattr(self._model, attr_name, None)
                if sub is not None and hasattr(sub, 'config'):
                    if not hasattr(sub.config, 'forced_bos_token_id'):
                        sub.config.forced_bos_token_id = None

            self._loaded = True
            logger.info("[FLORENCE] Model loaded on %s", self._device)
            return True
        except Exception as e:
            logger.error("[FLORENCE] Failed to load model: %s", e)
            self._loaded = False
            raise Exception(f"Florence-2 model load failed: {e}")

    def run_task(self, image_pil, task_prompt, text_prompt=""):
        self._ensure_loaded()
        import torch
        from PIL import Image as PILImage
        if image_pil.mode != "RGB":
            image_pil = image_pil.convert("RGB")
        full_prompt = task_prompt
        if text_prompt:
            full_prompt = task_prompt + text_prompt
        inputs = self._processor(text=full_prompt, images=image_pil, return_tensors="pt")
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch.no_grad():
            generated_ids = self._model.generate(
                **inputs, max_new_tokens=512, num_beams=3, early_stopping=True,
                forced_bos_token_id=None, use_cache=False,
            )
        generated_text = self._processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed = self._processor.post_process_generation(
            generated_text, task=task_prompt, image_size=(image_pil.width, image_pil.height)
        )
        return parsed

    def caption(self, image_pil, mode="detailed"):
        task = "<CAPTION>" if mode == "short" else "<DETAILED_CAPTION>" if mode == "detailed" else "<MORE_DETAILED_CAPTION>"
        result = self.run_task(image_pil, task)
        return result.get(task, result.get("caption", str(result)))


FLORENCE = Florence2Backend()