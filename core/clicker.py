"""
点击模块 —— 基于 pyautogui 的鼠标模拟，支持全自动模式下的答案选项点击
"""

import time
import logging
from typing import Optional

import pyautogui

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

    def execute(self, screenshot_img, answer_str: str) -> bool:
        """
        在截图中定位答案选项并点击。
        多选题：每次点击后重新截图，用最新截图定位下一个选项，避免坐标漂移。
        answer_str: 答案字符串（多选用 |答案分隔| 分隔）
        返回 True 表示全部点击完成，False 表示有选项定位失败。
        """
        answers = parse_answers(answer_str)
        all_success = True
        current_img = screenshot_img  # 首次用引擎传入的截图

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

            # 点击并验证（screenshot_after_click 返回点击前后截图）
            before, after = screenshot_after_click(screen_x, screen_y)
            ok = self._recognizer.verify_answer_clicked(before, after, ans)
            if not ok:
                logger.warning("点击验证未通过: %s", ans)
                all_success = False

            # 多选题：用点击后截图作为下一轮定位的基准，确保坐标不漂移
            # 即使验证未通过也更新截图，因为界面状态已经改变（点击动作已发生）
            current_img = after

        return all_success
