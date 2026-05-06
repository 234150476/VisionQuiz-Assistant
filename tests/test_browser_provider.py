"""Tests for core.browser_provider — BrowserElementProvider with mocked CDP."""

import json
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

from core.element_provider import QuestionElement, OptionElement, InputTarget


class BrowserProviderConnectTests(unittest.TestCase):
    """Test connection lifecycle."""

    @patch("core.browser_provider.websocket", None)
    def test_connect_fails_without_websocket_lib(self):
        from core.browser_provider import BrowserElementProvider
        p = BrowserElementProvider()
        self.assertFalse(p.connect())

    @patch("core.browser_provider.websocket")
    @patch("urllib.request.urlopen")
    def test_connect_success(self, mock_urlopen, mock_ws):
        from core.browser_provider import BrowserElementProvider
        # Mock /json response with a page tab
        tab_data = json.dumps([{"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1"}])
        mock_resp = MagicMock()
        mock_resp.read.return_value = tab_data.encode()
        mock_urlopen.return_value = mock_resp

        mock_ws.create_connection.return_value = MagicMock()

        p = BrowserElementProvider(debug_port=9222)
        result = p.connect()

        self.assertTrue(result)
        mock_ws.create_connection.assert_called_once()

    @patch("core.browser_provider.websocket")
    @patch("urllib.request.urlopen")
    def test_connect_no_page_tab(self, mock_urlopen, mock_ws):
        from core.browser_provider import BrowserElementProvider
        tab_data = json.dumps([{"type": "other"}])
        mock_resp = MagicMock()
        mock_resp.read.return_value = tab_data.encode()
        mock_urlopen.return_value = mock_resp

        p = BrowserElementProvider()
        result = p.connect()
        self.assertFalse(result)

    @patch("core.browser_provider.websocket")
    @patch("urllib.request.urlopen", side_effect=ConnectionError("refused"))
    def test_connect_handles_exception(self, mock_urlopen, mock_ws):
        from core.browser_provider import BrowserElementProvider
        p = BrowserElementProvider()
        result = p.connect()
        self.assertFalse(result)
        self.assertFalse(p._connected)

    def test_close_sets_state(self):
        from core.browser_provider import BrowserElementProvider
        p = BrowserElementProvider()
        mock_ws = MagicMock()
        p._ws = mock_ws
        p._connected = True
        p.close()
        mock_ws.close.assert_called_once()
        self.assertIsNone(p._ws)
        self.assertFalse(p._connected)


class BrowserProviderEvaluateTests(unittest.TestCase):
    """Test CDP command and JS evaluation."""

    def _make_connected_provider(self):
        from core.browser_provider import BrowserElementProvider
        p = BrowserElementProvider()
        p._ws = MagicMock()
        p._connected = True
        return p

    def test_send_command_returns_result(self):
        p = self._make_connected_provider()
        p._ws.recv.return_value = json.dumps({"id": 1, "result": {"value": "ok"}})
        result = p._send_command("Runtime.evaluate", {"expression": "1+1"})
        self.assertEqual(result, {"value": "ok"})

    def test_send_command_timeout(self):
        import time
        p = self._make_connected_provider()
        p._timeout = 0.01

        # recv returns a non-matching id first, then blocks
        calls = [json.dumps({"id": 999, "result": {}})]

        def slow_recv():
            if calls:
                return calls.pop(0)
            time.sleep(1)

        p._ws.recv.side_effect = slow_recv
        result = p._send_command("Test.method")
        self.assertIsNone(result)

    def test_evaluate_js_returns_string(self):
        p = self._make_connected_provider()
        p._ws.recv.return_value = json.dumps({
            "id": 1,
            "result": {"result": {"type": "string", "value": "hello"}},
        })
        result = p._evaluate_js("document.title")
        self.assertEqual(result, "hello")

    def test_evaluate_js_returns_json_for_object(self):
        p = self._make_connected_provider()
        p._ws.recv.return_value = json.dumps({
            "id": 1,
            "result": {"result": {"type": "object", "value": {"a": 1}}},
        })
        result = p._evaluate_js("({a:1})")
        self.assertEqual(result, '{"a": 1}')

    def test_evaluate_js_returns_none_on_failure(self):
        p = self._make_connected_provider()
        p._ws.recv.return_value = json.dumps({"id": 1, "result": {"result": {}}})
        result = p._evaluate_js("undefined")
        self.assertIsNone(result)


class BrowserProviderGetQuestionElementsTests(unittest.TestCase):
    """Test get_question_elements with mocked JS evaluation."""

    def _make_provider_with_mock_eval(self, eval_responses: dict):
        """Create a provider where _evaluate_js returns values from a dict keyed by substring."""
        from core.browser_provider import BrowserElementProvider
        p = BrowserElementProvider()
        p._connected = True
        p._ws = MagicMock()

        def mock_eval(expr):
            for key, val in eval_responses.items():
                if key in expr:
                    return val
            return None

        p._evaluate_js = mock_eval
        return p

    def test_returns_question_element(self):
        from core.browser_provider import BrowserElementProvider
        p = BrowserElementProvider()
        p._connected = True
        p._ws = MagicMock()
        # Override extraction methods directly for cleaner test
        p._extract_question_text = lambda: "What is 1+1?"
        p._extract_options = lambda: [
            OptionElement(text="A. 1", element_ref=0, index=0),
            OptionElement(text="B. 2", element_ref=1, index=1),
        ]
        p._extract_input_targets = lambda: []
        p._infer_type = lambda opts, inputs: "single"

        qe = p.get_question_elements()
        self.assertIsNotNone(qe)
        self.assertEqual(qe.question_text, "What is 1+1?")
        self.assertIsInstance(qe.raw_hash, str)
        self.assertTrue(len(qe.raw_hash) > 0)
        self.assertEqual(len(qe.options), 2)

    def test_returns_none_when_no_question_text(self):
        p = self._make_provider_with_mock_eval({})
        p._evaluate_js = lambda expr: ""
        result = p.get_question_elements()
        self.assertIsNone(result)

    def test_returns_none_on_exception(self):
        from core.browser_provider import BrowserElementProvider
        p = BrowserElementProvider()
        p._connected = True
        p._ws = MagicMock()
        p._evaluate_js = MagicMock(side_effect=RuntimeError("boom"))
        result = p.get_question_elements()
        self.assertIsNone(result)


class BrowserProviderClickAndFillTests(unittest.TestCase):
    """Test click_option, fill_input, is_option_selected."""

    def _make_provider(self, eval_return="true"):
        from core.browser_provider import BrowserElementProvider
        p = BrowserElementProvider()
        p._connected = True
        p._ws = MagicMock()
        p._evaluate_js = MagicMock(return_value=eval_return)
        return p

    def test_click_option_success(self):
        p = self._make_provider("true")
        opt = OptionElement(text="A", element_ref=0, index=0)
        self.assertTrue(p.click_option(opt))

    def test_click_option_failure(self):
        p = self._make_provider("false")
        opt = OptionElement(text="A", element_ref=0, index=0)
        self.assertFalse(p.click_option(opt))

    def test_fill_input_success(self):
        p = self._make_provider("true")
        target = InputTarget(placeholder="答案", element_ref=0)
        self.assertTrue(p.fill_input(target, "hello"))

    def test_fill_input_failure(self):
        p = self._make_provider("false")
        target = InputTarget(placeholder="答案", element_ref=0)
        self.assertFalse(p.fill_input(target, "hello"))

    def test_is_option_selected_true(self):
        p = self._make_provider("true")
        opt = OptionElement(text="A", element_ref=0, index=0)
        self.assertTrue(p.is_option_selected(opt))

    def test_is_option_selected_false(self):
        p = self._make_provider("false")
        opt = OptionElement(text="A", element_ref=0, index=0)
        self.assertFalse(p.is_option_selected(opt))


class BrowserProviderInferTypeTests(unittest.TestCase):
    """Test _infer_type logic."""

    def _make_provider(self):
        from core.browser_provider import BrowserElementProvider
        p = BrowserElementProvider()
        p._connected = True
        return p

    def test_fill_when_inputs_no_options(self):
        p = self._make_provider()
        result = p._infer_type([], [InputTarget()])
        self.assertEqual(result, "fill")

    def test_judge_with_two_options_and_judge_words(self):
        p = self._make_provider()
        opts = [OptionElement(text="正确"), OptionElement(text="错误")]
        # Mock _evaluate_js for checkbox/radio check
        p._evaluate_js = MagicMock(return_value=json.dumps({"checkbox": 0, "radio": 0}))
        result = p._infer_type(opts, [])
        self.assertEqual(result, "judge")

    def test_multi_when_checkbox(self):
        p = self._make_provider()
        opts = [OptionElement(text="A"), OptionElement(text="B"), OptionElement(text="C")]
        p._evaluate_js = MagicMock(return_value=json.dumps({"checkbox": 3, "radio": 0}))
        result = p._infer_type(opts, [])
        self.assertEqual(result, "multi")

    def test_single_when_radio(self):
        p = self._make_provider()
        opts = [OptionElement(text="A"), OptionElement(text="B")]
        p._evaluate_js = MagicMock(return_value=json.dumps({"checkbox": 0, "radio": 2}))
        result = p._infer_type(opts, [])
        self.assertEqual(result, "single")

    def test_single_default(self):
        p = self._make_provider()
        opts = [OptionElement(text="X"), OptionElement(text="Y")]
        p._evaluate_js = MagicMock(return_value=None)
        result = p._infer_type(opts, [])
        self.assertEqual(result, "single")


class SelectorLoaderTests(unittest.TestCase):
    """Test _load_selectors helper."""

    def test_returns_defaults_when_no_config(self):
        from core.browser_provider import _load_selectors
        sel = _load_selectors("")
        self.assertIn("question_text", sel)
        self.assertIn("option", sel)

    def test_merges_user_config(self):
        import tempfile, os, json
        from core.browser_provider import _load_selectors
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"question_text": ".my-question"}, f)
            path = f.name
        try:
            sel = _load_selectors(path)
            self.assertEqual(sel["question_text"], ".my-question")
            self.assertIn("option", sel)  # default preserved
        finally:
            os.unlink(path)


class TextHashTests(unittest.TestCase):
    def test_deterministic(self):
        from core.browser_provider import _compute_text_hash
        h1 = _compute_text_hash("hello")
        h2 = _compute_text_hash("hello")
        self.assertEqual(h1, h2)

    def test_different_text_different_hash(self):
        from core.browser_provider import _compute_text_hash
        self.assertNotEqual(_compute_text_hash("a"), _compute_text_hash("b"))


if __name__ == "__main__":
    unittest.main()
