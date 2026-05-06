import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from core.ai_client import AIClient, PromptAResult, PromptBResult, PromptCResult, ProviderProfile


def make_chat_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class AIClientTests(unittest.TestCase):
    def make_client(self):
        openai_client = MagicMock()
        with patch("core.ai_client.OpenAI", return_value=openai_client):
            client = AIClient("key", "https://example.com/v1", "gpt-test", timeout=5)
        return client, openai_client

    def test_answer_with_text_retries_retryable_error(self):
        client, openai_client = self.make_client()
        openai_client.chat.completions.create.side_effect = [
            ConnectionError("network"),
            make_chat_response(" A "),
        ]

        with patch.object(client, "_sleep_with_close_check") as sleep_mock:
            result = client.answer_with_text("question")

        self.assertIsInstance(result, PromptBResult)
        self.assertEqual(result.answer, "A")
        self.assertEqual(openai_client.chat.completions.create.call_count, 2)
        sleep_mock.assert_called_once()

    def test_answer_with_text_returns_json_result(self):
        client, openai_client = self.make_client()
        openai_client.chat.completions.create.return_value = make_chat_response(
            '{"answer": "B", "answer_source": "ai", "confidence": 0.95}'
        )

        result = client.answer_with_text("question")

        self.assertIsInstance(result, PromptBResult)
        self.assertEqual(result.answer, "B")
        self.assertEqual(result.answer_source, "ai")
        self.assertAlmostEqual(result.confidence, 0.95)

    def test_answer_with_image_returns_prompt_a_result(self):
        client, openai_client = self.make_client()
        openai_client.chat.completions.create.return_value = make_chat_response(
            '{"question_type": "single", "question": "test?", '
            '"options": [{"text": "A选项", "x": 100, "y": 200}], '
            '"input_targets": [], "word_limit": null, '
            '"recognition_source": "vision", "confidence": 0.9}'
        )

        result = client.answer_with_image("test?", Image.new("RGB", (100, 100)))

        self.assertIsInstance(result, PromptAResult)
        self.assertEqual(result.question_type, "single")
        self.assertEqual(result.question, "test?")
        self.assertEqual(len(result.options), 1)
        self.assertEqual(result.options[0].text, "A选项")
        self.assertEqual(result.recognition_source, "vision")

    def test_verify_click_returns_prompt_c_result(self):
        client, openai_client = self.make_client()
        openai_client.chat.completions.create.return_value = make_chat_response(
            '{"confirmed": true, "confidence": 0.9}'
        )

        result = client.verify_click(
            Image.new("RGB", (100, 100)),
            Image.new("RGB", (100, 100)),
            "A",
        )

        self.assertIsInstance(result, PromptCResult)
        self.assertTrue(result.confirmed)
        self.assertAlmostEqual(result.confidence, 0.9)

    def test_answer_with_text_rejects_empty_answer(self):
        client, openai_client = self.make_client()
        openai_client.chat.completions.create.return_value = make_chat_response("   ")

        with self.assertRaises((ValueError, RuntimeError)):
            client.answer_with_text("question")

    def test_close_is_idempotent_and_blocks_public_calls(self):
        client, openai_client = self.make_client()

        client.close()
        client.close()

        openai_client.close.assert_called_once()
        with self.assertRaises(RuntimeError):
            client.answer_with_text("question")

    def test_locate_option_returns_validated_coords(self):
        client, openai_client = self.make_client()
        openai_client.chat.completions.create.return_value = make_chat_response("10,20")

        coords = client.locate_option(Image.new("RGB", (100, 100)), "A")

        self.assertEqual(coords, (10, 20))

    def test_provider_profile_extra_body_passed_to_sdk(self):
        """Extra body from profile reaches OpenAI SDK create() call."""
        profile = ProviderProfile(
            base_url="https://api.xiaomimimo.com/v1",
            model="mimo-v2.5",
            extra_body={"thinking": {"type": "disabled"}},
        )
        openai_client_2 = MagicMock()
        with patch("core.ai_client.OpenAI", return_value=openai_client_2):
            client2 = AIClient("key", "https://api.xiaomimimo.com/v1", "mimo-v2.5", timeout=5, profile=profile)
        openai_client_2.chat.completions.create.return_value = make_chat_response(
            '{"answer": "B", "answer_source": "ai", "confidence": 0.9}'
        )
        client2.answer_with_text("question")
        call_args = openai_client_2.chat.completions.create.call_args
        # call_args[1] is kwargs dict (positional args tuple is call_args[0])
        kwargs = call_args[1] if len(call_args) > 1 and isinstance(call_args[1], dict) else call_args.kwargs
        self.assertIn("thinking", kwargs)
        self.assertEqual(kwargs["thinking"], {"type": "disabled"})

    def test_backward_compat_no_profile(self):
        """AIClient without profile works exactly as before."""
        client, openai_client = self.make_client()
        openai_client.chat.completions.create.return_value = make_chat_response(
            '{"answer": "A", "answer_source": "ai", "confidence": 0.9}'
        )
        result = client.answer_with_text("question")
        self.assertIsInstance(result, PromptBResult)
        self.assertEqual(result.answer, "A")

    def test_mimo_profile_assembly(self):
        """MiMo profile with thinking disabled sends correct params."""
        profile = ProviderProfile(
            base_url="https://api.xiaomimimo.com/v1",
            model="mimo-v2.5",
            supports_vision=True,
            extra_body={"thinking": {"type": "disabled"}},
        )
        openai_client = MagicMock()
        with patch("core.ai_client.OpenAI", return_value=openai_client):
            client = AIClient("key", "https://api.xiaomimimo.com/v1", "mimo-v2.5", timeout=5, profile=profile)
        self.assertEqual(client.model, "mimo-v2.5")
        self.assertTrue(client._profile.supports_vision)
        self.assertEqual(client._profile.extra_body, {"thinking": {"type": "disabled"}})

    def test_image_transport_inline_base64(self):
        """Default inline_base64 transport works."""
        client, openai_client = self.make_client()
        openai_client.chat.completions.create.return_value = make_chat_response(
            '{"question_type": "single", "question": "test?", '
            '"options": [], "input_targets": [], "word_limit": null, '
            '"recognition_source": "vision", "confidence": 0.9}'
        )
        result = client.answer_with_image("test?", Image.new("RGB", (100, 100)))
        self.assertIsInstance(result, PromptAResult)

    def test_image_transport_public_url_raises(self):
        """public_url transport raises NotImplementedError."""
        profile = ProviderProfile(image_transport="public_url")
        openai_client = MagicMock()
        with patch("core.ai_client.OpenAI", return_value=openai_client):
            client = AIClient("key", "https://example.com/v1", "test", timeout=5, profile=profile)
        with self.assertRaises(NotImplementedError):
            client.answer_with_image("test?", Image.new("RGB", (100, 100)))


class ThinkingBlockTests(unittest.TestCase):
    """MiMo thinking 块剥离测试。"""

    def test_strip_thinking_removes_think_tags(self):
        raw = '<think>分析题目...</think>\n{"answer": "B", "answer_source": "ai", "confidence": 0.9}'
        result = AIClient._strip_thinking(raw)
        self.assertNotIn("<think>", result)
        self.assertIn('"answer"', result)

    def test_strip_thinking_removes_reasoning_tags(self):
        raw = '<reasoning>分析中...</reasoning>\n{"confirmed": true, "confidence": 0.8}'
        result = AIClient._strip_thinking(raw)
        self.assertNotIn("<reasoning>", result)
        self.assertIn('"confirmed"', result)

    def test_extract_json_with_thinking_prefix(self):
        raw = '<think>分析题目结构和选项分布</think>\n```json\n{"question_type": "single", "question": "1+1=?", "options": [{"text": "2", "x": 100, "y": 200}], "input_targets": [], "word_limit": null, "recognition_source": "vision", "confidence": 0.95}\n```'
        result = AIClient._extract_json(raw)
        self.assertEqual(result["question_type"], "single")
        self.assertEqual(result["confidence"], 0.95)

    def test_extract_json_with_thinking_and_bare_json(self):
        raw = '<think>推理过程...\n分析完毕</think>\n{"answer": "C", "answer_source": "ai", "confidence": 0.85}'
        result = AIClient._extract_json(raw)
        self.assertEqual(result["answer"], "C")

    def test_extract_json_no_thinking_unchanged(self):
        raw = '{"answer": "A", "answer_source": "ai", "confidence": 0.9}'
        result = AIClient._extract_json(raw)
        self.assertEqual(result["answer"], "A")


if __name__ == "__main__":
    unittest.main()
