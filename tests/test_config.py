import os
import json
import tempfile
import unittest
from unittest.mock import patch

from core.config import MODEL_PRESETS, get_preset_catalog, get_active_preset


class ModelPresetTests(unittest.TestCase):
    def test_model_presets_catalog(self):
        self.assertIn("mimo_v25", MODEL_PRESETS)
        self.assertTrue(MODEL_PRESETS["mimo_v25"]["supports_vision"])
        self.assertEqual(MODEL_PRESETS["mimo_v25"]["model"], "mimo-v2.5")
        self.assertEqual(MODEL_PRESETS["mimo_v25"]["base_url"], "https://api.xiaomimimo.com/v1")

    def test_selected_preset_overrides_config(self):
        """When selected_preset is set and base_url/model are empty, preset fills them."""
        cfg = {
            "selected_preset": "mimo_v25",
            "api_key": "test",
            "api_base_url": "",
            "model": "",
        }
        # Simulate preset resolution logic
        preset_key = cfg.get("selected_preset", "")
        if preset_key and preset_key in MODEL_PRESETS:
            preset = MODEL_PRESETS[preset_key]
            if not cfg.get("api_base_url"):
                cfg["api_base_url"] = preset["base_url"]
            if not cfg.get("model"):
                cfg["model"] = preset["model"]
        self.assertEqual(cfg["api_base_url"], "https://api.xiaomimimo.com/v1")
        self.assertEqual(cfg["model"], "mimo-v2.5")

    def test_empty_preset_keeps_manual_values(self):
        """When selected_preset is empty, manual values are preserved."""
        cfg = {
            "selected_preset": "",
            "api_key": "test",
            "api_base_url": "https://custom.api.com/v1",
            "model": "custom-model",
        }
        preset_key = cfg.get("selected_preset", "")
        if preset_key and preset_key in MODEL_PRESETS:
            preset = MODEL_PRESETS[preset_key]
            if not cfg.get("api_base_url"):
                cfg["api_base_url"] = preset["base_url"]
            if not cfg.get("model"):
                cfg["model"] = preset["model"]
        self.assertEqual(cfg["api_base_url"], "https://custom.api.com/v1")
        self.assertEqual(cfg["model"], "custom-model")

    def test_get_preset_catalog_returns_copy(self):
        catalog = get_preset_catalog()
        self.assertIn("mimo_v25", catalog)
        catalog["mimo_v25"]["model"] = "modified"
        # Original should be unchanged
        self.assertEqual(MODEL_PRESETS["mimo_v25"]["model"], "mimo-v2.5")

    def test_get_active_preset(self):
        cfg = {"selected_preset": "mimo_v25"}
        preset = get_active_preset(cfg)
        self.assertIsNotNone(preset)
        self.assertEqual(preset["model"], "mimo-v2.5")
        self.assertTrue(preset["supports_vision"])

    def test_get_active_preset_none_when_empty(self):
        cfg = {"selected_preset": ""}
        preset = get_active_preset(cfg)
        self.assertIsNone(preset)

    def test_preset_count_at_least_10(self):
        """模型预设数量不少于 10 个（覆盖主流视觉模型）。"""
        self.assertGreaterEqual(len(MODEL_PRESETS), 10)

    def test_all_presets_have_required_fields(self):
        """每个预设必须包含 display_name, base_url, model, supports_vision。"""
        required = {"display_name", "base_url", "model", "supports_vision"}
        for key, preset in MODEL_PRESETS.items():
            missing = required - set(preset.keys())
            self.assertFalse(missing, f"Preset '{key}' missing fields: {missing}")

    def test_vision_presets_include_major_providers(self):
        """视觉预设应覆盖 Claude, Gemini, Qwen, GLM, Step, Doubao 等主流厂商。"""
        catalog = get_preset_catalog()
        vision_names = [k for k, v in catalog.items() if v.get("supports_vision")]
        self.assertGreaterEqual(len(vision_names), 10)
        # 至少包含以下厂商的预设
        for prefix in ["claude", "gemini", "qwen", "glm", "step", "doubao"]:
            matches = [k for k in vision_names if k.startswith(prefix)]
            self.assertTrue(matches, f"Missing vision preset for provider: {prefix}")


if __name__ == "__main__":
    unittest.main()
