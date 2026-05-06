"""
主窗口 —— 应用程序主界面
功能：题库选择、模式选择、启动/停止控制、题库导入、查看题库
"""

import logging
import os
import threading
import tkinter as tk
from enum import Enum
from tkinter import filedialog, messagebox, ttk

from core import config
from core.db_manager import QuestionDB
from core.engine import Engine, EngineMode
from core.recognizer import RecognizeResult
from ui.db_viewer import DBViewerDialog
from ui.error_mapper import UIErrorMapper
from ui.hud import HUD
from ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)


class UILifecycleState(Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CLOSING = "closing"


class MainWindow:
    """
    应用主窗口。
    """

    def __init__(self):
        self._cfg = config.load_config()
        self._config_was_corrupt = config.was_last_load_corrupt()
        self._engine: Engine = None
        self._hud: HUD = None
        self._current_db_path: str = ""  # 当前选中的题库 .db 路径
        self._lifecycle = UILifecycleState.IDLE
        self._generation = 0

        self._root = tk.Tk()
        self._root.title("AI 自动答题助手")
        self._root.resizable(False, False)

        # 在主线程获取屏幕分辨率，供引擎的全自动点击器使用（不允许在子线程创建 Tk 实例）
        self._screen_w = self._root.winfo_screenwidth()
        self._screen_h = self._root.winfo_screenheight()

        self._build()
        self._hud = HUD(
            self._root,
            opacity=self._cfg.get("hud_opacity", 0.85),
            top_offset=self._cfg.get("hud_top_offset", 20),
        )
        self._hud.set_status("就绪")
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._sync_controls()
        self._refresh_start_button()

        if self._config_was_corrupt:
            self._status_var.set("配置文件损坏，已恢复默认值")
            self._hud.set_status("配置已恢复默认值")
            self._root.after(0, self._notify_corrupt_config)

    # ------------------------------------------------------------------
    # 构建主窗口界面
    # ------------------------------------------------------------------

    def _build(self):
        root = self._root

        # ---- 题库区 ----
        db_frame = ttk.LabelFrame(root, text="题库")
        db_frame.pack(fill=tk.X, padx=12, pady=(12, 4))

        self._db_names = self._scan_db_directory()
        self._db_var = tk.StringVar()
        self._db_combo = ttk.Combobox(
            db_frame,
            textvariable=self._db_var,
            values=self._db_names,
            state="readonly",
            width=36,
        )
        self._db_combo.grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        self._db_combo.bind("<<ComboboxSelected>>", self._on_db_selected)
        if self._db_names:
            self._db_combo.current(0)
            self._current_db_path = os.path.join(config.get_db_dir(), self._db_names[0])
            self._db_var.set(self._db_names[0])
        tk.Button(db_frame, text="导入 Excel", command=self._import_excel).grid(
            row=0, column=2, padx=4, pady=4
        )
        tk.Button(db_frame, text="查看题库", command=self._view_db).grid(
            row=0, column=3, padx=4, pady=4
        )
        db_frame.columnconfigure(0, weight=1)

        # ---- 模式选择 ----
        mode_frame = ttk.LabelFrame(root, text="运行模式")
        mode_frame.pack(fill=tk.X, padx=12, pady=4)

        self._mode_var = tk.StringVar(value=EngineMode.SEMI_AUTO)
        tk.Radiobutton(
            mode_frame,
            text="半自动（仅显示答案）",
            variable=self._mode_var,
            value=EngineMode.SEMI_AUTO,
        ).pack(side=tk.LEFT, padx=12, pady=4)
        tk.Radiobutton(
            mode_frame,
            text="全自动（自动点击选项）",
            variable=self._mode_var,
            value=EngineMode.FULL_AUTO,
        ).pack(side=tk.LEFT, padx=12, pady=4)

        # ---- HUD 外观快速调整 ----
        hud_frame = ttk.LabelFrame(root, text="HUD 外观（启动前可调整）")
        hud_frame.pack(fill=tk.X, padx=12, pady=4)

        tk.Label(hud_frame, text="透明度").grid(row=0, column=0, padx=8, pady=4, sticky="w")
        self._opacity_var = tk.DoubleVar(value=self._cfg.get("hud_opacity", 0.85))
        opacity_slider = tk.Scale(
            hud_frame,
            variable=self._opacity_var,
            from_=0.1,
            to=1.0,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            length=180,
            command=self._on_opacity_change,
        )
        opacity_slider.grid(row=0, column=1, padx=4, pady=4, sticky="w")

        tk.Label(hud_frame, text="顶部偏移(px)").grid(row=0, column=2, padx=8, pady=4, sticky="w")
        self._offset_var = tk.IntVar(value=self._cfg.get("hud_top_offset", 20))
        offset_spin = tk.Spinbox(
            hud_frame,
            from_=0,
            to=300,
            textvariable=self._offset_var,
            width=6,
            command=self._on_offset_change,
        )
        offset_spin.grid(row=0, column=3, padx=4, pady=4, sticky="w")

        # ---- 控制按钮 ----
        btn_frame = tk.Frame(root)
        btn_frame.pack(fill=tk.X, padx=12, pady=8)

        self._start_btn = tk.Button(
            btn_frame,
            text="启动",
            width=12,
            bg="#4caf50",
            fg="white",
            font=("微软雅黑", 11, "bold"),
            command=self._on_start,
        )
        self._start_btn.pack(side=tk.LEFT, padx=4)

        self._stop_btn = tk.Button(
            btn_frame,
            text="停止",
            width=12,
            bg="#f44336",
            fg="white",
            font=("微软雅黑", 11, "bold"),
            command=self._on_stop,
            state=tk.DISABLED,
        )
        self._stop_btn.pack(side=tk.LEFT, padx=4)

        # 半自动模式专用：标记当前题目已手动完成
        self._answered_btn = tk.Button(
            btn_frame,
            text="✓ 已答",
            width=8,
            bg="#1976d2",
            fg="white",
            font=("微软雅黑", 10),
            command=self._on_mark_answered,
            state=tk.DISABLED,
        )
        self._answered_btn.pack(side=tk.LEFT, padx=4)

        tk.Button(
            btn_frame,
            text="设置",
            width=8,
            command=self._open_settings,
        ).pack(side=tk.RIGHT, padx=4)

        # ---- 状态栏 ----
        status_frame = tk.Frame(root, bd=1, relief=tk.SUNKEN)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_var = tk.StringVar(value="就绪")
        tk.Label(status_frame, textvariable=self._status_var, anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=2
        )
        self._model_label = tk.Label(status_frame, text="", anchor="e", fg="gray")
        self._model_label.pack(side=tk.RIGHT, padx=6, pady=2)
        self._mode_label = tk.Label(status_frame, text="", anchor="e", fg="gray")
        self._mode_label.pack(side=tk.RIGHT, padx=6, pady=2)
        self._update_model_display()
        self._update_mode_display()

    # ------------------------------------------------------------------
    # UI 生命周期 / 调度
    # ------------------------------------------------------------------

    def _is_root_alive(self) -> bool:
        try:
            return self._root is not None and bool(self._root.winfo_exists())
        except tk.TclError:
            return False

    def _dispatch(self, callback, *args, generation: int = None) -> bool:
        if generation is None:
            generation = self._generation
        if not self._is_root_alive():
            return False

        def _run():
            if generation != self._generation:
                return
            if not self._is_root_alive():
                return
            try:
                callback(*args)
            except tk.TclError:
                pass

        try:
            self._root.after(0, _run)
            return True
        except tk.TclError:
            return False

    def _set_lifecycle(self, state: UILifecycleState):
        self._lifecycle = state
        self._sync_controls()

    def _sync_controls(self):
        if self._lifecycle == UILifecycleState.IDLE:
            self._start_btn.config(state=tk.NORMAL)
            self._stop_btn.config(state=tk.DISABLED)
            self._answered_btn.config(state=tk.DISABLED)
            return

        if self._lifecycle == UILifecycleState.RUNNING:
            self._start_btn.config(state=tk.DISABLED)
            self._stop_btn.config(state=tk.NORMAL)
            answered_state = (
                tk.NORMAL if self._mode_var.get() == EngineMode.SEMI_AUTO else tk.DISABLED
            )
            self._answered_btn.config(state=answered_state)
            return

        self._start_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.DISABLED)
        self._answered_btn.config(state=tk.DISABLED)

    def _compute_readiness(self) -> tuple:
        """检查配置是否满足启动条件。返回 (ready, reason)。"""
        api_key = self._cfg.get("api_key", "")
        model = self._cfg.get("model", "")
        db_path = self._current_db_path

        if not api_key or not model:
            return False, "请先完善配置"
        if not db_path or not os.path.isfile(db_path):
            return False, "请先选择题库"
        return True, "开始识别"

    def _refresh_start_button(self):
        """根据配置完整性刷新启动按钮的文案和禁用态。"""
        if self._lifecycle != UILifecycleState.IDLE:
            return
        ready, reason = self._compute_readiness()
        self._start_btn.config(
            text=reason,
            state=tk.NORMAL if ready else tk.DISABLED,
        )

    def _set_status_text(self, status: str):
        if self._is_root_alive():
            self._status_var.set(status)

    def _show_error(
        self,
        title: str,
        message: str,
        exc: Exception = None,
        use_hud: bool = None,
    ):
        if exc is not None:
            logger.error("%s: %s", title, message, exc_info=exc)
        else:
            logger.error("%s: %s", title, message)

        mapped_msg, _severity = UIErrorMapper.translate(exc if exc is not None else message)
        display_msg = mapped_msg
        if exc is not None and message and mapped_msg not in message:
            display_msg = f"{message}\n{mapped_msg}"
        elif exc is not None and message:
            display_msg = message

        if use_hud is None:
            use_hud = self._lifecycle == UILifecycleState.RUNNING and self._hud is not None

        if use_hud and self._hud is not None:
            self._hud.show_error(display_msg)
        elif self._is_root_alive():
            try:
                messagebox.showerror(title, display_msg, parent=self._root)
            except tk.TclError:
                pass

        self._set_status_text(f"{title}：{display_msg}")

    def _notify_corrupt_config(self):
        if not self._is_root_alive():
            return
        messagebox.showwarning(
            "配置已重置",
            "检测到配置文件损坏，程序已恢复默认配置。\n请打开【设置】重新确认 API 和模型参数。",
            parent=self._root,
        )

    # ------------------------------------------------------------------
    # 题库操作
    # ------------------------------------------------------------------

    def _scan_db_directory(self, refresh=False):
        """扫描 db/ 目录，返回排序后的 .db 文件名列表。"""
        if hasattr(self, "_db_names_cache") and self._db_names_cache is not None and not refresh:
            return self._db_names_cache
        db_dir = config.get_db_dir()
        names = sorted(
            f for f in os.listdir(db_dir)
            if f.endswith(".db") and os.path.isfile(os.path.join(db_dir, f))
        )
        self._db_names_cache = names
        return names

    def _on_db_selected(self, _event=None):
        """Combobox 选中题库时触发。"""
        name = self._db_var.get()
        if not name:
            return
        db_dir = config.get_db_dir()
        self._current_db_path = os.path.join(db_dir, name)
        self._status_var.set(f"已选择题库: {name}")
        self._refresh_start_button()

    def _import_excel(self):
        """从 Excel 文件导入题目到题库。"""
        path = filedialog.askopenfilename(
            title="选择 Excel 题库文件",
            filetypes=[("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")],
            parent=self._root,
        )
        if not path:
            return

        # 同名 .db 文件放到 db/ 目录
        db_dir = config.get_db_dir()
        base_name = os.path.splitext(os.path.basename(path))[0]
        db_path = os.path.join(db_dir, f"{base_name}.db")

        db = None
        try:
            db = QuestionDB(db_path)
            success, skipped = db.import_from_excel(path)
        except Exception as e:
            messagebox.showerror("导入失败", str(e), parent=self._root)
            return
        finally:
            if db is not None:
                db.close()

        messagebox.showinfo(
            "导入完成",
            f"成功导入 {success} 条，跳过 {skipped} 条。\n题库: {db_path}",
            parent=self._root,
        )
        self._current_db_path = db_path
        # 刷新下拉列表并选中新导入的题库
        new_name = os.path.basename(db_path)
        self._db_names = self._scan_db_directory(refresh=True)
        self._db_combo["values"] = self._db_names
        if new_name in self._db_names:
            self._db_combo.current(self._db_names.index(new_name))
            self._db_var.set(new_name)
        self._status_var.set(f"已导入题库: {base_name}")
        self._refresh_start_button()

    def _view_db(self):
        """打开题库查看器。"""
        if not self._current_db_path or not os.path.isfile(self._current_db_path):
            messagebox.showwarning("提示", "请先选择或导入题库", parent=self._root)
            return
        try:
            DBViewerDialog(self._root, self._current_db_path)
        except Exception as exc:
            self._show_error(
                "题库打开失败",
                "无法打开题库文件，请检查文件是否损坏或格式是否正确。",
                exc=exc,
                use_hud=False,
            )

    # ------------------------------------------------------------------
    # 引擎控制
    # ------------------------------------------------------------------

    def _on_start(self):
        if self._lifecycle != UILifecycleState.IDLE:
            return
        if self._engine and self._engine.is_running:
            return

        # 配置完整性由 _refresh_start_button() 的 disabled 态保证，
        # 此处保留硬检查以防极端竞态（如设置中途被外部修改）。
        if not config.is_config_complete(self._cfg):
            self._refresh_start_button()
            return

        self._generation += 1
        self._set_lifecycle(UILifecycleState.STARTING)
        self._db_combo.config(state="disabled")

        mode = self._mode_var.get()
        db_path = self._current_db_path if os.path.isfile(self._current_db_path) else None
        engine = None

        try:
            engine = Engine(
                cfg=self._cfg,
                db_path=db_path,
                mode=mode,
                screen_size=(self._screen_w, self._screen_h),
            )
            self._engine = engine
            engine.set_callbacks(
                on_result=self._on_result,
                on_error=self._on_engine_error,
                on_status=self._on_engine_status,
            )
            engine.start()
        except Exception as exc:
            self._engine = None
            self._set_lifecycle(UILifecycleState.IDLE)
            self._db_combo.config(state="readonly")
            self._refresh_start_button()
            self._show_error(
                "启动失败",
                "启动引擎失败，请检查配置、题库和运行环境后重试。",
                exc=exc,
                use_hud=False,
            )
            return

        self._set_lifecycle(UILifecycleState.RUNNING)
        if self._hud:
            self._hud.show_status("运行中")
        self._set_status_text("运行中")

    def _on_stop(self):
        """停止引擎（非阻塞：在子线程执行 stop，避免主线程冻结）。"""
        if self._lifecycle != UILifecycleState.RUNNING:
            return

        engine = self._engine
        if engine is None:
            self._set_lifecycle(UILifecycleState.IDLE)
            return

        generation = self._generation
        self._set_lifecycle(UILifecycleState.STOPPING)
        if self._hud:
            self._hud.show_status("正在停止…")
        self._set_status_text("正在停止…")

        def _do_stop():
            stop_error = None
            try:
                engine.stop()
            except Exception as exc:
                stop_error = exc
            self._dispatch(self._on_stop_done, engine, generation, stop_error, generation=generation)

        threading.Thread(target=_do_stop, daemon=True, name="EngineStopThread").start()

    def _on_stop_done(self, engine: Engine, generation: int, stop_error: Exception = None):
        if generation != self._generation or self._lifecycle == UILifecycleState.CLOSING:
            return
        if self._engine is engine:
            self._engine = None

        self._set_lifecycle(UILifecycleState.IDLE)
        self._db_combo.config(state="readonly")
        self._refresh_start_button()
        if stop_error is not None:
            self._show_error(
                "停止失败",
                "停止引擎时发生错误，请重试。",
                exc=stop_error,
                use_hud=False,
            )
            return

        if self._hud:
            self._hud.show_status("已停止")
        self._set_status_text("已停止")

    def _on_mark_answered(self):
        """半自动模式：用户手动选择答案后点击，标记当前题目已答。"""
        if self._engine and self._lifecycle == UILifecycleState.RUNNING:
            self._engine.mark_current_answered()
            self._status_var.set("已标记当前题目为已答")

    # ------------------------------------------------------------------
    # 引擎回调（在引擎线程调用，全部通过 after() 派发到主线程）
    # ------------------------------------------------------------------

    def _on_result(self, result: RecognizeResult):
        self._dispatch(self._apply_result, result, generation=self._generation)

    def _apply_result(self, result: RecognizeResult):
        if self._lifecycle != UILifecycleState.RUNNING or self._hud is None:
            return
        self._hud.show_content(
            question=result.question_text,
            answer=result.answer,
            source=result.source,
            status="识别成功",
        )
        self._set_status_text(f"[{result.source}] 答案: {result.answer[:40]}")

    def _on_engine_error(self, msg: str):
        self._dispatch(self._apply_engine_error, msg, generation=self._generation)

    def _apply_engine_error(self, msg: str):
        self._show_error("运行错误", msg, use_hud=True)

    def _on_engine_status(self, status: str):
        self._dispatch(self._apply_engine_status, status, generation=self._generation)

    def _apply_engine_status(self, status: str):
        if self._hud:
            self._hud.show_status(status)
        self._set_status_text(status)

    # ------------------------------------------------------------------
    # HUD 外观实时调整
    # ------------------------------------------------------------------

    def _on_opacity_change(self, _=None):
        val = self._opacity_var.get()
        if self._hud:
            self._hud.set_opacity(val)
        self._cfg["hud_opacity"] = val

    def _on_offset_change(self, _=None):
        try:
            val = self._offset_var.get()
        except (ValueError, tk.TclError):
            return
        if self._hud:
            self._hud.set_top_offset(val)
        self._cfg["hud_top_offset"] = val

    # ------------------------------------------------------------------
    # 模型显示
    # ------------------------------------------------------------------

    def _update_model_display(self):
        """更新状态栏右侧的当前模型名称。"""
        from core.config import MODEL_PRESETS
        preset_key = self._cfg.get("selected_preset", "")
        if preset_key and preset_key in MODEL_PRESETS:
            display = MODEL_PRESETS[preset_key]["display_name"]
        else:
            display = self._cfg.get("model", "")
        try:
            self._model_label.config(text=f"模型: {display}" if display else "")
        except tk.TclError:
            pass

    def _update_mode_display(self):
        """更新状态栏的当前输入模式。"""
        mode = self._cfg.get("input_mode", "screenshot")
        mode_labels = {
            "screenshot": "截图模式",
            "browser": "浏览器模式",
            "windows": "桌面模式",
        }
        label = mode_labels.get(mode, mode)
        try:
            self._mode_label.config(text=f"输入: {label}")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # 设置对话框
    # ------------------------------------------------------------------

    def _open_settings(self):
        try:
            dialog = SettingsDialog(self._root, self._cfg)
        except Exception as exc:
            self._show_error(
                "设置打开失败",
                "无法打开设置窗口，请稍后重试。",
                exc=exc,
                use_hud=False,
            )
            return

        self._root.wait_window(dialog)
        if dialog.result is not None:
            self._cfg = dialog.result
            self._opacity_var.set(self._cfg.get("hud_opacity", 0.85))
            self._offset_var.set(self._cfg.get("hud_top_offset", 20))
            if self._hud:
                self._hud.set_opacity(self._cfg["hud_opacity"])
                self._hud.set_top_offset(self._cfg["hud_top_offset"])
            if self._engine and self._engine.is_running:
                self._status_var.set("配置已保存（API/模型/输入模式等设置需重启引擎生效）")
            else:
                self._status_var.set("配置已保存")
            self._update_model_display()
            self._update_mode_display()
            self._refresh_start_button()

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def _on_close(self):
        if self._lifecycle == UILifecycleState.CLOSING:
            return

        self._generation += 1
        generation = self._generation
        self._set_lifecycle(UILifecycleState.CLOSING)
        config.save_config(self._cfg)

        if self._hud:
            self._hud.show_status("正在退出…")
        self._set_status_text("正在退出…")

        engine = self._engine
        if not (engine and engine.is_running):
            self._engine = None
            self._destroy_sequence()
            return

        def _do_close():
            close_error = None
            try:
                engine.stop()
            except Exception as exc:
                close_error = exc
                logger.error("关闭时停止引擎失败", exc_info=exc)
            self._dispatch(self._finish_close, engine, generation, close_error, generation=generation)

        threading.Thread(target=_do_close, daemon=True, name="EngineCloseThread").start()

    def _finish_close(self, engine: Engine, generation: int, close_error: Exception = None):
        if generation != self._generation:
            return
        if self._engine is engine:
            self._engine = None
        if close_error is not None and self._hud is not None:
            self._hud.show_error("退出时发生异常，正在尝试安全关闭。")
        self._destroy_sequence()

    def _destroy_sequence(self):
        try:
            if self._hud:
                self._hud.destroy()
                self._hud = None
        except tk.TclError:
            self._hud = None
        try:
            if self._is_root_alive():
                self._root.destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # 启动主循环
    # ------------------------------------------------------------------

    def run(self):
        self._root.mainloop()
