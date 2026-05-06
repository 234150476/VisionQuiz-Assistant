"""
题库查看器 —— 分页浏览当前题库内容
"""

import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from core.db_manager import QuestionDB


class DBViewerDialog(tk.Toplevel):
    """
    题库查看对话框：分页展示题库中的题目和答案。
    """

    PAGE_SIZE = 50

    def __init__(self, parent: tk.Tk, db_path: str):
        super().__init__(parent)
        self.title(f"题库查看 - {db_path}")
        self.geometry("800x500")

        self._db_path = db_path
        self._db = None
        self._page = 1
        self._total = 0
        self._closed = False

        try:
            self._db = QuestionDB(db_path)
            self._build()
            self._load_page()
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.grab_set()
        except Exception:
            self.destroy()
            raise

    # ------------------------------------------------------------------
    # 构建界面
    # ------------------------------------------------------------------

    def _build(self):
        # 顶部信息栏
        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=6)
        self._info_label = tk.Label(top, text="", anchor="w")
        self._info_label.pack(side=tk.LEFT)

        # 表格
        cols = ("id", "question", "answer", "created_at")
        col_labels = {"id": "ID", "question": "题目", "answer": "答案", "created_at": "创建时间"}
        col_widths = {"id": 50, "question": 400, "answer": 220, "created_at": 130}

        frame = tk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)

        scrollbar_y = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        scrollbar_x = ttk.Scrollbar(frame, orient=tk.HORIZONTAL)

        self._tree = ttk.Treeview(
            frame,
            columns=cols,
            show="headings",
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
        )
        scrollbar_y.config(command=self._tree.yview)
        scrollbar_x.config(command=self._tree.xview)

        for col in cols:
            self._tree.heading(col, text=col_labels[col])
            self._tree.column(col, width=col_widths[col], minwidth=40)

        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)

        # 底部分页控件
        bottom = tk.Frame(self)
        bottom.pack(fill=tk.X, padx=10, pady=6)

        self._prev_btn = tk.Button(bottom, text="上一页", command=self._prev_page)
        self._prev_btn.pack(side=tk.LEFT, padx=4)
        self._next_btn = tk.Button(bottom, text="下一页", command=self._next_page)
        self._next_btn.pack(side=tk.LEFT, padx=4)
        self._page_label = tk.Label(bottom, text="")
        self._page_label.pack(side=tk.LEFT, padx=10)
        tk.Button(bottom, text="关闭", command=self._on_close).pack(side=tk.RIGHT, padx=4)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _load_page(self):
        try:
            rows, total = self._db.get_all(self._page, self.PAGE_SIZE)
        except sqlite3.DatabaseError as exc:
            self._handle_db_error(exc)
            return

        self._total = total
        total_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

        # 清空表格
        for item in self._tree.get_children():
            self._tree.delete(item)

        # 填充数据
        for row in rows:
            q = row["question"]
            a = row["answer"].replace("|答案分隔|", " / ")
            self._tree.insert(
                "", tk.END,
                values=(row["id"], q, a, row.get("created_at", ""))
            )

        self._info_label.config(text=f"共 {total} 条记录")
        self._page_label.config(text=f"第 {self._page} / {total_pages} 页")
        self._set_paging_enabled(True)

    # ------------------------------------------------------------------
    # 分页控制
    # ------------------------------------------------------------------

    def _prev_page(self):
        if self._page > 1:
            self._page -= 1
            self._load_page()

    def _next_page(self):
        total_pages = max(1, (self._total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if self._page < total_pages:
            self._page += 1
            self._load_page()

    def _on_close(self):
        self.destroy()

    def _handle_db_error(self, exc: Exception):
        self._set_paging_enabled(False)
        self._info_label.config(text="题库数据损坏")
        self._page_label.config(text="无法分页")
        messagebox.showerror(
            "题库数据损坏",
            f"题库数据损坏：{exc}\n请重新导入或修复题库文件。",
            parent=self,
        )

    def _set_paging_enabled(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        self._prev_btn.config(state=state)
        self._next_btn.config(state=state)

    def destroy(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.grab_current() == self:
                self.grab_release()
        except tk.TclError:
            pass
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None
        try:
            super().destroy()
        except tk.TclError:
            pass
