"""Auto-patch Florence-2 cached files for transformers 4.57.x compatibility."""
import glob
import os
import sys

CACHE_BASE = os.path.expanduser("~/.cache/huggingface/modules/transformers_modules/microsoft")


def find_cached(pattern):
    return glob.glob(os.path.join(CACHE_BASE, "**", pattern), recursive=True)


def patch_configuration():
    for path in find_cached("configuration_florence2.py"):
        with open(path, "r") as f:
            content = f.read()
        old = "        if self.forced_bos_token_id is None and"
        new = (
            "        if not hasattr(self, 'forced_bos_token_id'):\n"
            "            self.forced_bos_token_id = None\n"
            "        if self.forced_bos_token_id is None and"
        )
        if old in content and "hasattr(self, 'forced_bos_token_id')" not in content:
            content = content.replace(old, new)
            with open(path, "w") as f:
                f.write(content)
            print(f"  Patched: {os.path.basename(path)} (forced_bos_token_id)")


def patch_processing():
    for path in find_cached("processing_florence2.py"):
        with open(path, "r") as f:
            content = f.read()
        old = "                    tokenizer.additional_special_tokens + \\"
        new = "                    getattr(tokenizer, 'additional_special_tokens', []) + \\"
        if old in content:
            content = content.replace(old, new)
            with open(path, "w") as f:
                f.write(content)
            print(f"  Patched: {os.path.basename(path)} (additional_special_tokens)")


def patch_modeling():
    for path in find_cached("modeling_florence2.py"):
        with open(path, "r") as f:
            content = f.read()
        original = content
        changes = []

        # Add class attributes if missing
        if "_supports_sdpa = False" not in content:
            content = content.replace(
                '    _skip_keys_device_placement = "past_key_values"',
                '    _skip_keys_device_placement = "past_key_values"\n'
                '    _supports_sdpa = False\n'
                '    _supports_flash_attn_2 = False\n'
                '    _supports_cache_class = True',
            )
            changes.append("class attrs")

        # Remove conflicting @property definitions
        for prop_block in [
            (
                "\n    @property\n"
                "    def _supports_flash_attn_2(self):\n"
                '        """\n'
                "        Retrieve language_model's attribute to check whether the model supports\n"
                "        Flash Attention 2 or not.\n"
                '        """\n'
                "        return self.language_model._supports_flash_attn_2\n"
            ),
            (
                "\n    @property\n"
                "    def _supports_sdpa(self):\n"
                '        """\n'
                "        Retrieve language_model's attribute to check whether the model supports\n"
                "        SDPA or not.\n"
                '        """\n'
                "        return self.language_model._supports_sdpa\n"
            ),
        ]:
            if prop_block in content:
                content = content.replace(prop_block, "")
                changes.append(f"removed {prop_block.splitlines()[2].strip()}")

        # Fix past_key_values compatibility with transformers 4.57+
        old_pkv = "            past_length = past_key_values[0][0].shape[2]"
        new_pkv = (
            "            if hasattr(past_key_values, 'get_seq_length'):\n"
            "                past_length = past_key_values.get_seq_length()\n"
            "            elif past_key_values[0] is not None and past_key_values[0][0] is not None:\n"
            "                past_length = past_key_values[0][0].shape[2]\n"
            "            else:\n"
            "                past_length = 0"
        )
        if old_pkv in content and "get_seq_length" not in content:
            content = content.replace(old_pkv, new_pkv)
            changes.append("pkv compat")

        if content == original:
            print(f"  Already patched: {os.path.basename(path)}")
            continue
        with open(path, "w") as f:
            f.write(content)
        print(f"  Patched: {os.path.basename(path)} ({', '.join(changes) or 'no-op'})")


if __name__ == "__main__":
    print("[PATCH] Florence-2 cache compatibility patches")
    patch_configuration()
    patch_processing()
    patch_modeling()
    print("[PATCH] Done")
