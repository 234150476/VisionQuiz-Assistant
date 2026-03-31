"""
配置管理模块
"""

import os
import sys
import json

CONFIG_DEFAULTS = {
    "provider": "openai",
    "api_key": "",
    "api_base_url": "https://api.openai.com/v1",
    "model": "",
    "timeout": 30,
    "similarity_threshold": 0.8,
    "cache_expire_days": 7,
    "screenshot_interval": 2,
    "hud_opacity": 0.85,
    "hud_top_offset": 20,
}


def get_base_dir() -> str:
    """
    返回程序运行目录，兼容 PyInstaller 打包后的路径。
    打包后 sys.frozen 为 True，使用 sys.executable 所在目录；
    否则使用当前工作目录。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # 开发模式：使用 main.py / config.py 所在项目根目录，而非调用时的工作目录
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_config_path() -> str:
    return os.path.join(get_base_dir(), "config.json")


def load_config() -> dict:
    """
    读取 config.json。
    - 文件不存在则使用默认值创建；
    - 字段缺失自动补全；
    - 返回完整 dict。
    """
    config_path = _get_config_path()
    cfg = {}

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            cfg = {}

    # 补全缺失字段
    updated = False
    for key, default_value in CONFIG_DEFAULTS.items():
        if key not in cfg:
            cfg[key] = default_value
            updated = True

    # 如果有补全或文件不存在，写回磁盘
    if updated or not os.path.exists(config_path):
        save_config(cfg)

    return cfg


def save_config(cfg: dict) -> None:
    """将配置写入 config.json。写入失败时静默记录，不崩溃程序。"""
    config_path = _get_config_path()
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except OSError:
        pass


def get_db_dir() -> str:
    """
    返回 db/ 子目录的绝对路径。
    目录不存在时自动创建。
    """
    db_dir = os.path.join(get_base_dir(), "db")
    os.makedirs(db_dir, exist_ok=True)
    return db_dir


def get_models_dir() -> str:
    """返回 models/ 子目录的绝对路径（不自动创建）。"""
    return os.path.join(get_base_dir(), "models")


def get_cache_db_path() -> str:
    """返回 cache.db 的绝对路径（位于 db/ 子目录下）。"""
    return os.path.join(get_db_dir(), "cache.db")


def is_config_complete(cfg: dict) -> bool:
    """
    检查配置是否完整。
    api_key 和 model 均非空时返回 True，否则返回 False。
    """
    return bool(cfg.get("api_key", "").strip()) and bool(cfg.get("model", "").strip())
