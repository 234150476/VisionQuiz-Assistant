"""
设置对话框 —— API / 模型 / 运行参数配置
"""

import tkinter as tk
from tkinter import ttk, messagebox

from core import config
from core.config import MODEL_PRESETS


class SettingsDialog(tk.Toplevel):
    """
    模态设置对话框。
    关闭后通过 self.result 获取新配置（None 表示用户取消）。
    """

    def __init__(self, parent: tk.Tk, cfg: dict):
        super().__init__(parent)
        self.title("设置")
        self.resizable(False, False)

        self._cfg = dict(cfg)  # 工作副本
        self.result = None     # 用户点击确定后存放新配置
        self._closed = False

        self._vars: dict[str, tk.Variable] = {}
        try:
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
            self.grab_set()  # 模态
        except Exception:
            self.destroy()
            raise

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

        # ---- Tab 3：输入模式 ----
        tab_input = ttk.Frame(notebook)
        notebook.add(tab_input, text="输入模式")
        self._build_input_mode_tab(tab_input)

        # ---- Tab 4：HUD 外观 ----
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
        # ---- 预设选择器（第 0 行） ----
        preset_keys = list(MODEL_PRESETS.keys())
        preset_display = ["自定义"] + [MODEL_PRESETS[k]["display_name"] for k in preset_keys]
        self._preset_key_map = {"自定义": ""}  # display_name → key
        for k in preset_keys:
            self._preset_key_map[MODEL_PRESETS[k]["display_name"]] = k

        tk.Label(parent, text="模型预设", anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=4
        )
        self._preset_var = tk.StringVar(value="自定义")
        self._preset_combo = ttk.Combobox(
            parent, textvariable=self._preset_var,
            values=preset_display, state="readonly", width=30,
        )
        self._preset_combo.grid(row=0, column=1, sticky="ew", padx=10, pady=4)
        self._preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        # ---- 手动字段（第 1 行起） ----
        fields = [
            ("api_key",  "API Key"),
            ("api_base_url", "API Base URL"),
            ("model",    "模型名称"),
        ]
        for i, (key, label) in enumerate(fields):
            show = "*" if key == "api_key" else ""
            self._row(parent, i + 1, label, lambda p, k=key, s=show: self._entry(p, k, s))

        # timeout 用 Spinbox
        tk.Label(parent, text="超时（秒）", anchor="w").grid(
            row=len(fields) + 1, column=0, sticky="w", padx=10, pady=4
        )
        var = tk.IntVar()
        self._vars["timeout"] = var
        sb = tk.Spinbox(parent, from_=5, to=120, textvariable=var, width=10)
        sb.grid(row=len(fields) + 1, column=1, sticky="w", padx=10, pady=4)

    def _on_preset_selected(self, _event=None):
        """预设下拉选择后自动填充 api_base_url 和 model。"""
        display = self._preset_var.get()
        key = self._preset_key_map.get(display, "")
        if key and key in MODEL_PRESETS:
            preset = MODEL_PRESETS[key]
            if "api_base_url" in self._vars:
                self._vars["api_base_url"].set(preset["base_url"])
            if "model" in self._vars:
                self._vars["model"].set(preset["model"])

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

    def _build_input_mode_tab(self, parent):
        # ---- 输入模式选择 ----
        mode_frame = ttk.LabelFrame(parent, text="输入模式（需重启引擎生效）")
        mode_frame.pack(fill=tk.X, padx=10, pady=8)

        self._input_mode_var = tk.StringVar(value="screenshot")
        modes = [
            ("screenshot", "截图模式（Legacy）", "使用截图+AI 视觉识别，兼容所有场景"),
            ("browser", "浏览器模式", "通过 Chrome CDP 直接读取网页元素，省 Token、速度快"),
            ("windows", "桌面程序模式", "通过 UI Automation 读取 Windows 控件，无需截图"),
        ]
        for i, (val, text, desc) in enumerate(modes):
            row = ttk.Frame(mode_frame)
            row.pack(fill=tk.X, padx=8, pady=2)
            tk.Radiobutton(
                row, text=text, variable=self._input_mode_var, value=val,
                command=self._on_input_mode_changed,
            ).pack(side=tk.LEFT)
            tk.Label(row, text=desc, fg="gray", font=("", 8)).pack(side=tk.LEFT, padx=(8, 0))

        # ---- 浏览器模式配置 ----
        self._browser_frame = ttk.LabelFrame(parent, text="浏览器模式配置")
        self._browser_frame.pack(fill=tk.X, padx=10, pady=4)

        tk.Label(self._browser_frame, text="Chrome 调试端口", anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=4
        )
        var_port = tk.IntVar()
        self._vars["browser_debug_port"] = var_port
        tk.Spinbox(
            self._browser_frame, from_=1024, to=65535, textvariable=var_port, width=10
        ).grid(row=0, column=1, sticky="w", padx=10, pady=4)

        tk.Label(self._browser_frame, text="选择器配置文件（可选）", anchor="w").grid(
            row=1, column=0, sticky="w", padx=10, pady=4
        )
        self._row(self._browser_frame, 1, "选择器配置文件（可选）",
                  lambda p: self._entry(p, "browser_selector_config"))

        # ---- 桌面程序模式配置 ----
        self._windows_frame = ttk.LabelFrame(parent, text="桌面程序模式配置")
        self._windows_frame.pack(fill=tk.X, padx=10, pady=4)

        self._row(self._windows_frame, 0, "目标窗口标题",
                  lambda p: self._entry(p, "windows_target_title"))

        self._browser_frame.columnconfigure(1, weight=1)
        self._windows_frame.columnconfigure(1, weight=1)

        # 初始状态下隐藏/显示对应配置组
        parent.after(10, self._on_input_mode_changed)

    def _on_input_mode_changed(self):
        """根据选中的输入模式，显示/隐藏对应配置组。"""
        mode = self._input_mode_var.get()
        if mode == "browser":
            self._browser_frame.pack(fill=tk.X, padx=10, pady=4, after=self._browser_frame.master.winfo_children()[0])
            self._windows_frame.pack_forget()
        elif mode == "windows":
            self._browser_frame.pack_forget()
            self._windows_frame.pack(fill=tk.X, padx=10, pady=4, after=self._browser_frame.master.winfo_children()[0])
        else:
            self._browser_frame.pack_forget()
            self._windows_frame.pack_forget()

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
        tk.Spinbox(parent, from_=0, to=300, textvariable=var_offset, width=10).grid(
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

        # 同步预设下拉框
        preset_key = self._cfg.get("selected_preset", "")
        if preset_key and preset_key in MODEL_PRESETS:
            display = MODEL_PRESETS[preset_key]["display_name"]
            self._preset_var.set(display)

        # 同步输入模式
        self._input_mode_var.set(self._cfg.get("input_mode", "screenshot"))

    def _on_ok(self):
        new_cfg = dict(self._cfg)

        # 保存选中的预设
        display = self._preset_var.get()
        preset_key = self._preset_key_map.get(display, "")
        new_cfg["selected_preset"] = preset_key

        # 保存输入模式
        new_cfg["input_mode"] = self._input_mode_var.get()

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

        try:
            config.save_config(new_cfg, raise_on_error=True)
        except Exception as e:
            messagebox.showerror("配置保存失败", f"配置保存失败：{e}", parent=self)
            return

        self.result = new_cfg
        self.destroy()

    def destroy(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.grab_current() == self:
                self.grab_release()
        except tk.TclError:
            pass
        try:
            super().destroy()
        except tk.TclError:
            pass
