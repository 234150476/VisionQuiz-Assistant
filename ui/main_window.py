"""
主窗口 —— 应用程序主界面
功能：题库选择、模式选择、启动/停止控制、题库导入、查看题库
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging

from core import config
from core.db_manager import QuestionDB
from core.engine import Engine, EngineMode
from core.recognizer import RecognizeResult
from ui.hud import HUD
from ui.settings_dialog import SettingsDialog
from ui.db_viewer import DBViewerDialog

logger = logging.getLogger(__name__)


class MainWindow:
    """
    应用主窗口。
    """

    def __init__(self):
        self._cfg = config.load_config()
        self._engine: Engine = None
        self._hud: HUD = None
        self._current_db_path: str = ""  # 当前选中的题库 .db 路径

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

    # ------------------------------------------------------------------
    # 构建主窗口界面
    # ------------------------------------------------------------------

    def _build(self):
        root = self._root

        # ---- 题库区 ----
        db_frame = ttk.LabelFrame(root, text="题库")
        db_frame.pack(fill=tk.X, padx=12, pady=(12, 4))

        self._db_var = tk.StringVar(value="（未选择）")
        tk.Label(db_frame, textvariable=self._db_var, width=40, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=8, pady=4
        )
        tk.Button(db_frame, text="选择题库", command=self._select_db).grid(
            row=0, column=1, padx=4, pady=4
        )
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
            mode_frame, text="半自动（仅显示答案）",
            variable=self._mode_var, value=EngineMode.SEMI_AUTO,
        ).pack(side=tk.LEFT, padx=12, pady=4)
        tk.Radiobutton(
            mode_frame, text="全自动（自动点击选项）",
            variable=self._mode_var, value=EngineMode.FULL_AUTO,
        ).pack(side=tk.LEFT, padx=12, pady=4)

        # ---- HUD 外观快速调整 ----
        hud_frame = ttk.LabelFrame(root, text="HUD 外观（启动前可调整）")
        hud_frame.pack(fill=tk.X, padx=12, pady=4)

        tk.Label(hud_frame, text="透明度").grid(row=0, column=0, padx=8, pady=4, sticky="w")
        self._opacity_var = tk.DoubleVar(value=self._cfg.get("hud_opacity", 0.85))
        opacity_slider = tk.Scale(
            hud_frame, variable=self._opacity_var,
            from_=0.1, to=1.0, resolution=0.05, orient=tk.HORIZONTAL, length=180,
            command=self._on_opacity_change,
        )
        opacity_slider.grid(row=0, column=1, padx=4, pady=4, sticky="w")

        tk.Label(hud_frame, text="顶部偏移(px)").grid(row=0, column=2, padx=8, pady=4, sticky="w")
        self._offset_var = tk.IntVar(value=self._cfg.get("hud_top_offset", 20))
        offset_spin = tk.Spinbox(
            hud_frame, from_=0, to=300, textvariable=self._offset_var, width=6,
            command=self._on_offset_change,
        )
        offset_spin.grid(row=0, column=3, padx=4, pady=4, sticky="w")

        # ---- 控制按钮 ----
        btn_frame = tk.Frame(root)
        btn_frame.pack(fill=tk.X, padx=12, pady=8)

        self._start_btn = tk.Button(
            btn_frame, text="启动", width=12,
            bg="#4caf50", fg="white", font=("微软雅黑", 11, "bold"),
            command=self._on_start,
        )
        self._start_btn.pack(side=tk.LEFT, padx=4)

        self._stop_btn = tk.Button(
            btn_frame, text="停止", width=12,
            bg="#f44336", fg="white", font=("微软雅黑", 11, "bold"),
            command=self._on_stop, state=tk.DISABLED,
        )
        self._stop_btn.pack(side=tk.LEFT, padx=4)

        # 半自动模式专用：标记当前题目已手动完成
        self._answered_btn = tk.Button(
            btn_frame, text="✓ 已答", width=8,
            bg="#1976d2", fg="white", font=("微软雅黑", 10),
            command=self._on_mark_answered, state=tk.DISABLED,
        )
        self._answered_btn.pack(side=tk.LEFT, padx=4)

        tk.Button(
            btn_frame, text="设置", width=8,
            command=self._open_settings,
        ).pack(side=tk.RIGHT, padx=4)

        # ---- 状态栏 ----
        status_frame = tk.Frame(root, bd=1, relief=tk.SUNKEN)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_var = tk.StringVar(value="就绪")
        tk.Label(status_frame, textvariable=self._status_var, anchor="w").pack(
            fill=tk.X, padx=6, pady=2
        )

    # ------------------------------------------------------------------
    # 题库操作
    # ------------------------------------------------------------------

    def _select_db(self):
        """选择已有的 .db 题库文件，若引擎运行中则热切换。"""
        db_dir = config.get_db_dir()
        path = filedialog.askopenfilename(
            title="选择题库文件",
            initialdir=db_dir,
            filetypes=[("SQLite 数据库", "*.db"), ("所有文件", "*.*")],
            parent=self._root,
        )
        if path:
            self._current_db_path = path
            self._db_var.set(os.path.basename(path))
            self._status_var.set(f"已选择题库: {os.path.basename(path)}")
            # 引擎运行中：热切换题库
            if self._engine and self._engine.is_running:
                self._engine.switch_db(path)
                self._status_var.set(f"题库已切换: {os.path.basename(path)}")

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
        self._db_var.set(os.path.basename(db_path))
        self._status_var.set(f"已导入题库: {base_name}")

    def _view_db(self):
        """打开题库查看器。"""
        if not self._current_db_path or not os.path.isfile(self._current_db_path):
            messagebox.showwarning("提示", "请先选择或导入题库", parent=self._root)
            return
        DBViewerDialog(self._root, self._current_db_path)

    # ------------------------------------------------------------------
    # 引擎控制
    # ------------------------------------------------------------------

    def _on_start(self):
        # 防止重复启动（理论上按钮已 disabled，此处作为双重保险）
        if self._engine and self._engine.is_running:
            return

        # 检查配置完整性
        if not config.is_config_complete(self._cfg):
            messagebox.showwarning(
                "配置不完整",
                "请先在【设置】中填写 API Key 和模型名称，然后再启动。",
                parent=self._root,
            )
            return

        mode = self._mode_var.get()
        db_path = self._current_db_path if os.path.isfile(self._current_db_path) else None

        # 屏幕分辨率在主线程已获取，传入引擎（禁止引擎在子线程创建 tk.Tk()）
        self._engine = Engine(
            cfg=self._cfg,
            db_path=db_path,
            mode=mode,
            screen_size=(self._screen_w, self._screen_h),
        )
        self._engine.set_callbacks(
            on_result=self._on_result,
            on_error=self._on_engine_error,
            on_status=self._on_engine_status,
        )
        self._engine.start()

        self._start_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)
        # 半自动模式才显示"已答"按钮
        if mode == EngineMode.SEMI_AUTO:
            self._answered_btn.config(state=tk.NORMAL)

    def _on_stop(self):
        """停止引擎（非阻塞：在子线程执行 stop，避免主线程冻结）。"""
        engine = self._engine
        self._engine = None
        self._start_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._answered_btn.config(state=tk.DISABLED)
        self._hud.set_status("正在停止…")
        self._status_var.set("正在停止…")

        def _do_stop():
            if engine:
                engine.stop()
            self._root.after(0, self._on_stop_done)

        threading.Thread(target=_do_stop, daemon=True, name="EngineStopThread").start()

    def _on_stop_done(self):
        """stop 完成后回到主线程更新 UI。检查 root/hud 是否仍存活（防止关窗竞态）。"""
        try:
            if self._hud:
                self._hud.set_status("已停止")
            self._status_var.set("已停止")
        except tk.TclError:
            pass  # root 已销毁，忽略

    def _on_mark_answered(self):
        """半自动模式：用户手动选择答案后点击，标记当前题目已答。"""
        if self._engine:
            self._engine.mark_current_answered()
            self._status_var.set("已标记当前题目为已答")

    # ------------------------------------------------------------------
    # 引擎回调（在引擎线程调用，全部通过 after() 派发到主线程）
    # ------------------------------------------------------------------

    def _on_result(self, result: RecognizeResult):
        question = result.question_text
        answer = result.answer
        source = result.source
        # update_content 内部已通过 after() 派发，线程安全
        self._hud.update_content(
            question=question,
            answer=answer,
            source=source,
            status="识别成功",
        )
        self._root.after(0, lambda: self._status_var.set(
            f"[{source}] 答案: {answer[:40]}"
        ))

    def _on_engine_error(self, msg: str):
        self._hud.show_error(msg)
        self._root.after(0, lambda: self._status_var.set(f"错误: {msg}"))

    def _on_engine_status(self, status: str):
        self._hud.set_status(status)
        self._root.after(0, lambda: self._status_var.set(status))

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
    # 设置对话框
    # ------------------------------------------------------------------

    def _open_settings(self):
        dialog = SettingsDialog(self._root, self._cfg)
        self._root.wait_window(dialog)
        if dialog.result is not None:
            self._cfg = dialog.result
            config.save_config(self._cfg)
            # 更新 HUD 外观变量
            self._opacity_var.set(self._cfg.get("hud_opacity", 0.85))
            self._offset_var.set(self._cfg.get("hud_top_offset", 20))
            if self._hud:
                self._hud.set_opacity(self._cfg["hud_opacity"])
                self._hud.set_top_offset(self._cfg["hud_top_offset"])
            # 若引擎正在运行，提示部分配置需要重启引擎才能生效
            if self._engine and self._engine.is_running:
                self._status_var.set("配置已保存（API/模型/阈值等设置需重启引擎生效）")
            else:
                self._status_var.set("配置已保存")

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def _on_close(self):
        engine = self._engine
        self._engine = None
        config.save_config(self._cfg)

        if not (engine and engine.is_running):
            # 引擎未运行，直接销毁
            if self._hud:
                self._hud.destroy()
            self._root.destroy()
            return

        # 引擎运行中：禁用所有控制按钮，防止关闭过程中重复操作
        self._start_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.DISABLED)
        self._answered_btn.config(state=tk.DISABLED)

        # 在子线程执行 stop（join 最多 35s），避免冻结主线程
        if self._hud:
            self._hud.set_status("正在退出…")

        def _do_close():
            engine.stop()
            self._root.after(0, _finish)

        def _finish():
            try:
                if self._hud:
                    self._hud.destroy()
                self._root.destroy()
            except tk.TclError:
                pass

        threading.Thread(target=_do_close, daemon=True, name="EngineCloseThread").start()

    # ------------------------------------------------------------------
    # 启动主循环
    # ------------------------------------------------------------------

    def run(self):
        self._root.mainloop()
