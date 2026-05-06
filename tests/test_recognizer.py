import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from core.ai_client import PromptAResult, PromptBResult
from core.recognizer import Recognizer
from core.screenshot import compute_question_hash


class RecognizerTests(unittest.TestCase):
    def test_recognize_falls_back_to_text_when_vision_fails(self):
        cache = MagicMock()
        cache.get_by_phash.return_value = None
        cache.get_by_question_hash.return_value = None
        matcher = None
        ai_client = MagicMock()
        ai_client.answer_with_image.side_effect = RuntimeError("vision failed")
        ai_client.answer_with_text.return_value = PromptBResult(answer="B", answer_source="ai", confidence=0.9)
        recognizer = Recognizer(cache=cache, matcher=matcher, ai_client=ai_client)

        with patch("core.recognizer.is_ocr_available", return_value=True), patch(
            "core.recognizer.ocr_image", return_value="question text"
        ):
            result = recognizer.recognize(Image.new("RGB", (10, 10)), phash_str="phash")

        self.assertIsNotNone(result)
        self.assertEqual(result.answer, "B")
        self.assertEqual(result.source, "ai")
        self.assertEqual(result.answer_source, "ai")
        ai_client.answer_with_text.assert_called_once_with("question text")
        cache.insert.assert_called_once_with(
            compute_question_hash("question text"),
            "phash",
            "B",
            "ai",
        )

    def test_recognize_continues_after_cache_error(self):
        cache = MagicMock()
        cache.get_by_phash.side_effect = RuntimeError("cache down")
        cache.get_by_question_hash.return_value = None
        ai_client = MagicMock()
        ai_client.answer_with_image.return_value = PromptAResult(
            question_type="single", question="C", recognition_source="vision", confidence=0.9
        )
        ai_client.answer_with_text.return_value = PromptBResult(
            answer="C", answer_source="ai", confidence=0.9
        )
        recognizer = Recognizer(cache=cache, matcher=None, ai_client=ai_client)

        with patch("core.recognizer.is_ocr_available", return_value=False):
            result = recognizer.recognize(Image.new("RGB", (10, 10)), phash_str="phash")

        self.assertIsNotNone(result)
        self.assertEqual(result.question_type, "single")
        self.assertEqual(result.answer, "C")
        self.assertEqual(result.source, "ai")

    def test_recognize_skips_cache_write_when_ai_answer_invalid(self):
        cache = MagicMock()
        cache.get_by_phash.return_value = None
        cache.get_by_question_hash.return_value = None
        ai_client = MagicMock()
        # Prompt A 返回空题目（模拟无效结果）
        ai_client.answer_with_image.return_value = PromptAResult(
            question_type="single", question="", recognition_source="vision", confidence=0.0
        )
        recognizer = Recognizer(cache=cache, matcher=None, ai_client=ai_client)

        with patch("core.recognizer.is_ocr_available", return_value=False):
            result = recognizer.recognize(Image.new("RGB", (10, 10)), phash_str="phash")

        # Prompt A 返回空 answer，不会写缓存
        if result is not None:
            cache.insert.assert_not_called()

    def test_verify_answer_clicked_returns_true_without_ai(self):
        recognizer = Recognizer(cache=MagicMock(), matcher=None, ai_client=None)

        self.assertTrue(recognizer.verify_answer_clicked(None, None, "A"))

    def test_locate_option_coord_swallows_ai_error(self):
        ai_client = MagicMock()
        ai_client.locate_option.side_effect = RuntimeError("boom")
        recognizer = Recognizer(cache=MagicMock(), matcher=None, ai_client=ai_client)

        self.assertIsNone(recognizer.locate_option_coord(Image.new("RGB", (10, 10)), "A"))

    def test_recognize_returns_none_when_both_prompts_fail(self):
        """Prompt A 失败 + Prompt B 返回空答案 → 应返回 None 而非空结果。"""
        cache = MagicMock()
        cache.get_by_phash.return_value = None
        cache.get_by_question_hash.return_value = None
        ai_client = MagicMock()
        ai_client.answer_with_image.side_effect = RuntimeError("vision failed")
        # Prompt B 返回空答案
        ai_client.answer_with_text.return_value = PromptBResult(
            answer="", answer_source="ai", confidence=0.0
        )
        recognizer = Recognizer(cache=cache, matcher=None, ai_client=ai_client)

        with patch("core.recognizer.is_ocr_available", return_value=True), patch(
            "core.recognizer.ocr_image", return_value="some ocr text"
        ):
            result = recognizer.recognize(Image.new("RGB", (10, 10)), phash_str="phash")

        self.assertIsNone(result)

    def test_recognize_returns_none_when_prompt_b_fails(self):
        """Prompt A 失败 + Prompt B 抛异常 → 应返回 None。"""
        cache = MagicMock()
        cache.get_by_phash.return_value = None
        ai_client = MagicMock()
        ai_client.answer_with_image.side_effect = RuntimeError("vision failed")
        ai_client.answer_with_text.side_effect = RuntimeError("text failed")
        recognizer = Recognizer(cache=cache, matcher=None, ai_client=ai_client)

        with patch("core.recognizer.is_ocr_available", return_value=True), patch(
            "core.recognizer.ocr_image", return_value="some ocr text"
        ):
            result = recognizer.recognize(Image.new("RGB", (10, 10)), phash_str="phash")

        self.assertIsNone(result)


class PreprocessOcrTextTests(unittest.TestCase):
    def test_preprocess_normal_text(self):
        """正常中文文本返回 quality='good'"""
        from core.recognizer import _preprocess_ocr_text
        text = "以下哪个是Python的内置数据类型？"
        cleaned, quality = _preprocess_ocr_text(text)
        self.assertEqual(quality, 'good')
        self.assertEqual(cleaned, text)

    def test_preprocess_noisy_text(self):
        """乱码文本返回 quality='poor'"""
        from core.recognizer import _preprocess_ocr_text
        text = "▓▒░█▓▒░█▓▒░█▓▒░█"
        cleaned, quality = _preprocess_ocr_text(text)
        self.assertEqual(quality, 'poor')

    def test_preprocess_repeated_chars(self):
        """连续重复字符被清洗"""
        from core.recognizer import _preprocess_ocr_text
        text = "你好好好好世界"
        cleaned, quality = _preprocess_ocr_text(text)
        self.assertIn('好好', cleaned)
        self.assertNotIn('好好好好', cleaned)

    def test_preprocess_empty(self):
        """空文本返回 poor"""
        from core.recognizer import _preprocess_ocr_text
        cleaned, quality = _preprocess_ocr_text("")
        self.assertEqual(quality, 'poor')

    def test_preprocess_whitespace_only(self):
        """纯空白文本返回 poor"""
        from core.recognizer import _preprocess_ocr_text
        cleaned, quality = _preprocess_ocr_text("   \n  ")
        self.assertEqual(quality, 'poor')

    def test_preprocess_short_noise_lines_filtered(self):
        """短噪声行被过滤"""
        from core.recognizer import _preprocess_ocr_text
        text = "AB\n123\n这是一道正常的题目"
        cleaned, quality = _preprocess_ocr_text(text)
        self.assertIn("这是一道正常的题目", cleaned)
        self.assertNotIn("AB", cleaned)


if __name__ == "__main__":
    unittest.main()
