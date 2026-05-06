"""
WindowsElementProvider —— 通过 UI Automation 操作桌面程序元素

使用 uiautomation 库连接目标窗口，遍历 UIA 控件树查找 RadioButton/CheckBox/Button，
通过 InvokePattern/SelectionItemPattern 执行操作。
UIA 树不完整时降级到截图模式。
"""

import hashlib
import logging
import re
from typing import Optional

try:
    import uiautomation as auto
except ImportError:
    auto = None

from core.element_provider import (
    ElementProvider, QuestionElement, OptionElement, InputTarget,
)

logger = logging.getLogger(__name__)


def _compute_text_hash(text: str) -> str:
    """计算文本的 MD5 哈希。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class WindowsElementProvider(ElementProvider):
    """
    通过 UI Automation 操作 Windows 桌面程序的元素提供器。

    需要目标窗口支持 UIA（UI Automation）。
    """

    def __init__(self, target_title: str = ""):
        self._target_title = target_title
        self._window: Optional[object] = None
        self._connected = False

    @property
    def name(self) -> str:
        title = self._target_title[:20] if self._target_title else "?"
        return f"Windows(UIA:{title})"

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self, **kwargs) -> bool:
        """连接到目标窗口。"""
        if auto is None:
            logger.error("uiautomation 未安装，无法使用桌面程序模式")
            return False

        title = kwargs.get("title", self._target_title)
        if not title:
            logger.warning("未指定目标窗口标题")
            return False

        try:
            # 遍历顶级窗口做模糊匹配（RegexName 不支持中文）
            pattern = re.compile(re.escape(title), re.IGNORECASE)
            root = auto.GetRootControl()
            exact_name = None
            for child in root.GetChildren():
                if child.Name and pattern.search(child.Name):
                    exact_name = child.Name
                    break

            if not exact_name:
                logger.warning("未找到匹配窗口: %s", title)
                return False

            window = auto.WindowControl(searchDepth=1, Name=exact_name)
            if not window.Exists(maxSearchSeconds=2):
                logger.warning("窗口引用失效: %s", exact_name)
                return False

            self._window = window
            self._connected = True
            logger.info("已连接窗口: %s", exact_name)
            return True
        except Exception as exc:
            logger.warning("窗口连接失败: %s", exc)
            self._connected = False
            return False

    def _ensure_connected(self) -> bool:
        """确保窗口连接可用。"""
        if self._connected and self._window:
            try:
                # 验证窗口仍存在
                return self._window.Exists(maxSearchSeconds=1)
            except Exception:
                self._connected = False
                return False
        return self.connect(title=self._target_title)

    def close(self):
        """释放 UIA 资源。"""
        self._window = None
        self._connected = False
        logger.info("UIA 连接已释放")

    # ------------------------------------------------------------------
    # 控件树遍历
    # ------------------------------------------------------------------

    def _find_controls(self, control_type, max_depth: int = 5) -> list:
        """递归遍历控件树，查找指定类型的控件。"""
        if not self._window:
            return []

        results = []

        def _walk(control, depth):
            if depth > max_depth:
                return
            try:
                children = control.GetChildren()
                for child in children:
                    try:
                        ctrl_type = child.ControlTypeName
                        if ctrl_type == control_type:
                            results.append(child)
                        _walk(child, depth + 1)
                    except Exception:
                        continue
            except Exception:
                return

        _walk(self._window, 0)
        return results

    def _get_control_text(self, control) -> str:
        """获取控件的文本内容。"""
        try:
            name = control.Name
            if name:
                return name.strip()
            # 尝试获取 Value
            value_pattern = control.GetValuePattern()
            if value_pattern:
                return value_pattern.Value.strip()
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # 元素读取
    # ------------------------------------------------------------------

    def get_question_elements(self) -> Optional[QuestionElement]:
        """从当前窗口中读取题目元素。"""
        if not self._ensure_connected():
            return None

        try:
            # 提取题干：查找 Text 控件中内容最长的非空文本
            question_text = self._extract_question_text()
            if not question_text:
                logger.warning("未能从窗口提取题干文本")
                return None

            # 提取选项：RadioButton + CheckBox
            options = self._extract_options()
            # 提取输入框：Edit 控件
            input_targets = self._extract_input_targets()
            question_type = self._infer_type(options, input_targets)

            raw_hash = _compute_text_hash(question_text)

            return QuestionElement(
                question_text=question_text,
                question_type=question_type,
                options=options,
                input_targets=input_targets,
                raw_hash=raw_hash,
            )
        except Exception as exc:
            logger.warning("读取窗口元素失败: %s", exc)
            return None

    def _extract_question_text(self) -> str:
        """提取题干文本。"""
        if not self._window:
            return ""

        # 策略 1：查找 TextControl 中最长的文本块
        text_controls = self._find_controls("TextControl", max_depth=4)
        candidates = []
        for tc in text_controls:
            text = self._get_control_text(tc)
            if text and len(text) > 5:  # 忽略太短的文本
                candidates.append(text)

        if candidates:
            # 选择最长的文本块作为题干（通常是题目描述）
            candidates.sort(key=len, reverse=True)
            return candidates[0]

        # 策略 2：直接取窗口 Name
        try:
            name = self._window.Name
            if name and len(name) > 10:
                return name.strip()
        except Exception:
            pass

        return ""

    def _extract_options(self) -> list[OptionElement]:
        """提取所有可选选项。"""
        options = []
        index = 0

        # 查找 RadioButton
        radio_buttons = self._find_controls("RadioButtonControl", max_depth=5)
        for rb in radio_buttons:
            text = self._get_control_text(rb)
            if not text:
                continue
            selected = False
            try:
                pattern = rb.GetTogglePattern()
                if pattern:
                    selected = pattern.ToggleState == 1  # ToggleState.On
            except Exception:
                pass
            options.append(OptionElement(
                text=text,
                element_ref=rb,
                selected=selected,
                index=index,
            ))
            index += 1

        # 查找 CheckBox
        check_boxes = self._find_controls("CheckBoxControl", max_depth=5)
        for cb in check_boxes:
            text = self._get_control_text(cb)
            if not text:
                continue
            selected = False
            try:
                pattern = cb.GetTogglePattern()
                if pattern:
                    selected = pattern.ToggleState == 1
            except Exception:
                pass
            options.append(OptionElement(
                text=text,
                element_ref=cb,
                selected=selected,
                index=index,
            ))
            index += 1

        # 查找 Button（用于判断题的"正确/错误"按钮）
        if not options:
            buttons = self._find_controls("ButtonControl", max_depth=4)
            for btn in buttons:
                text = self._get_control_text(btn)
                if not text:
                    continue
                judge_words = {"正确", "错误", "对", "错", "是", "否", "True", "False"}
                if text in judge_words or len(text) < 10:
                    options.append(OptionElement(
                        text=text,
                        element_ref=btn,
                        selected=False,
                        index=index,
                    ))
                    index += 1

        return options

    def _extract_input_targets(self) -> list[InputTarget]:
        """提取输入框控件。"""
        targets = []
        edit_controls = self._find_controls("EditControl", max_depth=5)
        for i, ec in enumerate(edit_controls):
            placeholder = ""
            try:
                placeholder = ec.Name or ""
            except Exception:
                pass
            targets.append(InputTarget(
                placeholder=placeholder,
                element_ref=ec,
            ))
        return targets

    def _infer_type(self, options: list[OptionElement], inputs: list[InputTarget]) -> str:
        """根据控件类型推断题型。"""
        if inputs and not options:
            return "fill"

        # 统计控件类型
        has_radio = any(
            hasattr(o.element_ref, "ControlTypeName") and
            o.element_ref.ControlTypeName == "RadioButtonControl"
            for o in options
        )
        has_check = any(
            hasattr(o.element_ref, "ControlTypeName") and
            o.element_ref.ControlTypeName == "CheckBoxControl"
            for o in options
        )

        if has_check:
            return "multi"
        if has_radio:
            return "single"

        # 按钮类选项 → 判断题
        if len(options) == 2:
            texts = {o.text for o in options}
            judge_words = {"正确", "错误", "对", "错", "√", "×", "True", "False", "是", "否"}
            if texts & judge_words:
                return "judge"

        return "single"

    # ------------------------------------------------------------------
    # 元素操作
    # ------------------------------------------------------------------

    def click_option(self, option: OptionElement) -> bool:
        """点击指定选项。"""
        control = option.element_ref
        if control is None:
            logger.warning("选项 element_ref 为空: %s", option.text)
            return False

        try:
            # 策略 1: SelectionItemPattern（RadioButton/CheckBox 首选）
            try:
                pattern = control.GetSelectionItemPattern()
                if pattern:
                    pattern.Select()
                    logger.info("已通过 SelectionItemPattern 选择: %s", option.text)
                    return True
            except Exception:
                pass

            # 策略 2: TogglePattern
            try:
                pattern = control.GetTogglePattern()
                if pattern:
                    pattern.Toggle()
                    logger.info("已通过 TogglePattern 切换: %s", option.text)
                    return True
            except Exception:
                pass

            # 策略 3: InvokePattern（按钮类）
            try:
                pattern = control.GetInvokePattern()
                if pattern:
                    pattern.Invoke()
                    logger.info("已通过 InvokePattern 调用: %s", option.text)
                    return True
            except Exception:
                pass

            # 策略 4: 直接点击
            try:
                control.Click()
                logger.info("已直接点击: %s", option.text)
                return True
            except Exception:
                pass

            logger.warning("所有点击策略均失败: %s", option.text)
            return False
        except Exception as exc:
            logger.warning("点击选项异常: %s — %s", option.text, exc)
            return False

    def fill_input(self, target: InputTarget, text: str) -> bool:
        """在指定输入框中填入文本。"""
        control = target.element_ref
        if control is None:
            logger.warning("输入框 element_ref 为空")
            return False

        try:
            # ValuePattern 直接设置值
            try:
                pattern = control.GetValuePattern()
                if pattern:
                    pattern.SetValue(text)
                    logger.info("已通过 ValuePattern 填入文本")
                    return True
            except Exception:
                pass

            # 回退：点击聚焦 + 键盘输入
            try:
                control.Click()
                import pyautogui
                import time
                time.sleep(0.2)
                pyautogui.write(text, interval=0.03)
                logger.info("已通过键盘输入填入文本")
                return True
            except Exception:
                pass

            logger.warning("填入文本失败")
            return False
        except Exception as exc:
            logger.warning("填入文本异常: %s", exc)
            return False

    def is_option_selected(self, option: OptionElement) -> bool:
        """查询指定选项是否已选中。"""
        control = option.element_ref
        if control is None:
            return False

        try:
            # SelectionItemPattern
            try:
                pattern = control.GetSelectionItemPattern()
                if pattern:
                    return pattern.IsSelected
            except Exception:
                pass

            # TogglePattern
            try:
                pattern = control.GetTogglePattern()
                if pattern:
                    return pattern.ToggleState == 1
            except Exception:
                pass

        except Exception:
            pass

        return option.selected
