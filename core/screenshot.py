"""
截图模块 —— 全屏截图、pHash 计算、鼠标遮盖
"""

import hashlib
import logging

import mss
from PIL import Image, ImageDraw
import imagehash

logger = logging.getLogger(__name__)

def capture_screen() -> Image.Image | None:
    """
    全屏截图，返回 PIL Image（RGB 模式）。
    使用 mss 多屏兼容，始终截取主显示器。
    """
    try:
        with mss.mss() as sct:
            # monitor[1] 为主显示器；monitor[0] 是所有屏幕的合并区域
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return img
    except mss.exception.ScreenShotError as exc:
        logger.warning("截图失败，跳过本轮: %s", exc)
        return None
    except Exception as exc:
        logger.warning("截图异常，跳过本轮: %s", exc)
        return None


def _get_cursor_pos() -> tuple[int, int]:
    """获取当前鼠标光标的屏幕坐标（x, y）。"""
    try:
        import pyautogui
        x, y = pyautogui.position()
        return int(x), int(y)
    except Exception:
        return 0, 0


def blackout_cursor(img: Image.Image, cursor_size: int = 32) -> Image.Image:
    """
    在图像上将鼠标光标区域涂黑（32×32 像素）。
    确保 pHash 计算不受鼠标位置影响。
    返回修改后的新 Image 对象（不修改原图）。
    """
    try:
        img_copy = img.copy()
        x, y = _get_cursor_pos()
        half = cursor_size // 2
        x0 = max(0, x - half)
        y0 = max(0, y - half)
        x1 = min(img_copy.width, x + half)
        y1 = min(img_copy.height, y + half)
        draw = ImageDraw.Draw(img_copy)
        draw.rectangle([x0, y0, x1, y1], fill=(0, 0, 0))
        return img_copy
    except Exception:
        return img


def compute_phash(img: Image.Image) -> str:
    """
    计算图像的 pHash 字符串（16 进制，64 位）。
    在计算前先遮盖鼠标光标区域。
    """
    try:
        img_clean = blackout_cursor(img)
        h = imagehash.phash(img_clean)
        return str(h)
    except Exception as exc:
        logger.warning("pHash 计算失败，跳过本轮去重: %s", exc)
        return ""


def compute_question_hash(text: str) -> str:
    """
    对题目文本计算 MD5，用作缓存 key（question_hash）。
    """
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def crop_region(img: Image.Image, region: dict) -> Image.Image:
    """
    从截图中裁剪指定区域。
    region: {"left": x, "top": y, "width": w, "height": h}
    """
    x = region["left"]
    y = region["top"]
    w = region["width"]
    h = region["height"]
    return img.crop((x, y, x + w, y + h))


def image_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    """将 PIL Image 转换为字节串（用于 base64 编码后传给 AI）。"""
    import io
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def image_to_base64(img: Image.Image) -> str:
    """将 PIL Image 编码为 base64 字符串（data:image/png;base64,…）。"""
    import base64
    data = image_to_bytes(img)
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:image/png;base64,{b64}"
