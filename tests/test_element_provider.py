"""Tests for core.element_provider — dataclasses and ABC contract."""

import unittest
from core.element_provider import (
    OptionElement, InputTarget, QuestionElement, ElementProvider,
)


class OptionElementTests(unittest.TestCase):
    def test_defaults(self):
        opt = OptionElement(text="A. Hello")
        self.assertEqual(opt.text, "A. Hello")
        self.assertIsNone(opt.element_ref)
        self.assertFalse(opt.selected)
        self.assertEqual(opt.index, 0)

    def test_custom_values(self):
        ref = object()
        opt = OptionElement(text="B", element_ref=ref, selected=True, index=3)
        self.assertEqual(opt.text, "B")
        self.assertIs(opt.element_ref, ref)
        self.assertTrue(opt.selected)
        self.assertEqual(opt.index, 3)


class InputTargetTests(unittest.TestCase):
    def test_defaults(self):
        t = InputTarget()
        self.assertEqual(t.placeholder, "")
        self.assertIsNone(t.element_ref)

    def test_with_values(self):
        ref = {"nodeId": 42}
        t = InputTarget(placeholder="请输入答案", element_ref=ref)
        self.assertEqual(t.placeholder, "请输入答案")
        self.assertEqual(t.element_ref, ref)


class QuestionElementTests(unittest.TestCase):
    def test_defaults(self):
        q = QuestionElement(question_text="1+1=?")
        self.assertEqual(q.question_text, "1+1=?")
        self.assertEqual(q.question_type, "")
        self.assertEqual(q.options, [])
        self.assertEqual(q.input_targets, [])
        self.assertEqual(q.raw_hash, "")

    def test_full_construction(self):
        opts = [OptionElement(text="A. 2"), OptionElement(text="B. 3")]
        inputs = [InputTarget(placeholder="答案")]
        q = QuestionElement(
            question_text="1+1=?",
            question_type="single",
            options=opts,
            input_targets=inputs,
            raw_hash="abc123",
        )
        self.assertEqual(len(q.options), 2)
        self.assertEqual(len(q.input_targets), 1)
        self.assertEqual(q.question_type, "single")
        self.assertEqual(q.raw_hash, "abc123")

    def test_options_list_is_independent(self):
        """Each QuestionElement gets its own options list (field default_factory)."""
        q1 = QuestionElement(question_text="A")
        q2 = QuestionElement(question_text="B")
        q1.options.append(OptionElement(text="X"))
        self.assertEqual(len(q1.options), 1)
        self.assertEqual(len(q2.options), 0)


class ElementProviderABCTests(unittest.TestCase):
    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            ElementProvider()

    def test_concrete_subclass_can_instantiate(self):
        class DummyProvider(ElementProvider):
            def connect(self, **kwargs): return True
            def get_question_elements(self): return None
            def click_option(self, option): return True
            def fill_input(self, target, text): return True
            def is_option_selected(self, option): return False
            def close(self): pass

        p = DummyProvider()
        self.assertTrue(p.connect())
        self.assertIsNone(p.get_question_elements())
        self.assertEqual(p.name, "DummyProvider")

    def test_name_property_uses_class_name(self):
        class MyProvider(ElementProvider):
            def connect(self, **kwargs): return True
            def get_question_elements(self): return None
            def click_option(self, option): return False
            def fill_input(self, target, text): return False
            def is_option_selected(self, option): return False
            def close(self): pass

        p = MyProvider()
        self.assertEqual(p.name, "MyProvider")


if __name__ == "__main__":
    unittest.main()
