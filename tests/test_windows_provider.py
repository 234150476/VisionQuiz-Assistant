"""Tests for core.windows_provider — WindowsElementProvider with mocked UIA."""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock

from core.element_provider import OptionElement, InputTarget


class WindowsProviderConnectTests(unittest.TestCase):
    """Test connection lifecycle."""

    @patch("core.windows_provider.auto", None)
    def test_connect_fails_without_uiautomation(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider(target_title="Test")
        self.assertFalse(p.connect())

    def test_connect_fails_without_title(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider(target_title="")
        result = p.connect()
        self.assertFalse(result)

    @patch("core.windows_provider.auto")
    def test_connect_success(self, mock_auto):
        from core.windows_provider import WindowsElementProvider
        mock_window = MagicMock()
        mock_window.Exists.return_value = True
        mock_window.Name = "My Quiz App"
        mock_auto.WindowControl.return_value = mock_window

        p = WindowsElementProvider(target_title="Quiz")
        result = p.connect()

        self.assertTrue(result)
        self.assertTrue(p._connected)
        mock_auto.WindowControl.assert_called_once()

    @patch("core.windows_provider.auto")
    def test_connect_window_not_found(self, mock_auto):
        from core.windows_provider import WindowsElementProvider
        mock_window = MagicMock()
        mock_window.Exists.return_value = False
        mock_auto.WindowControl.return_value = mock_window

        p = WindowsElementProvider(target_title="Nonexistent")
        result = p.connect()
        self.assertFalse(result)

    def test_close_resets_state(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider(target_title="Test")
        p._window = MagicMock()
        p._connected = True
        p.close()
        self.assertIsNone(p._window)
        self.assertFalse(p._connected)

    def test_name_property(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider(target_title="My Quiz Application")
        self.assertIn("My Quiz Applic", p.name)

    def test_name_property_empty_title(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider(target_title="")
        self.assertIn("?", p.name)


class WindowsProviderGetQuestionElementsTests(unittest.TestCase):
    """Test element extraction with mocked UIA tree."""

    def _make_connected_provider(self, text_controls=None, radio_buttons=None,
                                  check_boxes=None, buttons=None, edit_controls=None):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider(target_title="Test")
        p._connected = True
        p._window = MagicMock()

        def mock_find_controls(control_type, max_depth=5):
            mapping = {
                "TextControl": text_controls or [],
                "RadioButtonControl": radio_buttons or [],
                "CheckBoxControl": check_boxes or [],
                "ButtonControl": buttons or [],
                "EditControl": edit_controls or [],
            }
            return mapping.get(control_type, [])

        p._find_controls = mock_find_controls
        return p

    def _make_uia_control(self, name, control_type_name="RadioButtonControl", is_selected=False):
        ctrl = MagicMock()
        ctrl.Name = name
        ctrl.ControlTypeName = control_type_name

        # SelectionItemPattern
        sip = MagicMock()
        sip.IsSelected = is_selected
        ctrl.GetSelectionItemPattern.return_value = sip

        # TogglePattern
        tp = MagicMock()
        tp.ToggleState = 1 if is_selected else 0
        ctrl.GetTogglePattern.return_value = tp

        return ctrl

    def test_extracts_question_from_longest_text(self):
        p = self._make_connected_provider(
            text_controls=[
                self._make_uia_control("短", "TextControl"),
                self._make_uia_control("这是一道很长的题目文本，应该被选为题干", "TextControl"),
                self._make_uia_control("中等长度文本块", "TextControl"),
            ],
            radio_buttons=[
                self._make_uia_control("A. 选项一", "RadioButtonControl"),
                self._make_uia_control("B. 选项二", "RadioButtonControl"),
            ],
        )
        result = p.get_question_elements()
        self.assertIsNotNone(result)
        self.assertIn("很长的题目", result.question_text)
        self.assertEqual(len(result.options), 2)
        self.assertEqual(result.question_type, "single")

    def test_returns_none_when_no_text(self):
        p = self._make_connected_provider(text_controls=[])
        # Window Name also empty
        p._window.Name = ""
        result = p.get_question_elements()
        self.assertIsNone(result)

    def test_extracts_checkboxes_as_multi(self):
        p = self._make_connected_provider(
            text_controls=[self._make_uia_control("多选题目文本", "TextControl")],
            check_boxes=[
                self._make_uia_control("选项A", "CheckBoxControl"),
                self._make_uia_control("选项B", "CheckBoxControl"),
                self._make_uia_control("选项C", "CheckBoxControl"),
            ],
        )
        result = p.get_question_elements()
        self.assertIsNotNone(result)
        self.assertEqual(result.question_type, "multi")
        self.assertEqual(len(result.options), 3)

    def test_extracts_edit_controls_as_fill(self):
        p = self._make_connected_provider(
            text_controls=[self._make_uia_control("请输入你的答案", "TextControl")],
            edit_controls=[MagicMock(Name="答案框")],
        )
        result = p.get_question_elements()
        self.assertIsNotNone(result)
        self.assertEqual(result.question_type, "fill")
        self.assertEqual(len(result.input_targets), 1)

    def test_returns_none_on_exception(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider(target_title="Test")
        p._connected = True
        p._window = MagicMock()
        p._ensure_connected = MagicMock(return_value=True)
        p._extract_question_text = MagicMock(side_effect=RuntimeError("boom"))
        result = p.get_question_elements()
        self.assertIsNone(result)


class WindowsProviderClickOptionTests(unittest.TestCase):
    """Test click_option cascade logic."""

    def test_selection_item_pattern_preferred(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        ctrl = MagicMock()
        sip = MagicMock()
        ctrl.GetSelectionItemPattern.return_value = sip

        opt = OptionElement(text="A", element_ref=ctrl, index=0)
        result = p.click_option(opt)
        self.assertTrue(result)
        sip.Select.assert_called_once()

    def test_toggle_pattern_fallback(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        ctrl = MagicMock()
        ctrl.GetSelectionItemPattern.side_effect = Exception("no pattern")
        tp = MagicMock()
        ctrl.GetTogglePattern.return_value = tp

        opt = OptionElement(text="B", element_ref=ctrl, index=0)
        result = p.click_option(opt)
        self.assertTrue(result)
        tp.Toggle.assert_called_once()

    def test_invoke_pattern_fallback(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        ctrl = MagicMock()
        ctrl.GetSelectionItemPattern.side_effect = Exception("no")
        ctrl.GetTogglePattern.side_effect = Exception("no")
        ip = MagicMock()
        ctrl.GetInvokePattern.return_value = ip

        opt = OptionElement(text="C", element_ref=ctrl, index=0)
        result = p.click_option(opt)
        self.assertTrue(result)
        ip.Invoke.assert_called_once()

    def test_direct_click_last_resort(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        ctrl = MagicMock()
        ctrl.GetSelectionItemPattern.side_effect = Exception("no")
        ctrl.GetTogglePattern.side_effect = Exception("no")
        ctrl.GetInvokePattern.side_effect = Exception("no")

        opt = OptionElement(text="D", element_ref=ctrl, index=0)
        result = p.click_option(opt)
        self.assertTrue(result)
        ctrl.Click.assert_called_once()

    def test_returns_false_when_no_ref(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        opt = OptionElement(text="X", element_ref=None)
        self.assertFalse(p.click_option(opt))


class WindowsProviderFillInputTests(unittest.TestCase):
    def test_value_pattern_preferred(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        ctrl = MagicMock()
        vp = MagicMock()
        ctrl.GetValuePattern.return_value = vp

        target = InputTarget(element_ref=ctrl)
        result = p.fill_input(target, "hello")
        self.assertTrue(result)
        vp.SetValue.assert_called_once_with("hello")

    def test_returns_false_when_no_ref(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        target = InputTarget(element_ref=None)
        self.assertFalse(p.fill_input(target, "text"))


class WindowsProviderIsOptionSelectedTests(unittest.TestCase):
    def test_uses_selection_pattern(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        ctrl = MagicMock()
        sip = MagicMock()
        sip.IsSelected = True
        ctrl.GetSelectionItemPattern.return_value = sip

        opt = OptionElement(text="A", element_ref=ctrl, selected=False)
        self.assertTrue(p.is_option_selected(opt))

    def test_uses_toggle_pattern_fallback(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        ctrl = MagicMock()
        ctrl.GetSelectionItemPattern.side_effect = Exception("no")
        tp = MagicMock()
        tp.ToggleState = 1
        ctrl.GetTogglePattern.return_value = tp

        opt = OptionElement(text="B", element_ref=ctrl, selected=False)
        self.assertTrue(p.is_option_selected(opt))

    def test_returns_false_when_element_ref_is_none(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        opt = OptionElement(text="C", element_ref=None, selected=True)
        # Code returns False immediately when control is None
        self.assertFalse(p.is_option_selected(opt))

    def test_returns_false_when_no_patterns_and_not_selected(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        ctrl = MagicMock()
        ctrl.GetSelectionItemPattern.side_effect = Exception("no")
        ctrl.GetTogglePattern.side_effect = Exception("no")

        opt = OptionElement(text="D", element_ref=ctrl, selected=False)
        self.assertFalse(p.is_option_selected(opt))


class WindowsProviderInferTypeTests(unittest.TestCase):
    def test_fill_when_inputs_no_options(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        self.assertEqual(p._infer_type([], [InputTarget()]), "fill")

    def test_multi_for_checkbox_controls(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        cb = MagicMock()
        cb.ControlTypeName = "CheckBoxControl"
        opts = [OptionElement(text="A", element_ref=cb)]
        self.assertEqual(p._infer_type(opts, []), "multi")

    def test_single_for_radio_controls(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        rb = MagicMock()
        rb.ControlTypeName = "RadioButtonControl"
        opts = [OptionElement(text="A", element_ref=rb)]
        self.assertEqual(p._infer_type(opts, []), "single")

    def test_judge_for_two_button_options(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        btn = MagicMock(spec=[])  # No ControlTypeName attribute
        opts = [
            OptionElement(text="正确", element_ref=btn),
            OptionElement(text="错误", element_ref=btn),
        ]
        self.assertEqual(p._infer_type(opts, []), "judge")


class WindowsProviderFindControlsTests(unittest.TestCase):
    def test_returns_empty_when_no_window(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        p._window = None
        self.assertEqual(p._find_controls("TextControl"), [])

    def test_walks_tree(self):
        from core.windows_provider import WindowsElementProvider
        p = WindowsElementProvider()
        child = MagicMock()
        child.ControlTypeName = "RadioButtonControl"
        child.GetChildren.return_value = []

        root = MagicMock()
        root.GetChildren.return_value = [child]
        p._window = root

        result = p._find_controls("RadioButtonControl", max_depth=3)
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], child)


if __name__ == "__main__":
    unittest.main()
