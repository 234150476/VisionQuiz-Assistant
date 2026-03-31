"""
设置对话框 —— API / 模型 / 运行参数配置
"""

import tkinter as tk
from tkinter import ttk, messagebox

from core import config


class SettingsDialog(tk.Toplevel):
    """
    模态设置对话框。
    关闭后通过 self.result 获取新配置（None 表示用户取消）。
    """

    def __init__(self, parent: tk.Tk, cfg: dict):
        super().__init__(parent)
        self.title("设置")
        self.resizable(False, False)
        self.grab_set()  # 模态

        self._cfg = dict(cfg)  # 工作副本
        self.result = None     # 用户点击确定后存放新配置

        self._vars: dict[str, tk.Variable] = {}
        self._build()
        self._load_values()

        # 居中显示
        self.update_idletasks()
        pw = parent.winfo_x()
        py = parent.winfo_y()
        pw2 = parent.winfo_width()
        ph2 = parent.winfo_height()
        dw = self.winfo_width()
        dh = self.winfo_height()
        x = pw + (pw2 - dw) // 2
        y = py + (ph2 - dh) // 2
        self.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # 构建界面
    # ------------------------------------------------------------------

    def _build(self):
        pad = {"padx": 10, "pady": 4}

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ---- Tab 1：API 设置 ----
        tab_api = ttk.Frame(notebook)
        notebook.add(tab_api, text="API 设置")
        self._build_api_tab(tab_api)

        # ---- Tab 2：运行参数 ----
        tab_run = ttk.Frame(notebook)
        notebook.add(tab_run, text="运行参数")
        self._build_run_tab(tab_run)

        # ---- Tab 3：HUD 外观 ----
        tab_hud = ttk.Frame(notebook)
        notebook.add(tab_hud, text="HUD 外观")
        self._build_hud_tab(tab_hud)

        # ---- 底部按钮 ----
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        tk.Button(btn_frame, text="确定", width=10, command=self._on_ok).pack(side=tk.RIGHT, padx=4)
        tk.Button(btn_frame, text="取消", width=10, command=self.destroy).pack(side=tk.RIGHT)

    def _row(self, parent, row: int, label: str, widget_factory):
        tk.Label(parent, text=label, anchor="w").grid(
            row=row, column=0, sticky="w", padx=10, pady=4
        )
        w = widget_factory(parent)
        w.grid(row=row, column=1, sticky="ew", padx=10, pady=4)
        parent.columnconfigure(1, weight=1)
        return w

    def _entry(self, parent, key: str, show=""):
        var = tk.StringVar()
        self._vars[key] = var
        return tk.Entry(parent, textvariable=var, show=show, width=40)

    def _build_api_tab(self, parent):
        fields = [
            ("provider", "服务商（openai/anthropic/…）"),
            ("api_key",  "API Key"),
            ("api_base_url", "API Base URL"),
            ("model",    "模型名称"),
        ]
        for i, (key, label) in enumerate(fields):
            show = "*" if key == "api_key" else ""
            self._row(parent, i, label, lambda p, k=key, s=show: self._entry(p, k, s))

        # timeout 用 Spinbox
        tk.Label(parent, text="超时（秒）", anchor="w").grid(
            row=len(fields), column=0, sticky="w", padx=10, pady=4
        )
        var = tk.IntVar()
        self._vars["timeout"] = var
        sb = tk.Spinbox(parent, from_=5, to=120, textvariable=var, width=10)
        sb.grid(row=len(fields), column=1, sticky="w", padx=10, pady=4)

    def _build_run_tab(self, parent):
        # 相似度阈值
        tk.Label(parent, text="题库匹配阈值（0.0~1.0）", anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=4
        )
        var_thresh = tk.DoubleVar()
        self._vars["similarity_threshold"] = var_thresh
        tk.Entry(parent, textvariable=var_thresh, width=10).grid(
            row=0, column=1, sticky="w", padx=10, pady=4
        )

        # 缓存过期天数
        tk.Label(parent, text="缓存过期天数", anchor="w").grid(
            row=1, column=0, sticky="w", padx=10, pady=4
        )
        var_expire = tk.IntVar()
        self._vars["cache_expire_days"] = var_expire
        tk.Spinbox(parent, from_=1, to=365, textvariable=var_expire, width=10).grid(
            row=1, column=1, sticky="w", padx=10, pady=4
        )

        # 截图间隔
        tk.Label(parent, text="截图间隔（秒）", anchor="w").grid(
            row=2, column=0, sticky="w", padx=10, pady=4
        )
        var_interval = tk.IntVar()
        self._vars["screenshot_interval"] = var_interval
        tk.Spinbox(parent, from_=1, to=30, textvariable=var_interval, width=10).grid(
            row=2, column=1, sticky="w", padx=10, pady=4
        )

        parent.columnconfigure(1, weight=1)

    def _build_hud_tab(self, parent):
        # 透明度
        tk.Label(parent, text="HUD 透明度（0.1~1.0）", anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=4
        )
        var_opacity = tk.DoubleVar()
        self._vars["hud_opacity"] = var_opacity
        tk.Entry(parent, textvariable=var_opacity, width=10).grid(
            row=0, column=1, sticky="w", padx=10, pady=4
        )

        # 顶部偏移
        tk.Label(parent, text="HUD 顶部偏移（像素）", anchor="w").grid(
            row=1, column=0, sticky="w", padx=10, pady=4
        )
        var_offset = tk.IntVar()
        self._vars["hud_top_offset"] = var_offset
        tk.Spinbox(parent, from_=0, to=200, textvariable=var_offset, width=10).grid(
            row=1, column=1, sticky="w", padx=10, pady=4
        )

        parent.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    # 数据加载 / 保存
    # ------------------------------------------------------------------

    def _load_values(self):
        for key, var in self._vars.items():
            val = self._cfg.get(key, config.CONFIG_DEFAULTS.get(key, ""))
            try:
                var.set(val)
            except Exception:
                var.set(str(val))

    def _on_ok(self):
        new_cfg = dict(self._cfg)
        for key, var in self._vars.items():
            try:
                val = var.get()
                # 类型转换
                default = config.CONFIG_DEFAULTS.get(key)
                if isinstance(default, float):
                    val = float(val)
                elif isinstance(default, int):
                    val = int(val)
                new_cfg[key] = val
            except (ValueError, tk.TclError) as e:
                messagebox.showerror("输入错误", f"字段 {key} 的值无效：{e}", parent=self)
                return

        # 验证阈值范围（严格大于 0.0，因为 0.0 会匹配所有题目失去过滤意义）
        thresh = new_cfg.get("similarity_threshold", 0.8)
        if not (0.0 < thresh <= 1.0):
            messagebox.showerror("输入错误", "题库匹配阈值必须在 (0.0, 1.0] 之间（不含 0.0）", parent=self)
            return

        opacity = new_cfg.get("hud_opacity", 0.85)
        if not (0.1 <= opacity <= 1.0):
            messagebox.showerror("输入错误", "HUD 透明度必须在 0.1~1.0 之间", parent=self)
            return

        self.result = new_cfg
        self.destroy()
