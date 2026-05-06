import unittest
from unittest.mock import MagicMock

from ui.hud import HUD


class HUDFormatDisplayTests(unittest.TestCase):
    """测试 HUD._format_display 的截断和组装逻辑（不依赖 tkinter 窗口）。"""

    def _make_hud(self, max_width=120):
        """构造一个不需要 tkinter 的 HUD 代理对象。"""
        hud = object.__new__(HUD)
        hud._max_width = max_width
        return hud

    def test_normal_display(self):
        """正常长度题目和答案：完整显示，不截断。"""
        hud = self._make_hud(200)
        text = hud._format_display("什么是 Python？", "A", "ai", "已识别")
        self.assertIn("什么是 Python？", text)
        self.assertIn("答案：A", text)
        self.assertIn("来源：AI", text)
        self.assertIn("✅", text)

    def test_long_question_truncated(self):
        """超长题目被截断为 head...tail 格式。"""
        hud = self._make_hud(40)
        q = "这是一道非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的题目文本内容用于测试截断效果"
        text = hud._format_display(q, "A", "ai", "已识别")
        self.assertIn("...", text)

    def test_long_answer_truncated(self):
        """超长答案被截断到 60 字符以内。"""
        hud = self._make_hud(200)
        ans = "A" * 100
        text = hud._format_display("题目", ans, "ai", "已识别")
        # 答案应被截断为 57 字符 + "..."
        self.assertIn("答案：" + "A" * 57 + "...", text)

    def test_short_answer_not_truncated(self):
        """短答案不被截断。"""
        hud = self._make_hud(200)
        text = hud._format_display("题目", "B", "ai", "已识别")
        self.assertIn("答案：B", text)
        self.assertNotIn("...", text.split("答案")[1] if "答案" in text else "")

    def test_empty_answer_omitted(self):
        """空答案不显示答案段。"""
        hud = self._make_hud(200)
        text = hud._format_display("题目", "", "ai", "已识别")
        self.assertNotIn("答案", text)

    def test_empty_question_uses_prefix_only(self):
        """空题目仍显示前缀。"""
        hud = self._make_hud(200)
        text = hud._format_display("", "A", "ai", "已识别")
        self.assertTrue(text.startswith("题目：") or text.startswith("[✅] 题目："))

    def test_multiple_answers_combined(self):
        """多答案用分隔符连接。"""
        hud = self._make_hud(200)
        text = hud._format_display("题目", "A|答案分隔|B", "ai", "已识别")
        self.assertIn("A  /  B", text)

    def test_max_width_from_window(self):
        """_max_width 来自窗口宽度，非默认 80。"""
        hud = self._make_hud(30)
        q = "这是一道非常非常非常非常非常非常非常非常非常非常非常非常长的题目文本用来测试截断效果"
        text = hud._format_display(q, "A", "ai", "已识别")
        self.assertIn("...", text)

    def test_error_status_icon(self):
        """错误状态使用 ❌ 图标。"""
        hud = self._make_hud(200)
        text = hud._format_display("题目", "", "", "错误")
        self.assertIn("❌", text)

    def test_cache_hit_icon(self):
        """缓存命中使用 📋 图标。"""
        hud = self._make_hud(200)
        text = hud._format_display("题目", "C", "cache", "缓存命中")
        self.assertIn("📋", text)
        self.assertIn("来源：缓存", text)


if __name__ == "__main__":
    unittest.main()
