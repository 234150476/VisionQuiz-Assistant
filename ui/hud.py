"""
HUD 模块 —— 屏幕顶部常驻悬浮提示条
鼠标穿透（WS_EX_TRANSPARENT）、半透明、始终置顶
显示题目摘要 + 答案
"""

import logging
import sys
import time
import tkinter as tk
from enum import Enum

logger = logging.getLogger(__name__)

# Windows 专用：鼠标穿透扩展样式
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_GWL_EXSTYLE = -20


class HUDState(Enum):
    NORMAL = "normal"
    ERROR = "error"
    RECOVERING = "recovering"


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
    通过 show_content() / show_error() 更新显示内容（线程安全）。
    """

    # 布局常量
    _PAD_X = 20
    _PAD_Y = 6
    _FONT_MAIN = ("微软雅黑", 11)
    _FONT_ANS = ("微软雅黑", 12, "bold")
    _ERROR_HOLD_SECONDS = 3.0
    _ERROR_DEDUPE_SECONDS = 5.0
    _ERROR_RECOVER_SECONDS = 5.0
    _BG_NORMAL = "#2b2b2b"
    _FG_STATUS_NORMAL = "#888888"
    _FG_SOURCE_NORMAL = "#aaaaaa"
    _FG_QUESTION_NORMAL = "#cccccc"
    _FG_ANSWER_NORMAL = "#00e676"
    _BG_ERROR = "#3a1f1f"
    _FG_ERROR = "#ff6b6b"
    _FG_ERROR_ACCENT = "#ffd166"

    def __init__(self, root: tk.Tk, opacity: float = 0.85, top_offset: int = 20):
        self._root = root
        self._opacity = max(0.1, min(1.0, opacity))
        self._top_offset = top_offset
        self._win: tk.Toplevel = None
        self._display_var = tk.StringVar(value="就绪")
        self._hud_state = HUDState.NORMAL
        self._last_error_msg = ""
        self._last_error_ts = 0.0
        self._destroyed = False
        self._display_label = None
        self._frame = None
        self._build()

    # ------------------------------------------------------------------
    # 构建窗口
    # ------------------------------------------------------------------

    def _build(self):
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)  # 无边框
        win.attributes("-topmost", True)  # 始终置顶
        win.attributes("-alpha", self._opacity)
        win.configure(bg=self._BG_NORMAL)

        # 定位到屏幕顶部中央
        sw = win.winfo_screenwidth()
        win_w = min(sw - 40, 900)
        win.geometry(f"{win_w}x70+{(sw - win_w) // 2}+{self._top_offset}")

        # --- 内部布局：单行紧凑 ---
        frame = tk.Frame(win, bg=self._BG_NORMAL)
        frame.pack(fill=tk.BOTH, expand=True, padx=self._PAD_X, pady=self._PAD_Y)

        self._display_label = tk.Label(
            frame,
            textvariable=self._display_var,
            bg=self._BG_NORMAL,
            fg=self._FG_QUESTION_NORMAL,
            font=self._FONT_MAIN,
            anchor="w",
        )
        self._display_label.pack(fill=tk.BOTH, expand=True)

        self._win = win
        self._frame = frame
        self._max_width = win_w

        # Windows 鼠标穿透：必须在窗口完整显示后再设置扩展样式
        if sys.platform == "win32":
            win.update()  # 确保窗口已被操作系统实际创建并分配 HWND
            hwnd = win.winfo_id()
            if hwnd:
                _set_click_through(hwnd)

    # ------------------------------------------------------------------
    # 公共接口（线程安全）
    # ------------------------------------------------------------------

    def _is_window_alive(self) -> bool:
        if self._destroyed or self._win is None:
            return False
        try:
            return bool(self._win.winfo_exists())
        except tk.TclError:
            return False

    def _format_display(
        self,
        question: str,
        answer: str,
        source: str,
        status: str,
    ) -> str:
        """将 question/answer/source/status 组装为单行紧凑显示字符串。"""
        status_icons = {
            "识别中": "🔍",
            "已识别": "✅",
            "错误": "❌",
            "缓存命中": "📋",
        }
        status_icon = status_icons.get(status, status) if status else ""

        ans_clean = answer.replace("|答案分隔|", "  /  ") if answer else ""
        source_label = {"bank": "题库", "cache": "缓存", "ai": "AI"}.get(source, source or "")

        max_width = getattr(self, "_max_width", 80)

        # --- 固定部分 + 答案 + 题目预算 ---
        fixed_parts = []
        if status_icon:
            fixed_parts.append(f"[{status_icon}]")
        fixed_prefix = " ".join(fixed_parts) + " 题目：" if fixed_parts else "题目："
        fixed_suffix = ""
        if source_label:
            fixed_suffix += f" | 来源：{source_label}"
        if ans_clean:
            fixed_suffix += f" | 答案：{ans_clean}"
        fixed_len = len(fixed_prefix) + len(fixed_suffix)

        # 答案过长时截断（在预算计算后、拼接前）
        if ans_clean and len(ans_clean) > 60:
            ans_clean = ans_clean[:57] + "..."
            # 重新计算 fixed_suffix（答案已截断）
            fixed_suffix = ""
            if source_label:
                fixed_suffix += f" | 来源：{source_label}"
            fixed_suffix += f" | 答案：{ans_clean}"
            fixed_len = len(fixed_prefix) + len(fixed_suffix)

        question_budget = max(10, max_width - fixed_len)

        q = question.strip().replace("\n", " ") if question else ""
        if len(q) > question_budget:
            head = int(question_budget * 0.8)
            tail = int(question_budget * 0.2)
            if tail > 0:
                q = q[:head] + "..." + q[-tail:]
            else:
                q = q[:head] + "..."

        parts = [fixed_prefix + q] if q else [fixed_prefix]
        if source_label:
            parts.append(f"来源：{source_label}")
        if ans_clean:
            parts.append(f"答案：{ans_clean}")

        return " | ".join(parts) if len(parts) > 1 else parts[0]

    def _safe_after(self, callback, *args) -> bool:
        if not self._is_window_alive():
            return False

        def _run():
            if not self._is_window_alive():
                return
            try:
                callback(*args)
            except tk.TclError:
                pass

        try:
            self._win.after(0, _run)
            return True
        except tk.TclError:
            return False

    def _apply_normal_style(self):
        if not self._is_window_alive():
            return
        self._win.configure(bg=self._BG_NORMAL)
        self._frame.configure(bg=self._BG_NORMAL)
        self._display_label.configure(bg=self._BG_NORMAL, fg=self._FG_QUESTION_NORMAL)

    def _apply_error_style(self):
        if not self._is_window_alive():
            return
        self._win.configure(bg=self._BG_ERROR)
        self._frame.configure(bg=self._BG_ERROR)
        self._display_label.configure(bg=self._BG_ERROR, fg=self._FG_ERROR)

    def _maybe_recover(self, now: float) -> bool:
        if self._hud_state != HUDState.ERROR:
            return True

        age = now - self._last_error_ts
        if age < self._ERROR_HOLD_SECONDS:
            return False
        if age < self._ERROR_RECOVER_SECONDS:
            return False

        self._hud_state = HUDState.RECOVERING
        self._apply_normal_style()
        self._hud_state = HUDState.NORMAL
        return True

    def update_content(
        self,
        question: str = "",
        answer: str = "",
        source: str = "",
        status: str = "",
    ):
        self.show_content(question=question, answer=answer, source=source, status=status)

    def show_content(
        self,
        question: str = "",
        answer: str = "",
        source: str = "",
        status: str = "",
    ):
        if self._destroyed:
            return
        self._safe_after(self._do_update, question, answer, source, status)

    def _do_update(self, question: str, answer: str, source: str, status: str):
        if self._destroyed:
            return
        now = time.monotonic()
        if not self._maybe_recover(now):
            return

        self._apply_normal_style()
        display_text = self._format_display(question, answer, source, status)
        self._display_var.set(display_text)

    def set_status(self, status: str):
        self.show_status(status)

    def show_status(self, status: str):
        if self._destroyed:
            return
        self._safe_after(self._do_set_status, status)

    def _do_set_status(self, status: str):
        if self._destroyed:
            return
        now = time.monotonic()
        if self._hud_state == HUDState.ERROR and not self._maybe_recover(now):
            return
        self._display_var.set(status)

    def show_error(self, msg: str):
        if self._destroyed:
            return
        self._safe_after(self._do_error, msg)

    def _do_error(self, msg: str):
        if self._destroyed:
            return

        now = time.monotonic()
        if msg == self._last_error_msg and (now - self._last_error_ts) < self._ERROR_DEDUPE_SECONDS:
            return

        self._hud_state = HUDState.ERROR
        self._last_error_msg = msg
        self._last_error_ts = now
        self._apply_error_style()
        self._display_var.set(f"[❌ 错误] {msg}")

    def set_opacity(self, opacity: float):
        """动态调整透明度。"""
        self._opacity = max(0.1, min(1.0, opacity))
        if self._is_window_alive():
            self._win.attributes("-alpha", self._opacity)

    def set_top_offset(self, offset: int):
        """动态调整顶部偏移（重新定位窗口）。"""
        self._top_offset = offset
        if self._is_window_alive():
            sw = self._win.winfo_screenwidth()
            win_w = self._win.winfo_width()
            x = (sw - win_w) // 2
            self._win.geometry(f"+{x}+{offset}")

    def destroy(self):
        if self._destroyed:
            return
        self._destroyed = True
        if self._win:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None
