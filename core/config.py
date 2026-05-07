"""
配置管理模块
"""

import os
import sys
import json
import logging
import base64
import ctypes
import ctypes.wintypes
from typing import Optional

logger = logging.getLogger(__name__)

_LAST_LOAD_WAS_CORRUPT = False

MODEL_PRESETS = {
    "openai": {
        "display_name": "OpenAI GPT-4o",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "openai_4o_mini": {
        "display_name": "OpenAI GPT-4o-mini",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "claude_sonnet": {
        "display_name": "Claude 3.5 Sonnet",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-5-sonnet-20241022",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "claude_opus": {
        "display_name": "Claude 3 Opus",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-opus-20240229",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "gemini_15_pro": {
        "display_name": "Gemini 1.5 Pro",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-1.5-pro",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "gemini_15_flash": {
        "display_name": "Gemini 1.5 Flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-1.5-flash",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "gemini_20_flash": {
        "display_name": "Gemini 2.0 Flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.0-flash",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "qwen_vl_max": {
        "display_name": "通义千问 Qwen-VL-Max",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "qwen_vl_plus": {
        "display_name": "通义千问 Qwen-VL-Plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-plus",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "glm_4v": {
        "display_name": "智谱 GLM-4V",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4v",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "step_1v": {
        "display_name": "阶跃星辰 Step-1V",
        "base_url": "https://api.stepfun.com/v1",
        "model": "step-1v-32k",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "doubao_vision": {
        "display_name": "豆包 Doubao-Vision",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-vision-pro-32k",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": None,
    },
    "mimo_v25": {
        "display_name": "MiMo-V2.5 (视觉)",
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": {"thinking": {"type": "disabled"}},
    },
    "mimo_v25_pro": {
        "display_name": "MiMo-V2.5-Pro (文本)",
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5-pro",
        "supports_vision": False,
        "image_transport": "inline_base64",
        "extra_body": {"thinking": {"type": "disabled"}},
    },
    "mimo_v2_omni": {
        "display_name": "MiMo-V2-Omni (全模态)",
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2-omni",
        "supports_vision": True,
        "image_transport": "inline_base64",
        "extra_body": {"thinking": {"type": "disabled"}},
    },
}

CONFIG_DEFAULTS = {
    "api_key": "",
    "api_base_url": "https://api.openai.com/v1",
    "model": "",
    "timeout": 30,
    "similarity_threshold": 0.55,
    "cache_expire_days": 7,
    "screenshot_interval": 2,
    "hud_opacity": 0.85,
    "hud_top_offset": 20,
    "selected_preset": "",
    "phash_threshold": 8,
    "recognition_timeout": 45,
    "auto_mark_timeout": 10,
    # P7: ElementProvider 模式配置
    "input_mode": "screenshot",       # screenshot | browser | windows
    "browser_debug_port": 9222,       # Chrome CDP 调试端口
    "browser_selector_config": "",    # 外部 JSON 选择器配置文件路径（可选）
    "windows_target_title": "",       # 目标窗口标题（模糊匹配）
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


def was_last_load_corrupt() -> bool:
    """返回最近一次 load_config 是否遇到损坏/不可读配置。"""
    return _LAST_LOAD_WAS_CORRUPT


# ---------------------------------------------------------------------------
# DPAPI 加解密
# ---------------------------------------------------------------------------

_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                 ("pbData", ctypes.POINTER(ctypes.c_char))]


_CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _encrypt_dpapi(plaintext: str) -> str:
    """使用 Windows DPAPI 加密字符串，返回 'DPAPI:' + base64 编码的密文。"""
    data_in = plaintext.encode("utf-8")
    blob_in = DATA_BLOB(len(data_in),
                        ctypes.create_string_buffer(data_in, len(data_in)))
    blob_out = DATA_BLOB()

    if not _crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(blob_out.pbData)

    return "DPAPI:" + base64.b64encode(encrypted).decode("ascii")


def _decrypt_dpapi(encrypted: str) -> str:
    """解密 DPAPI 加密的字符串。检测 'DPAPI:' 前缀。"""
    raw = base64.b64decode(encrypted[len("DPAPI:"):])
    blob_in = DATA_BLOB(len(raw),
                        ctypes.create_string_buffer(raw, len(raw)))
    blob_out = DATA_BLOB()

    if not _crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8")
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def load_config() -> dict:
    """
    读取 config.json。
    - 文件不存在则使用默认值创建；
    - 字段缺失自动补全；
    - 返回完整 dict。
    """
    global _LAST_LOAD_WAS_CORRUPT
    config_path = _get_config_path()
    cfg = {}
    _LAST_LOAD_WAS_CORRUPT = False

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except json.JSONDecodeError as exc:
            logger.warning("配置文件已损坏，已回退默认配置: %s", exc)
            _LAST_LOAD_WAS_CORRUPT = True
            cfg = {}
        except OSError as exc:
            logger.warning("读取配置文件失败，已回退默认配置: %s", exc)
            _LAST_LOAD_WAS_CORRUPT = True
            cfg = {}

    # 补全缺失字段
    updated = False
    for key, default_value in CONFIG_DEFAULTS.items():
        if key not in cfg:
            cfg[key] = default_value
            updated = True

    # 预设解析：selected_preset 非空时用预设值填充 api_base_url/model
    preset_key = cfg.get("selected_preset", "")
    if preset_key and preset_key in MODEL_PRESETS:
        preset = MODEL_PRESETS[preset_key]
        if not cfg.get("api_base_url"):
            cfg["api_base_url"] = preset["base_url"]
        if not cfg.get("model"):
            cfg["model"] = preset["model"]
        updated = True

    # DPAPI 透明迁移：旧明文 api_key → 加密后重新保存
    api_key = cfg.get("api_key", "")
    if api_key and not api_key.startswith("DPAPI:"):
        try:
            cfg["api_key"] = _encrypt_dpapi(api_key)
            updated = True
        except Exception as exc:
            logger.warning("DPAPI 加密 api_key 失败，保留明文: %s", exc)

    # 如果有补全或文件不存在，写回磁盘
    if updated or not os.path.exists(config_path):
        save_config(cfg)

    # 返回前解密 api_key，供调用方使用明文
    stored_key = cfg.get("api_key", "")
    if stored_key.startswith("DPAPI:"):
        try:
            cfg["api_key"] = _decrypt_dpapi(stored_key)
        except Exception as exc:
            logger.warning("DPAPI 解密 api_key 失败，返回空: %s", exc)
            cfg["api_key"] = ""

    return cfg


def save_config(cfg: dict, raise_on_error: bool = False) -> bool:
    """将配置写入 config.json。写入失败时记录日志，可选抛出异常。"""
    config_path = _get_config_path()

    # 写入前加密 api_key（如果尚未加密）
    write_cfg = dict(cfg)
    api_key = write_cfg.get("api_key", "")
    if api_key and not api_key.startswith("DPAPI:"):
        try:
            write_cfg["api_key"] = _encrypt_dpapi(api_key)
        except Exception as exc:
            logger.warning("DPAPI 加密 api_key 失败，以明文写入: %s", exc)

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(write_cfg, f, ensure_ascii=False, indent=4)
        return True
    except OSError as exc:
        logger.warning("写入配置文件失败: %s", exc)
        if raise_on_error:
            raise
        return False


def get_preset_catalog() -> dict:
    """返回预设目录的深拷贝，供 UI 导入。"""
    return {k: dict(v) for k, v in MODEL_PRESETS.items()}


def get_active_preset(cfg: dict) -> Optional[dict]:
    """返回当前选中预设的 metadata dict，无选中时返回 None。"""
    preset_key = cfg.get("selected_preset", "")
    if preset_key and preset_key in MODEL_PRESETS:
        return dict(MODEL_PRESETS[preset_key])
    return None


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
