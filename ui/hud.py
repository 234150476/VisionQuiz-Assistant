"""
HUD 模块 —— 屏幕顶部常驻悬浮提示条
鼠标穿透（WS_EX_TRANSPARENT）、半透明、始终置顶
显示题目摘要 + 答案
"""

import tkinter as tk
import logging
import sys

logger = logging.getLogger(__name__)

# Windows 专用：鼠标穿透扩展样式
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_GWL_EXSTYLE = -20


def _set_click_through(hwnd):
    """将窗口设置为鼠标穿透（仅 Windows）。"""
    try:
        import ctypes
        style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        style |= _WS_EX_TRANSPARENT | _WS_EX_LAYERED
        ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style)
        # 必须调用 SetLayeredWindowAttributes 激活 LAYERED 窗口，否则穿透可能不生效
        # 使用 LWA_ALPHA(0x02)，alpha=255 表示完全不透明（透明度由 tkinter 的 -alpha 控制）
        LWA_ALPHA = 0x00000002
        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    except Exception as e:
        logger.warning("设置鼠标穿透失败: %s", e)


class HUD:
    """
    HUD 悬浮条。
    必须在主线程（tkinter 线程）中创建和更新。
    通过 update_content() 更新显示内容（线程安全）。
    """

    # 布局常量
    _PAD_X = 20
    _PAD_Y = 6
    _MAX_Q_LEN = 30        # 题目摘要最大字符数（超出截断）
    _FONT_MAIN = ("微软雅黑", 11)
    _FONT_ANS = ("微软雅黑", 12, "bold")

    def __init__(self, root: tk.Tk, opacity: float = 0.85, top_offset: int = 20):
        self._root = root
        self._opacity = max(0.1, min(1.0, opacity))
        self._top_offset = top_offset
        self._win: tk.Toplevel = None
        self._q_var = tk.StringVar()
        self._a_var = tk.StringVar()
        self._src_var = tk.StringVar()
        self._status_var = tk.StringVar(value="就绪")
        self._build()

    # ------------------------------------------------------------------
    # 构建窗口
    # ------------------------------------------------------------------

    def _build(self):
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)          # 无边框
        win.attributes("-topmost", True)    # 始终置顶
        win.attributes("-alpha", self._opacity)
        win.configure(bg="#2b2b2b")

        # 定位到屏幕顶部中央
        sw = win.winfo_screenwidth()
        win_w = min(sw - 40, 900)
        win.geometry(f"{win_w}x70+{(sw - win_w) // 2}+{self._top_offset}")

        # --- 内部布局 ---
        frame = tk.Frame(win, bg="#2b2b2b")
        frame.pack(fill=tk.BOTH, expand=True, padx=self._PAD_X, pady=self._PAD_Y)

        # 第一行：状态 + 来源
        top_row = tk.Frame(frame, bg="#2b2b2b")
        top_row.pack(fill=tk.X)

        tk.Label(
            top_row, textvariable=self._status_var,
            bg="#2b2b2b", fg="#888888",
            font=("微软雅黑", 9),
        ).pack(side=tk.LEFT)

        tk.Label(
            top_row, textvariable=self._src_var,
            bg="#2b2b2b", fg="#aaaaaa",
            font=("微软雅黑", 9),
        ).pack(side=tk.RIGHT)

        # 第二行：题目摘要
        tk.Label(
            frame, textvariable=self._q_var,
            bg="#2b2b2b", fg="#cccccc",
            font=self._FONT_MAIN,
            anchor="w",
        ).pack(fill=tk.X)

        # 第三行：答案（突出显示）
        tk.Label(
            frame, textvariable=self._a_var,
            bg="#2b2b2b", fg="#00e676",
            font=self._FONT_ANS,
            anchor="w",
        ).pack(fill=tk.X)

        self._win = win

        # Windows 鼠标穿透：必须在窗口完整显示后再设置扩展样式
        if sys.platform == "win32":
            win.update()  # 确保窗口已被操作系统实际创建并分配 HWND
            hwnd = win.winfo_id()
            if hwnd:
                _set_click_through(hwnd)

    # ------------------------------------------------------------------
    # 公共接口（线程安全）
    # ------------------------------------------------------------------

    def update_content(
        self,
        question: str = "",
        answer: str = "",
        source: str = "",
        status: str = "",
    ):
        """
        更新 HUD 显示内容。可在任意线程调用（通过 after 派发到 UI 线程）。
        """
        self._root.after(0, self._do_update, question, answer, source, status)

    def _do_update(self, question: str, answer: str, source: str, status: str):
        # 题目截断
        q_short = question.strip().replace("\n", " ")
        if len(q_short) > self._MAX_Q_LEN:
            q_short = q_short[: self._MAX_Q_LEN] + "…"

        # 答案分隔符美化
        ans_display = answer.replace("|答案分隔|", "  /  ")

        # 来源标签
        source_label = {"bank": "[题库]", "cache": "[缓存]", "ai": "[AI]"}.get(source, "")

        self._q_var.set(q_short if q_short else "")
        self._a_var.set(f"答案：{ans_display}" if ans_display else "")
        self._src_var.set(source_label)
        if status:
            self._status_var.set(status)

    def set_status(self, status: str):
        """仅更新状态文字。"""
        self._root.after(0, lambda: self._status_var.set(status))

    def show_error(self, msg: str):
        """以红色文字显示错误信息。"""
        self._root.after(0, self._do_error, msg)

    def _do_error(self, msg: str):
        self._q_var.set(msg)
        self._a_var.set("")
        self._src_var.set("⚠ 错误")

    def set_opacity(self, opacity: float):
        """动态调整透明度。"""
        self._opacity = max(0.1, min(1.0, opacity))
        if self._win:
            self._win.attributes("-alpha", self._opacity)

    def set_top_offset(self, offset: int):
        """动态调整顶部偏移（重新定位窗口）。"""
        self._top_offset = offset
        if self._win:
            sw = self._win.winfo_screenwidth()
            win_w = self._win.winfo_width()
            x = (sw - win_w) // 2
            self._win.geometry(f"+{x}+{offset}")

    def destroy(self):
        if self._win:
            self._win.destroy()
            self._win = None
