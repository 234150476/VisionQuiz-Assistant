"""Tests for core.clicker — AutoClicker dispatch and handler routing."""

import unittest
from unittest.mock import MagicMock, patch, call

from core.clicker import AutoClicker, parse_answers, ANSWER_SEPARATOR


def make_result(**kwargs):
    """Build a minimal RecognizeResult-like object for clicker tests."""
    r = MagicMock()
    r.question_type = kwargs.get("question_type", "single")
    r.answer = kwargs.get("answer", "A")
    r.options = kwargs.get("options", [])
    r.input_targets = kwargs.get("input_targets", [])
    r._img_w = kwargs.get("img_w", 1920)
    r._img_h = kwargs.get("img_h", 1080)
    return r


class ParseAnswersTests(unittest.TestCase):
    def test_single_answer(self):
        self.assertEqual(parse_answers("A"), ["A"])

    def test_multi_answer(self):
        result = parse_answers(f"A{ANSWER_SEPARATOR}C")
        self.assertEqual(result, ["A", "C"])

    def test_strips_whitespace(self):
        result = parse_answers(f"  A  {ANSWER_SEPARATOR}  B  ")
        self.assertEqual(result, ["A", "B"])

    def test_empty_parts_filtered(self):
        result = parse_answers(f"A{ANSWER_SEPARATOR}{ANSWER_SEPARATOR}B")
        self.assertEqual(result, ["A", "B"])


class DispatchRoutingTests(unittest.TestCase):
    """Test that dispatch_answer routes to correct handler per question_type."""

    def setUp(self):
        self.recognizer = MagicMock()
        self.clicker = AutoClicker(self.recognizer, 1920, 1080)

    @patch("core.clicker.AutoClicker._handle_single")
    def test_single_routes_to_handle_single(self, mock_handler):
        mock_handler.return_value = True
        result = make_result(question_type="single")
        self.clicker.dispatch_answer(result)
        mock_handler.assert_called_once_with(result)

    @patch("core.clicker.AutoClicker._handle_multi")
    def test_multi_routes_to_handle_multi(self, mock_handler):
        mock_handler.return_value = True
        result = make_result(question_type="multi")
        self.clicker.dispatch_answer(result)
        mock_handler.assert_called_once_with(result)

    @patch("core.clicker.AutoClicker._handle_judge")
    def test_judge_routes_to_handle_judge(self, mock_handler):
        mock_handler.return_value = True
        result = make_result(question_type="judge")
        self.clicker.dispatch_answer(result)
        mock_handler.assert_called_once_with(result)

    @patch("core.clicker.AutoClicker._handle_fill")
    def test_fill_routes_to_handle_fill(self, mock_handler):
        mock_handler.return_value = True
        result = make_result(question_type="fill")
        self.clicker.dispatch_answer(result)
        mock_handler.assert_called_once_with(result)

    @patch("core.clicker.AutoClicker._handle_essay")
    def test_essay_routes_to_handle_essay(self, mock_handler):
        mock_handler.return_value = True
        result = make_result(question_type="essay")
        self.clicker.dispatch_answer(result)
        mock_handler.assert_called_once_with(result)

    @patch("core.clicker.AutoClicker._handle_single")
    def test_unknown_type_defaults_to_single(self, mock_handler):
        mock_handler.return_value = True
        result = make_result(question_type="unknown_type")
        self.clicker.dispatch_answer(result)
        mock_handler.assert_called_once_with(result)

    @patch("core.clicker.AutoClicker._handle_single")
    def test_empty_type_defaults_to_single(self, mock_handler):
        mock_handler.return_value = True
        result = make_result(question_type="")
        self.clicker.dispatch_answer(result)
        mock_handler.assert_called_once_with(result)


class ResolveOptionCoordTests(unittest.TestCase):
    """Test _resolve_option_coord matching strategies."""

    def setUp(self):
        self.recognizer = MagicMock()
        self.clicker = AutoClicker(self.recognizer, 1920, 1080)
        self.clicker._current_img_w = 1920
        self.clicker._current_img_h = 1080

    def test_exact_match(self):
        options = [
            {"text": "选项A", "x": 100, "y": 200},
            {"text": "选项B", "x": 300, "y": 200},
        ]
        self.clicker._current_options = options
        coord = self.clicker._resolve_option_coord("选项A")
        self.assertEqual(coord, (100, 200))

    def test_contains_match(self):
        options = [
            {"text": "这是选项A的内容", "x": 100, "y": 200},
        ]
        self.clicker._current_options = options
        coord = self.clicker._resolve_option_coord("选项A")
        self.assertEqual(coord, (100, 200))

    def test_letter_index_match(self):
        options = [
            {"text": "First", "x": 100, "y": 200},
            {"text": "Second", "x": 300, "y": 200},
        ]
        self.clicker._current_options = options
        self.assertEqual(self.clicker._resolve_option_coord("A"), (100, 200))
        self.assertEqual(self.clicker._resolve_option_coord("B"), (300, 200))

    def test_no_match_returns_none(self):
        options = [{"text": "选项A", "x": 100, "y": 200}]
        self.clicker._current_options = options
        self.assertIsNone(self.clicker._resolve_option_coord("不存在"))

    def test_empty_options_returns_none(self):
        self.clicker._current_options = []
        self.assertIsNone(self.clicker._resolve_option_coord("A"))


class HandleSingleTests(unittest.TestCase):
    def setUp(self):
        self.recognizer = MagicMock()
        self.clicker = AutoClicker(self.recognizer, 1920, 1080)
        self.clicker._current_img_w = 1920
        self.clicker._current_img_h = 1080

    @patch("core.clicker.AutoClicker._verify_and_retry", return_value=True)
    def test_single_clicks_matched_option(self, mock_verify):
        result = make_result(
            question_type="single",
            answer="选项A",
            options=[{"text": "选项A", "x": 100, "y": 200}, {"text": "选项B", "x": 300, "y": 200}],
        )
        ok = self.clicker._handle_single(result)
        self.assertTrue(ok)
        mock_verify.assert_called_once_with(100, 200, "选项A")

    @patch("core.clicker.AutoClicker._verify_and_retry", return_value=True)
    def test_single_no_match_returns_false(self, mock_verify):
        result = make_result(
            question_type="single",
            answer="不存在",
            options=[{"text": "选项A", "x": 100, "y": 200}],
        )
        ok = self.clicker._handle_single(result)
        self.assertFalse(ok)
        mock_verify.assert_not_called()


class HandleJudgeTests(unittest.TestCase):
    def setUp(self):
        self.recognizer = MagicMock()
        self.clicker = AutoClicker(self.recognizer, 1920, 1080)
        self.clicker._current_img_w = 1920
        self.clicker._current_img_h = 1080

    @patch("core.clicker.AutoClicker._verify_and_retry", return_value=True)
    def test_positive_keyword_selects_first(self, mock_verify):
        result = make_result(
            question_type="judge",
            answer="正确",
            options=[{"text": "对", "x": 100, "y": 200}, {"text": "错", "x": 300, "y": 200}],
        )
        ok = self.clicker._handle_judge(result)
        self.assertTrue(ok)
        mock_verify.assert_called_once_with(100, 200, "正确")

    @patch("core.clicker.AutoClicker._verify_and_retry", return_value=True)
    def test_negative_keyword_selects_second(self, mock_verify):
        result = make_result(
            question_type="judge",
            answer="错误",
            options=[{"text": "对", "x": 100, "y": 200}, {"text": "错", "x": 300, "y": 200}],
        )
        ok = self.clicker._handle_judge(result)
        self.assertTrue(ok)
        mock_verify.assert_called_once_with(300, 200, "错误")

    @patch("core.clicker.AutoClicker._verify_and_retry", return_value=True)
    def test_empty_options_returns_false(self, mock_verify):
        result = make_result(question_type="judge", answer="正确", options=[])
        ok = self.clicker._handle_judge(result)
        self.assertFalse(ok)


class HandleFillEssayTests(unittest.TestCase):
    def setUp(self):
        self.recognizer = MagicMock()
        self.clicker = AutoClicker(self.recognizer, 1920, 1080)
        self.clicker._current_img_w = 1920
        self.clicker._current_img_h = 1080

    @patch("core.clicker.pyautogui")
    @patch("core.clicker.time")
    def test_fill_clicks_target_and_types(self, mock_time, mock_pyautogui):
        result = make_result(
            question_type="fill",
            answer="答案文本",
            input_targets=[{"placeholder": "输入答案", "x": 500, "y": 300}],
        )
        ok = self.clicker._handle_fill(result)
        self.assertTrue(ok)
        mock_pyautogui.click.assert_called_once_with(500, 300)
        mock_pyautogui.write.assert_called_once_with("答案文本", interval=0.05)

    @patch("core.clicker.pyautogui")
    @patch("core.clicker.time")
    def test_essay_clicks_target_and_types(self, mock_time, mock_pyautogui):
        result = make_result(
            question_type="essay",
            answer="长篇回答",
            input_targets=[{"placeholder": "请输入", "x": 600, "y": 400}],
        )
        ok = self.clicker._handle_essay(result)
        self.assertTrue(ok)
        mock_pyautogui.click.assert_called_once_with(600, 400)
        mock_pyautogui.write.assert_called_once_with("长篇回答", interval=0.05)

    def test_fill_no_targets_returns_false(self):
        result = make_result(question_type="fill", answer="答案", input_targets=[])
        ok = self.clicker._handle_fill(result)
        self.assertFalse(ok)

    def test_essay_no_targets_returns_false(self):
        result = make_result(question_type="essay", answer="答案", input_targets=[])
        ok = self.clicker._handle_essay(result)
        self.assertFalse(ok)


class HandleMultiTests(unittest.TestCase):
    def setUp(self):
        self.recognizer = MagicMock()
        self.clicker = AutoClicker(self.recognizer, 1920, 1080)
        self.clicker._current_img_w = 1920
        self.clicker._current_img_h = 1080

    @patch("core.clicker.AutoClicker._verify_and_retry", return_value=True)
    def test_multi_clicks_all_matched(self, mock_verify):
        sep = ANSWER_SEPARATOR
        result = make_result(
            question_type="multi",
            answer=f"A{sep}C",
            options=[
                {"text": "选项A", "x": 100, "y": 200},
                {"text": "选项B", "x": 200, "y": 200},
                {"text": "选项C", "x": 300, "y": 200},
            ],
        )
        ok = self.clicker._handle_multi(result)
        self.assertTrue(ok)
        self.assertEqual(mock_verify.call_count, 2)
