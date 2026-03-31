"""
程序入口
"""

import logging
import sys
import os

# 确保运行目录在 sys.path（开发模式下直接 python main.py）
_base = os.path.dirname(os.path.abspath(__file__))
if _base not in sys.path:
    sys.path.insert(0, _base)


def _setup_logging():
    """配置日志：输出到控制台，打包后静默。"""
    level = logging.DEBUG if not getattr(sys, "frozen", False) else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    _setup_logging()

    from ui.main_window import MainWindow
    app = MainWindow()
    app.run()


if __name__ == "__main__":
    main()
