"""
点击模块 —— 基于 pyautogui 的鼠标模拟，支持全自动模式下的答案选项点击
支持 5 种题型统一路由：single / multi / judge / fill / essay
P7 新增 ElementClicker：通过 ElementProvider 直接操作元素
"""

import time
import logging
from typing import TYPE_CHECKING, Optional

import pyautogui

if TYPE_CHECKING:
    from core.recognizer import RecognizeResult
    from core.element_provider import ElementProvider, QuestionElement, OptionElement

logger = logging.getLogger(__name__)

# pyautogui 全局安全设置
pyautogui.FAILSAFE = True   # 鼠标移到左上角 (0,0) 时抛出异常，作为紧急停止
pyautogui.PAUSE = 0.05     # 每次操作后的默认停顿（秒）


ANSWER_SEPARATOR = "|答案分隔|"


def _move_and_click(x: int, y: int, delay_before: float = 0.1, delay_after: float = 0.3):
    """
    移动鼠标到 (x, y) 并单击。
    delay_before: 点击前等待（秒）
    delay_after:  点击后等待（秒）
    """
    time.sleep(delay_before)
    pyautogui.moveTo(x, y, duration=0.15)
    pyautogui.click()
    time.sleep(delay_after)


def click_at(x: int, y: int):
    """直接点击指定屏幕坐标。"""
    _move_and_click(x, y)


def parse_answers(answer_str: str) -> list[str]:
    """
    解析答案字符串，多选题以 |答案分隔| 分割，返回列表。
    单选/判断题返回单元素列表。
    """
    if ANSWER_SEPARATOR in answer_str:
        parts = [a.strip() for a in answer_str.split(ANSWER_SEPARATOR)]
        return [a for a in parts if a]
    return [answer_str.strip()]


def click_answer_by_coords(coords_list: list[tuple[int, int]]):
    """
    依次点击多个坐标（用于多选题）。
    每次点击之间有短暂停顿。
    """
    for i, (x, y) in enumerate(coords_list):
        logger.info("点击选项坐标 #%d: (%d, %d)", i + 1, x, y)
        _move_and_click(x, y, delay_before=0.1, delay_after=0.4)


def screenshot_after_click(x: int, y: int):
    """
    点击后立刻截一张屏，供点击验证使用。
    返回点击前截图和点击后截图的元组。
    """
    import mss
    from PIL import Image

    def _grab():
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    before = _grab()
    _move_and_click(x, y, delay_before=0.05, delay_after=0.5)
    after = _grab()
    return before, after


class AutoClicker:
    """
    全自动点击执行器。
    封装"定位坐标 → 点击 → 验证"完整流程。
    """

    def __init__(self, recognizer, screen_width: int, screen_height: int):
        """
        recognizer: core.recognizer.Recognizer 实例
        screen_width / screen_height: 主显示器分辨率（用于坐标还原）
        """
        self._recognizer = recognizer
        self._screen_w = screen_width
        self._screen_h = screen_height

    def _relative_to_screen(self, rel_x: int, rel_y: int, img_w: int, img_h: int) -> tuple[int, int]:
        """
        将截图内相对坐标映射到屏幕绝对坐标。
        （截图与屏幕分辨率一致时为 1:1，DPI 缩放下需换算）
        """
        scale_x = self._screen_w / img_w if img_w else 1
        scale_y = self._screen_h / img_h if img_h else 1
        return int(rel_x * scale_x), int(rel_y * scale_y)

    # ------------------------------------------------------------------
    # 新版统一路由入口
    # ------------------------------------------------------------------

    def dispatch_answer(self, result: "RecognizeResult") -> bool:
        """根据 question_type 路由到对应处理方法。

        Parameters
        ----------
        result : RecognizeResult
            包含 question_type, answer, options, input_targets 等字段的识别结果。
            result 中应附带 _img_w / _img_h 属性（由引擎在调用前设置），
            用于选项坐标从截图坐标到屏幕坐标的转换。

        Returns
        -------
        bool
            True 表示操作成功，False 表示失败。
        """
        # 从 result 上获取截图尺寸（引擎调用前由 _tick_click 设置）
        img_w = getattr(result, "_img_w", 0)
        img_h = getattr(result, "_img_h", 0)
        self._current_img_w = img_w
        self._current_img_h = img_h

        qt = getattr(result, "question_type", "") or "single"

        if qt == "fill":
            return self._handle_fill(result)
        elif qt == "essay":
            return self._handle_essay(result)
        elif qt == "multi":
            return self._handle_multi(result)
        elif qt == "judge":
            return self._handle_judge(result)
        else:  # 'single' or unknown
            return self._handle_single(result)

    # ------------------------------------------------------------------
    # 选项坐标解析辅助
    # ------------------------------------------------------------------

    def _resolve_option_coord(self, answer_text: str):
        """从 result.options 中查找匹配 answer_text 的选项，返回屏幕坐标。

        查找策略：
        1. 精确匹配 option["text"] == answer_text
        2. 包含匹配 answer_text in option["text"]（answer 为选项文本片段）
        3. 若 answer_text 为选项字母（A/B/C/...），按索引查找

        Returns
        -------
        tuple[int, int] | None
            屏幕绝对坐标 (x, y)，未找到返回 None。
        """
        options = getattr(self, "_current_options", [])
        if not options:
            return None

        ans = answer_text.strip()
        img_w = self._current_img_w
        img_h = self._current_img_h

        # 策略 1 & 2: 文本匹配
        best = None
        for opt in options:
            opt_text = opt.get("text", "").strip() if isinstance(opt, dict) else ""
            if not opt_text:
                continue
            if opt_text == ans:
                best = opt
                break
            if ans in opt_text and best is None:
                best = opt

        # 策略 3: 选项字母索引（A=0, B=1, ...）
        if best is None and len(ans) == 1 and ans.isalpha():
            idx = ord(ans.upper()) - ord("A")
            if 0 <= idx < len(options):
                best = options[idx]

        if best is None:
            return None

        rel_x = best.get("x", 0) if isinstance(best, dict) else 0
        rel_y = best.get("y", 0) if isinstance(best, dict) else 0
        return self._relative_to_screen(rel_x, rel_y, img_w, img_h)

    # ------------------------------------------------------------------
    # 点击验证 + 重试
    # ------------------------------------------------------------------

    def _verify_and_retry(self, x: int, y: int, answer: str) -> bool:
        """点击后截图验证，失败则重试一次。

        Returns
        -------
        bool
            最终验证结果。
        """
        before, after = screenshot_after_click(x, y)
        ok = self._recognizer.verify_answer_clicked(before, after, answer)
        if ok:
            return True

        logger.warning("点击验证未通过，重试一次: %s @ (%d, %d)", answer, x, y)
        before2, after2 = screenshot_after_click(x, y)
        ok2 = self._recognizer.verify_answer_clicked(before2, after2, answer)
        if not ok2:
            logger.warning("重试后验证仍未通过: %s", answer)
        return ok2

    # ------------------------------------------------------------------
    # 5 种题型处理方法
    # ------------------------------------------------------------------

    def _handle_single(self, result: "RecognizeResult") -> bool:
        """单选题：匹配选项坐标 → 点击 → 验证。"""
        self._current_options = getattr(result, "options", [])
        coord = self._resolve_option_coord(result.answer.strip())
        if coord is None:
            logger.warning("单选题：无法定位选项 %r", result.answer)
            return False
        screen_x, screen_y = coord
        logger.info("单选题点击 %r → 屏幕坐标 (%d, %d)", result.answer, screen_x, screen_y)
        return self._verify_and_retry(screen_x, screen_y, result.answer.strip())

    def _handle_multi(self, result: "RecognizeResult") -> bool:
        """多选题：解析多个答案 → 逐个匹配坐标 → 逐个点击验证。"""
        self._current_options = getattr(result, "options", [])
        answers = parse_answers(result.answer)
        all_success = True

        for ans in answers:
            ans = ans.strip()
            if not ans:
                continue
            coord = self._resolve_option_coord(ans)
            if coord is None:
                logger.warning("多选题：无法定位选项 %r", ans)
                all_success = False
                continue
            screen_x, screen_y = coord
            logger.info("多选题点击 %r → 屏幕坐标 (%d, %d)", ans, screen_x, screen_y)
            ok = self._verify_and_retry(screen_x, screen_y, ans)
            if not ok:
                all_success = False

        return all_success

    def _handle_judge(self, result: "RecognizeResult") -> bool:
        """判断题：根据答案语义选择 options[0]（正确）或 options[1]（错误）。"""
        options = getattr(result, "options", [])
        ans = result.answer.strip()

        # 映射答案语义到选项索引
        positive_keywords = {"正确", "对", "√", "A", "是", "true", "T"}
        negative_keywords = {"错误", "错", "×", "B", "否", "false", "F"}

        if ans in positive_keywords:
            idx = 0
        elif ans in negative_keywords:
            idx = 1
        else:
            # 尝试用字母索引
            if len(ans) == 1 and ans.isalpha():
                idx = ord(ans.upper()) - ord("A")
            else:
                idx = 0  # 默认选第一个

        if not options or idx >= len(options):
            logger.warning("判断题：选项索引 %d 越界（共 %d 个选项）", idx, len(options))
            return False

        opt = options[idx]
        rel_x = opt.get("x", 0) if isinstance(opt, dict) else 0
        rel_y = opt.get("y", 0) if isinstance(opt, dict) else 0
        screen_x, screen_y = self._relative_to_screen(
            rel_x, rel_y, self._current_img_w, self._current_img_h
        )
        logger.info("判断题点击 %r → 屏幕坐标 (%d, %d)", ans, screen_x, screen_y)
        return self._verify_and_retry(screen_x, screen_y, ans)

    def _handle_fill(self, result: "RecognizeResult") -> bool:
        """填空题：定位输入框 → 点击聚焦 → 模拟键盘输入。"""
        targets = getattr(result, "input_targets", [])
        if not targets:
            logger.warning("填空题：无输入框目标 (input_targets 为空)")
            return False

        target = targets[0]
        rel_x = target.get("x", 0) if isinstance(target, dict) else 0
        rel_y = target.get("y", 0) if isinstance(target, dict) else 0
        screen_x, screen_y = self._relative_to_screen(
            rel_x, rel_y, self._current_img_w, self._current_img_h
        )
        logger.info("填空题：点击输入框 (%d, %d) → 输入 %r", screen_x, screen_y, result.answer)

        time.sleep(0.1)
        pyautogui.click(screen_x, screen_y)
        time.sleep(0.2)
        pyautogui.write(result.answer, interval=0.05)
        return True

    def _handle_essay(self, result: "RecognizeResult") -> bool:
        """简答题：逻辑同填空题，定位文本域 → 输入。"""
        targets = getattr(result, "input_targets", [])
        if not targets:
            logger.warning("简答题：无输入框目标 (input_targets 为空)")
            return False

        target = targets[0]
        rel_x = target.get("x", 0) if isinstance(target, dict) else 0
        rel_y = target.get("y", 0) if isinstance(target, dict) else 0
        screen_x, screen_y = self._relative_to_screen(
            rel_x, rel_y, self._current_img_w, self._current_img_h
        )
        logger.info("简答题：点击文本域 (%d, %d) → 输入 %r", screen_x, screen_y, result.answer)

        time.sleep(0.1)
        pyautogui.click(screen_x, screen_y)
        time.sleep(0.2)
        pyautogui.write(result.answer, interval=0.05)
        return True

    # ------------------------------------------------------------------
    # 旧接口（deprecated，保留兼容）
    # ------------------------------------------------------------------

    def execute(self, screenshot_img, answer_str: str) -> bool:
        """
        [DEPRECATED] 旧版点击入口，保留向后兼容。
        新代码请使用 dispatch_answer(result)。

        如果传入的 result 对象具有 question_type 属性，委托到 dispatch_answer；
        否则回退到旧的 locate_option_coord + click 逻辑。
        """
        import warnings
        warnings.warn(
            "AutoClicker.execute() 已废弃，请使用 dispatch_answer(result)",
            DeprecationWarning,
            stacklevel=2,
        )

        # 尝试兼容：如果 answer_str 实际是 RecognizeResult 对象
        if hasattr(answer_str, "question_type"):
            return self.dispatch_answer(answer_str)

        # 旧逻辑回退：逐选项定位 + 点击
        answers = parse_answers(answer_str)
        all_success = True
        current_img = screenshot_img

        for i, ans in enumerate(answers):
            img_w, img_h = current_img.size
            coord = self._recognizer.locate_option_coord(current_img, ans)
            if coord is None:
                logger.warning("无法定位选项: %s", ans)
                all_success = False
                continue

            rel_x, rel_y = coord
            screen_x, screen_y = self._relative_to_screen(rel_x, rel_y, img_w, img_h)
            logger.info("点击答案 %r → 屏幕坐标 (%d, %d)", ans, screen_x, screen_y)

            before, after = screenshot_after_click(screen_x, screen_y)
            ok = self._recognizer.verify_answer_clicked(before, after, ans)
            if not ok:
                logger.warning("点击验证未通过: %s", ans)
                all_success = False

            current_img = after

        return all_success


class ElementClicker:
    """
    元素模式点击执行器。
    通过 ElementProvider 直接操作页面/窗口元素，无需坐标转换。
    """

    def __init__(self, provider: "ElementProvider"):
        self._provider = provider

    def dispatch_answer(self, result: "RecognizeResult", question_elem: "QuestionElement" = None) -> bool:
        """
        根据 question_type 路由到对应处理方法，使用 provider 直接操作元素。

        Parameters
        ----------
        result : RecognizeResult
            包含 question_type, answer, options（携带 element_ref）等字段的识别结果。
        question_elem : QuestionElement, optional
            原始题目元素（用于获取 OptionElement 引用）。

        Returns
        -------
        bool
            True 表示操作成功。
        """
        qt = getattr(result, "question_type", "") or "single"

        if qt == "fill" or qt == "essay":
            return self._handle_input(result, question_elem)
        elif qt == "multi":
            return self._handle_multi(result, question_elem)
        elif qt == "judge":
            return self._handle_judge(result, question_elem)
        else:  # 'single' or unknown
            return self._handle_single(result, question_elem)

    def _find_option(self, answer_text: str, result_options: list, question_elem: "QuestionElement" = None):
        """
        从 result.options 或 question_elem.options 中查找匹配 answer_text 的选项。
        返回 OptionElement 或 None。
        """
        # 优先从 question_elem.options 中查找（携带完整的 OptionElement）
        if question_elem and question_elem.options:
            opts = question_elem.options
        else:
            return None

        ans = answer_text.strip()

        # 精确匹配
        for opt in opts:
            if opt.text.strip() == ans:
                return opt

        # 包含匹配
        for opt in opts:
            if ans in opt.text.strip():
                return opt

        # 字母索引匹配
        if len(ans) == 1 and ans.isalpha():
            idx = ord(ans.upper()) - ord("A")
            if 0 <= idx < len(opts):
                return opts[idx]

        return None

    def _handle_single(self, result: "RecognizeResult", question_elem: "QuestionElement" = None) -> bool:
        """单选题：匹配选项 → 点击 → 验证选中。"""
        option = self._find_option(result.answer.strip(), result.options, question_elem)
        if option is None:
            logger.warning("元素模式单选题：无法定位选项 %r", result.answer)
            return False

        logger.info("元素模式单选题点击: %s", option.text)
        success = self._provider.click_option(option)
        if success:
            time.sleep(0.3)
            selected = self._provider.is_option_selected(option)
            if selected:
                return True
            logger.warning("元素模式单选题：点击后未检测到选中状态")
        return success

    def _handle_multi(self, result: "RecognizeResult", question_elem: "QuestionElement" = None) -> bool:
        """多选题：解析多个答案 → 逐个匹配 → 逐个点击验证。"""
        answers = parse_answers(result.answer)
        all_success = True

        for ans in answers:
            ans = ans.strip()
            if not ans:
                continue
            option = self._find_option(ans, result.options, question_elem)
            if option is None:
                logger.warning("元素模式多选题：无法定位选项 %r", ans)
                all_success = False
                continue

            logger.info("元素模式多选题点击: %s", option.text)
            success = self._provider.click_option(option)
            if success:
                time.sleep(0.3)
                selected = self._provider.is_option_selected(option)
                if not selected:
                    logger.warning("元素模式多选题：点击后未检测到选中: %s", ans)
                    all_success = False
            else:
                all_success = False

        return all_success

    def _handle_judge(self, result: "RecognizeResult", question_elem: "QuestionElement" = None) -> bool:
        """判断题：根据答案语义匹配选项。"""
        options = question_elem.options if question_elem else []
        if not options:
            logger.warning("元素模式判断题：无选项")
            return False

        ans = result.answer.strip()
        positive_keywords = {"正确", "对", "√", "A", "是", "true", "T"}
        negative_keywords = {"错误", "错", "×", "B", "否", "false", "F"}

        if ans in positive_keywords:
            target_text = "正确"
        elif ans in negative_keywords:
            target_text = "错误"
        else:
            target_text = ans

        option = None
        for opt in options:
            if target_text in opt.text or opt.text in target_text:
                option = opt
                break

        if option is None:
            # 回退到索引
            idx = 0 if ans in positive_keywords else 1
            if idx < len(options):
                option = options[idx]

        if option is None:
            logger.warning("元素模式判断题：无法匹配选项 %r", ans)
            return False

        logger.info("元素模式判断题点击: %s", option.text)
        return self._provider.click_option(option)

    def _handle_input(self, result: "RecognizeResult", question_elem: "QuestionElement" = None) -> bool:
        """填空题/简答题：定位输入框 → 填入文本。"""
        targets = question_elem.input_targets if question_elem else []
        if not targets:
            # 尝试从 result.input_targets 构建
            logger.warning("元素模式填空题：无输入框目标")
            return False

        target = targets[0]
        logger.info("元素模式填空题：填入文本 → %s", target.placeholder or "输入框")
        return self._provider.fill_input(target, result.answer)
