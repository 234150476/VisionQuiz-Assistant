"""
识别模块 —— 整合截图、OCR、题库匹配、AI 识别，输出结构化结果
"""

import logging
import threading
from typing import Optional

from core.screenshot import compute_phash, compute_question_hash
from core.ocr import ocr_image, is_ocr_available
from core.cache import CacheDB
from core.matcher import QuestionMatcher
from core.ai_client import AIClient

logger = logging.getLogger(__name__)


class RecognizeResult:
    """
    识别结果数据类。
    """
    __slots__ = (
        "question_text",   # OCR 识别出的题目文本（可能为空）
        "answer",          # 最终答案（多选用 |答案分隔| 分隔）
        "source",          # 答案来源：'bank' | 'cache' | 'ai'
        "score",           # 题库匹配分数（0~1），非题库命中时为 None
        "question_hash",   # 题目文本 MD5
        "phash",           # 截图 pHash 字符串
    )

    def __init__(self):
        self.question_text: str = ""
        self.answer: str = ""
        self.source: str = ""
        self.score: Optional[float] = None
        self.question_hash: str = ""
        self.phash: str = ""

    def __repr__(self):
        return (
            f"RecognizeResult(source={self.source!r}, answer={self.answer!r}, "
            f"score={self.score}, question={self.question_text[:30]!r})"
        )


class Recognizer:
    """
    识别器：整合多路识别策略。

    识别优先级：
    1. pHash 命中缓存（截图级去重，免 AI 调用）
    2. 题库模糊匹配（OCR 文本 vs 题库，threshold 可配）
    3. AI 识别（OCR 文本 + 截图双路输入）

    命中后写缓存，结果统一通过 RecognizeResult 返回。
    """

    def __init__(
        self,
        cache: CacheDB,
        matcher: Optional[QuestionMatcher],
        ai_client: Optional[AIClient],
        similarity_threshold: float = 0.8,
    ):
        self._cache = cache
        self._matcher = matcher
        self._matcher_lock = threading.Lock()
        self._ai = ai_client
        self._threshold = similarity_threshold

    def set_matcher(self, matcher: Optional[QuestionMatcher]) -> None:
        """线程安全地替换题库匹配器（供 engine.switch_db 调用）。"""
        with self._matcher_lock:
            self._matcher = matcher

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def recognize(self, screenshot_img, phash_str: str = "") -> Optional[RecognizeResult]:
        """
        对当前截图进行识别，返回 RecognizeResult 或 None（全部策略失败）。

        Parameters
        ----------
        screenshot_img : PIL.Image.Image  当前全屏截图
        phash_str      : str              已计算好的 pHash（避免重复计算），若为空则内部计算
        """
        result = RecognizeResult()

        # 1. pHash（优先使用传入值，避免引擎层和识别层双重计算）
        if not phash_str:
            phash_str = compute_phash(screenshot_img)
        result.phash = phash_str

        # 2. pHash 命中缓存？
        cached = self._cache.get_by_phash(phash_str)
        if cached and cached.get("answer"):
            logger.debug("pHash 缓存命中: %s", phash_str)
            result.answer = cached["answer"]
            result.source = "cache"
            result.question_hash = cached.get("question_hash", "")
            return result

        # 3. OCR 识别文本
        ocr_text = ""
        if is_ocr_available():
            ocr_text = ocr_image(screenshot_img)
            logger.debug("OCR 文本: %s", ocr_text[:80])

        result.question_text = ocr_text

        # 4. question_hash（基于 OCR 文本）
        if ocr_text.strip():
            qhash = compute_question_hash(ocr_text.strip())
            result.question_hash = qhash

            # 5. question_hash 命中缓存？
            cached_by_text = self._cache.get_by_question_hash(qhash)
            if cached_by_text and cached_by_text.get("answer"):
                logger.debug("question_hash 缓存命中: %s", qhash)
                result.answer = cached_by_text["answer"]
                result.source = "cache"
                # 补写 phash 绑定（若缓存记录尚无 phash，更新缓存以加速下次识别）
                if not cached_by_text.get("phash") and phash_str:
                    self._cache.insert(qhash, phash_str, result.answer, cached_by_text.get("source", "cache"))
                return result

            # 6. 题库模糊匹配
            with self._matcher_lock:
                matcher = self._matcher
            if matcher is not None:
                bank_hit = matcher.find_best(ocr_text.strip(), self._threshold)
                if bank_hit:
                    logger.debug("题库匹配命中: score=%.3f", bank_hit["score"])
                    result.answer = bank_hit["answer"]
                    result.source = "bank"
                    result.score = bank_hit["score"]
                    # 写缓存
                    self._cache.insert(qhash, phash_str, result.answer, "bank")
                    return result

        # 7. AI 识别
        if self._ai is None:
            logger.warning("AI 客户端未配置，无法调用 AI")
            return None

        try:
            if is_ocr_available() and ocr_text.strip():
                # 图文双路
                answer = self._ai.answer_with_image(ocr_text, screenshot_img)
            else:
                # 纯图（OCR 不可用时，截图交给 AI 直接读取）
                answer = self._ai.answer_with_image("（OCR 不可用，请直接读取截图内容）", screenshot_img)
        except Exception as e:
            logger.error("AI 识别失败: %s", e)
            return None

        if not answer:
            return None

        result.answer = answer
        result.source = "ai"

        # 写缓存：仅当有有效的 question_hash 时才能正确存储
        # OCR 不可用时不写缓存（无法用 answer 文本做 question_hash，否则不同题目可能碰撞）
        if result.question_hash:
            self._cache.insert(result.question_hash, phash_str, answer, "ai")
        elif phash_str:
            # 无文本 hash 但有 phash：用 phash 字符串本身的 MD5 做 question_hash（唯一性有保证）
            import hashlib
            fallback_qhash = hashlib.md5(phash_str.encode()).hexdigest()
            self._cache.insert(fallback_qhash, phash_str, answer, "ai")
            result.question_hash = fallback_qhash

        return result

    def verify_answer_clicked(self, before_img, after_img, expected_answer: str) -> bool:
        """
        点击后验证：调用 AI 判断目标答案是否已被选中。
        若 AI 不可用，默认返回 True（乐观策略）。
        """
        if self._ai is None:
            return True
        try:
            return self._ai.verify_click(before_img, after_img, expected_answer)
        except Exception as e:
            logger.error("点击验证失败: %s", e)
            return True

    def locate_option_coord(self, screenshot_img, answer: str):
        """
        调用 AI 在截图中定位选项坐标。
        返回 (x, y) 相对截图坐标，或 None。
        """
        if self._ai is None:
            return None
        try:
            return self._ai.locate_option(screenshot_img, answer)
        except Exception as e:
            logger.error("AI 定位选项失败: %s", e)
            return None
