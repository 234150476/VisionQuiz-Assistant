"""Tests for core.clicker.ElementClicker — element-mode dispatch and option matching."""

import unittest
from unittest.mock import MagicMock, patch, call

from core.element_provider import QuestionElement, OptionElement, InputTarget
from core.clicker import ElementClicker


def make_result(**kwargs):
    """Build a minimal RecognizeResult-like object."""
    r = MagicMock()
    r.question_type = kwargs.get("question_type", "single")
    r.answer = kwargs.get("answer", "A")
    r.options = kwargs.get("options", [])
    r.input_targets = kwargs.get("input_targets", [])
    return r


def make_question(opts=None, inputs=None, qtype="single", text="Q"):
    """Build a QuestionElement."""
    return QuestionElement(
        question_text=text,
        question_type=qtype,
        options=opts or [],
        input_targets=inputs or [],
        raw_hash="abc",
    )


class DispatchRoutingTests(unittest.TestCase):
    """Test that dispatch_answer routes to the correct handler."""

    def setUp(self):
        self.provider = MagicMock()
        self.clicker = ElementClicker(self.provider)

    @patch.object(ElementClicker, "_handle_single")
    def test_single_routes_to_handle_single(self, mock_h):
        mock_h.return_value = True
        result = make_result(question_type="single")
        self.clicker.dispatch_answer(result)
        mock_h.assert_called_once()

    @patch.object(ElementClicker, "_handle_multi")
    def test_multi_routes_to_handle_multi(self, mock_h):
        mock_h.return_value = True
        result = make_result(question_type="multi")
        self.clicker.dispatch_answer(result)
        mock_h.assert_called_once()

    @patch.object(ElementClicker, "_handle_judge")
    def test_judge_routes_to_handle_judge(self, mock_h):
        mock_h.return_value = True
        result = make_result(question_type="judge")
        self.clicker.dispatch_answer(result)
        mock_h.assert_called_once()

    @patch.object(ElementClicker, "_handle_input")
    def test_fill_routes_to_handle_input(self, mock_h):
        mock_h.return_value = True
        result = make_result(question_type="fill")
        self.clicker.dispatch_answer(result)
        mock_h.assert_called_once()

    @patch.object(ElementClicker, "_handle_input")
    def test_essay_routes_to_handle_input(self, mock_h):
        mock_h.return_value = True
        result = make_result(question_type="essay")
        self.clicker.dispatch_answer(result)
        mock_h.assert_called_once()


class FindOptionTests(unittest.TestCase):
    """Test _find_option matching logic."""

    def setUp(self):
        self.provider = MagicMock()
        self.clicker = ElementClicker(self.provider)
        self.qe = make_question(opts=[
            OptionElement(text="A. Apple", index=0),
            OptionElement(text="B. Banana", index=1),
            OptionElement(text="C. Cherry", index=2),
        ])

    def test_exact_match(self):
        opt = self.clicker._find_option("A. Apple", [], self.qe)
        self.assertIsNotNone(opt)
        self.assertEqual(opt.text, "A. Apple")

    def test_contains_match(self):
        opt = self.clicker._find_option("Banana", [], self.qe)
        self.assertIsNotNone(opt)
        self.assertIn("Banana", opt.text)

    def test_letter_index_match(self):
        opt = self.clicker._find_option("C", [], self.qe)
        self.assertIsNotNone(opt)
        self.assertEqual(opt.index, 2)

    def test_letter_index_case_insensitive(self):
        opt = self.clicker._find_option("b", [], self.qe)
        self.assertIsNotNone(opt)
        self.assertEqual(opt.index, 1)

    def test_no_match_returns_none(self):
        opt = self.clicker._find_option("Z. Zebra", [], self.qe)
        self.assertIsNone(opt)

    def test_no_question_elem_returns_none(self):
        opt = self.clicker._find_option("A", [], None)
        self.assertIsNone(opt)

    def test_empty_options_returns_none(self):
        qe = make_question(opts=[])
        opt = self.clicker._find_option("A", [], qe)
        self.assertIsNone(opt)


class HandleSingleTests(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.click_option.return_value = True
        self.provider.is_option_selected.return_value = True
        self.clicker = ElementClicker(self.provider)
        self.opt_a = OptionElement(text="A. Yes", index=0)
        self.qe = make_question(opts=[self.opt_a])

    def test_success(self):
        result = make_result(answer="A. Yes")
        with patch("core.clicker.time"):
            ok = self.clicker._handle_single(result, self.qe)
        self.assertTrue(ok)
        self.provider.click_option.assert_called_once()

    def test_fails_when_option_not_found(self):
        result = make_result(answer="Z. Missing")
        ok = self.clicker._handle_single(result, self.qe)
        self.assertFalse(ok)

    def test_returns_click_result_when_verify_fails(self):
        self.provider.is_option_selected.return_value = False
        self.provider.click_option.return_value = True
        result = make_result(answer="A. Yes")
        with patch("core.clicker.time"):
            ok = self.clicker._handle_single(result, self.qe)
        # Returns True from click even if not selected
        self.assertTrue(ok)


class HandleMultiTests(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.click_option.return_value = True
        self.provider.is_option_selected.return_value = True
        self.clicker = ElementClicker(self.provider)
        self.qe = make_question(opts=[
            OptionElement(text="A. One", index=0),
            OptionElement(text="B. Two", index=1),
            OptionElement(text="C. Three", index=2),
        ])

    @patch("core.clicker.parse_answers")
    @patch("core.clicker.time")
    def test_clicks_all_answers(self, mock_time, mock_parse):
        mock_parse.return_value = ["A. One", "C. Three"]
        result = make_result(answer="A,C")
        ok = self.clicker._handle_multi(result, self.qe)
        self.assertTrue(ok)
        self.assertEqual(self.provider.click_option.call_count, 2)

    @patch("core.clicker.parse_answers")
    @patch("core.clicker.time")
    def test_fails_when_one_option_missing(self, mock_time, mock_parse):
        mock_parse.return_value = ["A. One", "Z. Missing"]
        result = make_result(answer="A,Z")
        ok = self.clicker._handle_multi(result, self.qe)
        self.assertFalse(ok)


class HandleJudgeTests(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.click_option.return_value = True
        self.provider.is_option_selected.return_value = True
        self.clicker = ElementClicker(self.provider)
        self.qe = make_question(opts=[
            OptionElement(text="正确", index=0),
            OptionElement(text="错误", index=1),
        ], qtype="judge")

    @patch("core.clicker.time")
    def test_positive_answer(self, mock_time):
        result = make_result(answer="正确", question_type="judge")
        ok = self.clicker._handle_judge(result, self.qe)
        self.assertTrue(ok)

    @patch("core.clicker.time")
    def test_negative_answer(self, mock_time):
        result = make_result(answer="错误", question_type="judge")
        ok = self.clicker._handle_judge(result, self.qe)
        self.assertTrue(ok)

    def test_no_options_returns_false(self):
        qe = make_question(opts=[], qtype="judge")
        result = make_result(answer="正确")
        self.assertFalse(self.clicker._handle_judge(result, qe))


class HandleInputTests(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.fill_input.return_value = True
        self.clicker = ElementClicker(self.provider)

    def test_fills_first_input_target(self):
        target = InputTarget(placeholder="答案", element_ref=MagicMock())
        qe = make_question(inputs=[target], qtype="fill")
        result = make_result(answer="hello", question_type="fill")
        ok = self.clicker._handle_input(result, qe)
        self.assertTrue(ok)
        self.provider.fill_input.assert_called_once_with(target, "hello")

    def test_fails_when_no_input_targets(self):
        qe = make_question(inputs=[], qtype="fill")
        result = make_result(answer="hello")
        self.assertFalse(self.clicker._handle_input(result, qe))

    def test_fails_when_no_question_elem(self):
        result = make_result(answer="hello")
        self.assertFalse(self.clicker._handle_input(result, None))


if __name__ == "__main__":
    unittest.main()
