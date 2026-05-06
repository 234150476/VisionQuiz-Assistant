import os
import tempfile
import unittest
from unittest.mock import patch

import mss
from PIL import Image

from core import ocr, screenshot


class OCRTests(unittest.TestCase):
    def setUp(self):
        ocr._ocr_instance = None
        ocr._ocr_state = None

    def tearDown(self):
        ocr._ocr_instance = None
        ocr._ocr_state = None

    def test_detect_model_dir_requires_core_model_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            os.makedirs(os.path.join(tempdir, "det"))
            os.makedirs(os.path.join(tempdir, "rec"))

            with patch("core.ocr.get_models_dir", return_value=tempdir):
                self.assertIsNone(ocr._detect_model_dir())

            for folder in ("det", "rec"):
                open(os.path.join(tempdir, folder, "inference.pdiparams"), "wb").close()
                open(os.path.join(tempdir, folder, "inference.pdmodel"), "wb").close()

            with patch("core.ocr.get_models_dir", return_value=tempdir):
                self.assertEqual(ocr._detect_model_dir(), tempdir)

    def test_get_ocr_caches_init_failed_state(self):
        with patch("core.ocr._detect_model_dir", return_value="models"), patch(
            "core.ocr._build_ocr", side_effect=RuntimeError("init failed")
        ) as build_mock:
            self.assertIsNone(ocr.get_ocr())
            self.assertIsNone(ocr.get_ocr())

        self.assertEqual(ocr._ocr_state, ocr.OCRState.INIT_FAILED)
        build_mock.assert_called_once_with("models")


class ScreenshotTests(unittest.TestCase):
    def test_capture_screen_returns_none_on_screenshot_error(self):
        class BrokenMSS:
            monitors = [None, {"left": 0, "top": 0, "width": 1, "height": 1}]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def grab(self, monitor):
                raise mss.exception.ScreenShotError("boom")

        with patch("core.screenshot.mss.mss", return_value=BrokenMSS()):
            self.assertIsNone(screenshot.capture_screen())

    def test_compute_phash_returns_empty_string_on_failure(self):
        img = Image.new("RGB", (10, 10))

        with patch("core.screenshot.imagehash.phash", side_effect=RuntimeError("boom")):
            self.assertEqual(screenshot.compute_phash(img), "")

    def test_blackout_cursor_ignores_draw_failures(self):
        img = Image.new("RGB", (10, 10))

        with patch("core.screenshot.ImageDraw.Draw", side_effect=RuntimeError("boom")):
            result = screenshot.blackout_cursor(img)

        self.assertIs(result, img)


if __name__ == "__main__":
    unittest.main()
