"""
OCR 模块 —— 基于 PaddleOCR 进行本地文字识别
检测运行目录下的 models/ 文件夹，优先使用标准模型，其次轻量模型。
"""

import os
import logging
from typing import Optional

from core.config import get_models_dir

logger = logging.getLogger(__name__)

# PaddleOCR 懒加载实例（避免启动时过慢）
_ocr_instance = None
_ocr_init_attempted = False  # 避免模型不存在时每次调用都重复检测


def _detect_model_dir() -> Optional[str]:
    """
    检测 models/ 目录下是否存在标准模型或轻量模型。
    优先返回标准模型路径，其次轻量模型路径，均不存在返回 None。

    约定目录结构（用户手动放置）：
        models/
            det/      检测模型
            rec/      识别模型
            cls/      方向分类模型（可选）
        或
        models/
            det_slim/
            rec_slim/
    """
    base = get_models_dir()
    if not os.path.isdir(base):
        return None

    # 标准模型
    if os.path.isdir(os.path.join(base, "det")) and os.path.isdir(os.path.join(base, "rec")):
        return base

    # 轻量模型（slim 子目录）
    if os.path.isdir(os.path.join(base, "det_slim")) and os.path.isdir(os.path.join(base, "rec_slim")):
        return base

    return None


def _build_ocr(model_dir: str):
    """
    根据 model_dir 内的目录判断模型规格，初始化 PaddleOCR。
    """
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        logger.error("PaddleOCR 未安装，请执行 pip install paddleocr")
        return None

    base = model_dir
    use_standard = os.path.isdir(os.path.join(base, "det"))

    if use_standard:
        det_model = os.path.join(base, "det")
        rec_model = os.path.join(base, "rec")
        cls_model = os.path.join(base, "cls") if os.path.isdir(os.path.join(base, "cls")) else None
    else:
        det_model = os.path.join(base, "det_slim")
        rec_model = os.path.join(base, "rec_slim")
        cls_model = os.path.join(base, "cls_slim") if os.path.isdir(os.path.join(base, "cls_slim")) else None

    kwargs = {
        "use_angle_cls": cls_model is not None,
        "det_model_dir": det_model,
        "rec_model_dir": rec_model,
        "use_gpu": False,
        "show_log": False,
    }
    if cls_model:
        kwargs["cls_model_dir"] = cls_model

    try:
        ocr = PaddleOCR(**kwargs)
        logger.info("PaddleOCR 初始化成功（%s）", "标准模型" if use_standard else "轻量模型")
        return ocr
    except Exception as e:
        logger.error("PaddleOCR 初始化失败: %s", e)
        return None


def get_ocr():
    """
    获取 PaddleOCR 单例。首次调用时自动检测模型并初始化。
    若模型不存在或初始化失败，返回 None，且不再重复尝试初始化。
    """
    global _ocr_instance, _ocr_init_attempted
    if _ocr_init_attempted:
        return _ocr_instance

    _ocr_init_attempted = True
    model_dir = _detect_model_dir()
    if model_dir is None:
        logger.warning("未检测到 PaddleOCR 模型目录（models/），将跳过本地 OCR")
        return None

    _ocr_instance = _build_ocr(model_dir)
    return _ocr_instance


def ocr_image(img) -> str:
    """
    对 PIL Image 进行 OCR，返回识别出的全部文本（按行拼接）。
    若 OCR 不可用或识别失败，返回空字符串。

    Parameters
    ----------
    img : PIL.Image.Image
    """
    ocr = get_ocr()
    if ocr is None:
        return ""

    import numpy as np
    try:
        img_array = np.array(img.convert("RGB"))
        result = ocr.ocr(img_array, cls=True)
    except Exception as e:
        logger.error("OCR 识别异常: %s", e)
        return ""

    if not result or result[0] is None:
        return ""

    lines = []
    for line in result[0]:
        if line and len(line) >= 2:
            text_info = line[1]
            if text_info and len(text_info) >= 1:
                text = str(text_info[0]).strip()
                if text:
                    lines.append(text)

    return "\n".join(lines)


def is_ocr_available() -> bool:
    """返回 OCR 是否可用（模型存在且初始化成功）。"""
    return get_ocr() is not None
