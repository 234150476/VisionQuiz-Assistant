"""
识别模块 —— 整合截图、OCR、题库匹配、AI 识别，输出结构化结果
"""

import logging
import hashlib
import threading
from typing import Optional

from core.screenshot import compute_phash, compute_question_hash
from core.ocr import ocr_image, is_ocr_available
from core.cache import CacheDB
from core.matcher import QuestionMatcher
from core.ai_client import AIClient, PromptAResult, PromptBResult
from core.element_provider import QuestionElement
from core.answer_normalizer import normalize_bank_answer

logger = logging.getLogger(__name__)


def _preprocess_ocr_text(raw_text: str) -> tuple:
    """预处理 OCR 文本，返回 (cleaned_text, quality)。
    quality: 'good' 或 'poor'
    """
    import re

    if not raw_text or not raw_text.strip():
        return (raw_text, 'poor')

    text = raw_text

    # 清洗规则 1: 去除连续重复字符 3+ 次 → 保留 2 次
    text = re.sub(r'(.)\1{2,}', r'\1\1', text)

    # 清洗规则 2: 去除长度 < 3 的纯噪声行（全标点或全数字）
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) < 3:
            continue  # 太短，跳过
        if all(c in '0123456789.,;:!?-+=/\\()[]{}|' for c in stripped):
            continue  # 全标点/全数字，跳过
        cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)

    # 清洗规则 3: 乱码检测 — 非中文/英文/数字/常见标点字符占比 > 30%
    if text:
        valid_chars = sum(1 for c in text if (
            '一' <= c <= '鿿' or  # 中文
            'a' <= c.lower() <= 'z' or     # 英文
            c.isdigit() or                  # 数字
            c in ' \t\n.,;:!?-+=/\\()[]{}|""\'\'【】《》（）、。，；：！？'  # 常见标点
        ))
        ratio = valid_chars / len(text)
        if ratio < 0.7:  # 有效字符 < 70% → 乱码
            return (text, 'poor')

    return (text, 'good')


class RecognizeResult:
    """
    识别结果数据类。
    """
    __slots__ = (
        "question_text",       # OCR 识别出的题目文本（可能为空）
        "answer",              # 最终答案（多选用 |答案分隔| 分隔）
        "source",              # 答案来源（旧字段，保留兼容）：'bank' | 'cache' | 'ai'
        "score",               # 题库匹配分数（0~1），非题库命中时为 None
        "question_hash",       # 题目文本 MD5
        "phash",               # 截图 pHash 字符串
        "question_type",       # 题目类型：'single'|'multi'|'judge'|'fill'|'essay'
        "options",             # 选项坐标列表（list of OptionCoord-like dicts）
        "input_targets",       # 输入框目标列表（list of InputTarget-like dicts）
        "word_limit",          # 字数限制（简答题）
        "confidence",          # 识别置信度（0~1）
        "recognition_source",  # 识别来源：'ocr'|'vision'（来自 Prompt A）
        "answer_source",       # 答案来源：'bank'|'cache'|'ai'（来自 Prompt B，新规范字段）
    )

    def __init__(self):
        self.question_text: str = ""
        self.answer: str = ""
        self.source: str = ""
        self.score: Optional[float] = None
        self.question_hash: str = ""
        self.phash: str = ""
        self.question_type: str = ""
        self.options: list = []
        self.input_targets: list = []
        self.word_limit: Optional[int] = None
        self.confidence: float = 0.0
        self.recognition_source: str = ""
        self.answer_source: str = ""

    def __repr__(self):
        return (
            f"RecognizeResult(source={self.source!r}, answer_source={self.answer_source!r}, "
            f"answer={self.answer!r}, question_type={self.question_type!r}, "
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

    def _build_result(
        self,
        *,
        answer: str,
        source: str,
        question_text: str = "",
        question_hash: str = "",
        phash: str = "",
        score: Optional[float] = None,
        question_type: str = "",
        options: Optional[list] = None,
        input_targets: Optional[list] = None,
        word_limit: Optional[int] = None,
        confidence: float = 0.0,
        recognition_source: str = "",
        answer_source: str = "",
    ) -> RecognizeResult:
        result = RecognizeResult()
        result.question_text = question_text
        result.answer = answer
        result.source = source
        result.score = score
        result.question_hash = question_hash
        result.phash = phash
        result.question_type = question_type
        result.options = options if options is not None else []
        result.input_targets = input_targets if input_targets is not None else []
        result.word_limit = word_limit
        result.confidence = confidence
        result.recognition_source = recognition_source
        result.answer_source = answer_source or source
        return result

    @staticmethod
    def _validate_answer(answer) -> str:
        if not isinstance(answer, str):
            raise ValueError("识别答案不是字符串")
        answer = answer.strip()
        if not answer:
            raise ValueError("识别答案为空")
        return answer

    def _try_phash_cache(self, img_hash: str, question_hash: str) -> Optional[RecognizeResult]:
        try:
            if not img_hash:
                return None
            cached = self._cache.get_by_phash(img_hash)
            if not cached or not cached.get("answer"):
                return None
            answer = self._validate_answer(cached["answer"])
            logger.debug("pHash 缓存命中: %s", img_hash)
            return self._build_result(
                answer=answer,
                source="cache",
                question_hash=cached.get("question_hash", "") or question_hash,
                phash=img_hash,
            )
        except Exception as exc:
            logger.warning("pHash 缓存查询失败: %s", exc)
            return None

    def _try_qhash_cache(
        self, question_hash: str, phash_str: str = ""
    ) -> Optional[RecognizeResult]:
        try:
            if not question_hash:
                return None
            cached = self._cache.get_by_question_hash(question_hash)
            if not cached or not cached.get("answer"):
                return None
            answer = self._validate_answer(cached["answer"])
            logger.debug("question_hash 缓存命中: %s", question_hash)
            if not cached.get("phash") and phash_str:
                try:
                    self._cache.update_phash(question_hash, phash_str)
                except Exception as exc:
                    logger.warning("缓存 phash 补写失败: %s", exc)
            return self._build_result(
                answer=answer,
                source="cache",
                question_hash=question_hash,
                phash=phash_str or cached.get("phash", ""),
            )
        except Exception as exc:
            logger.warning("question_hash 缓存查询失败: %s", exc)
            return None

    def _try_bank_match(
        self, ocr_text: str, question_hash: str, phash_str: str = ""
    ) -> Optional[RecognizeResult]:
        try:
            if not ocr_text.strip():
                return None
            with self._matcher_lock:
                matcher = self._matcher
            if matcher is None:
                return None
            bank_hit = matcher.find_best(ocr_text.strip(), self._threshold)
            if not bank_hit:
                return None
            answer = self._validate_answer(bank_hit["answer"])
            logger.debug("题库匹配命中: score=%.3f", bank_hit["score"])
            result = self._build_result(
                answer=answer,
                source="bank",
                question_text=ocr_text,
                question_hash=question_hash,
                phash=phash_str,
                score=bank_hit["score"],
            )
        except Exception as exc:
            logger.warning("题库匹配失败: %s", exc)
            return None

        try:
            self._cache.insert(question_hash, phash_str, result.answer, "bank")
        except Exception as exc:
            logger.warning("题库结果写缓存失败: %s", exc)
        return result

    def _try_ai_recognize(
        self,
        screenshot_img,
        ocr_text: str,
        phash_str: str = "",
        question_hash: str = "",
    ) -> Optional[RecognizeResult]:
        if self._ai is None:
            logger.warning("AI 客户端未配置，无法调用 AI")
            return None

        prompt_a_result: Optional[PromptAResult] = None
        prompt_b_result: Optional[PromptBResult] = None

        # --- Step 1: 通过 Prompt A 识别题目信息 ---
        try:
            img_input = ocr_text.strip() if ocr_text.strip() else "（OCR 不可用，请直接读取截图内容）"
            prompt_a_result = self._ai.answer_with_image(img_input, screenshot_img)
        except Exception as exc:
            logger.warning("AI 图像识别失败: %s", exc)

        # --- Step 2: 如果 Prompt A 失败，回退到 Prompt B 文本作答 ---
        if prompt_a_result is None:
            if ocr_text.strip():
                try:
                    prompt_b_result = self._ai.answer_with_text(ocr_text)
                except Exception as fallback_exc:
                    logger.warning("AI 文本回退失败: %s", fallback_exc)
                    return None
            else:
                return None

        # --- Step 3: 组装 RecognizeResult ---
        if prompt_a_result is not None:
            # Prompt A 成功：提取题目信息
            # 选项坐标转换为 dict 列表（兼容旧接口）
            options_dicts = [
                {"text": opt.text, "x": opt.x, "y": opt.y}
                for opt in prompt_a_result.options
            ]
            input_target_dicts = [
                {"placeholder": tgt.placeholder, "x": tgt.x, "y": tgt.y}
                for tgt in prompt_a_result.input_targets
            ]

            # Prompt A 仅识别题目，不含答案 → 调用 Prompt B 获取答案
            if prompt_b_result is None:
                try:
                    prompt_b_result = self._ai.answer_with_text(prompt_a_result.question or ocr_text)
                except Exception as exc:
                    logger.warning("Prompt B 答案推理失败: %s", exc)

            answer_text = prompt_b_result.answer if prompt_b_result else ""
            answer_src = prompt_b_result.answer_source if prompt_b_result else "ai"
            result = self._build_result(
                answer=answer_text,
                source="ai",
                question_text=prompt_a_result.question or ocr_text,
                question_hash=question_hash,
                phash=phash_str,
                question_type=prompt_a_result.question_type,
                options=options_dicts,
                input_targets=input_target_dicts,
                word_limit=prompt_a_result.word_limit,
                confidence=prompt_a_result.confidence,
                recognition_source=prompt_a_result.recognition_source,
                answer_source=answer_src,
            )
        else:
            # Prompt B 回退路径：如果 prompt_b_result 为空或答案为空，直接返回 None
            if not prompt_b_result or not prompt_b_result.answer.strip():
                logger.warning("Prompt A 和 Prompt B 均未给出有效答案，跳过本轮识别")
                return None
            result = self._build_result(
                answer=prompt_b_result.answer,
                source="ai",
                question_text=ocr_text,
                question_hash=question_hash,
                phash=phash_str,
                question_type="single",
                confidence=prompt_b_result.confidence,
                recognition_source="ocr",
                answer_source=prompt_b_result.answer_source,
            )

        # --- Step 4: 校验答案 ---
        if result.answer:
            try:
                result.answer = self._validate_answer(result.answer)
            except ValueError as exc:
                logger.warning("AI 返回答案校验失败: %s", exc)
                return result

        # --- Step 5: 写缓存 ---
        try:
            if result.answer and result.question_hash:
                self._cache.insert(result.question_hash, phash_str, result.answer, "ai")
            elif result.answer and phash_str:
                fallback_qhash = hashlib.md5(phash_str.encode()).hexdigest()
                self._cache.insert(fallback_qhash, phash_str, result.answer, "ai")
                result.question_hash = fallback_qhash
        except Exception as exc:
            logger.warning("AI 结果写缓存失败: %s", exc)
        return result

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
        if not phash_str:
            phash_str = compute_phash(screenshot_img)

        ocr_text = ""
        if is_ocr_available():
            ocr_text = ocr_image(screenshot_img)
            logger.debug("OCR 原始文本: %s", ocr_text[:80])

        # OCR 文本预处理（在 question_hash 计算之前）
        ocr_quality = "good"
        if ocr_text.strip():
            ocr_text, ocr_quality = _preprocess_ocr_text(ocr_text)
            logger.debug("OCR 预处理后: quality=%s, text=%s", ocr_quality, ocr_text[:80])

        question_hash = ""
        if ocr_text.strip():
            question_hash = compute_question_hash(ocr_text.strip())

        # 乱码检测结果为 poor 时，跳过题库匹配，仍走 AI 识别
        if ocr_quality == "poor":
            logger.info("OCR 文本质量较差（quality=poor），跳过题库匹配")

        strategies = [
            lambda: self._try_phash_cache(phash_str, question_hash),
            lambda: self._try_qhash_cache(question_hash, phash_str),
        ]
        if ocr_quality != "poor":
            strategies.append(
                lambda: self._try_bank_match(ocr_text, question_hash, phash_str),
            )
        strategies.append(
            lambda: self._try_ai_recognize(
                screenshot_img,
                ocr_text,
                phash_str,
                question_hash,
            ),
        )

        for strategy in strategies:
            result = strategy()
            if result is None:
                continue
            result.question_text = result.question_text or ocr_text
            result.question_hash = result.question_hash or question_hash
            result.phash = result.phash or phash_str
            if result.answer:
                # OCR 质量差时，标记识别来源为 vision_preferred
                if ocr_quality == "poor":
                    result.recognition_source = "vision_preferred"
                return result

        return None

    def recognize_from_elements(self, question_elem: QuestionElement) -> Optional[RecognizeResult]:
        """
        元素模式识别：直接从 QuestionElement 的文本进行题库匹配和 AI 文本回答。

        不调用 answer_with_image（Prompt A），仅使用 answer_with_text（Prompt B）。
        返回的 RecognizeResult.options 携带 element_ref 字段。
        """
        text = question_elem.question_text.strip()
        if not text:
            return None

        question_hash = question_elem.raw_hash or compute_question_hash(text)

        # 1. 题库匹配（复用 _try_bank_match）
        bank_result = self._try_bank_match(text, question_hash)
        if bank_result:
            bank_result.question_type = question_elem.question_type
            bank_result.options = [
                {"text": o.text, "element_ref": o.element_ref, "index": o.index}
                for o in question_elem.options
            ]
            # 归一化题库答案为选项字母
            bank_result.answer = normalize_bank_answer(
                bank_result.answer, bank_result.options, bank_result.question_type
            )
            return bank_result

        # 2. AI 文本回答（仅 Prompt B）
        if self._ai is None:
            logger.warning("AI 客户端未配置，元素模式无法回退到 AI")
            return None

        try:
            prompt_b = self._ai.answer_with_text(text)
            if prompt_b and prompt_b.answer.strip():
                result = self._build_result(
                    answer=prompt_b.answer.strip(),
                    source="ai",
                    question_text=text,
                    question_hash=question_hash,
                    question_type=question_elem.question_type or "single",
                    confidence=prompt_b.confidence,
                    recognition_source="text",
                    answer_source=prompt_b.answer_source,
                )
                result.options = [
                    {"text": o.text, "element_ref": o.element_ref, "index": o.index}
                    for o in question_elem.options
                ]
                result.input_targets = [
                    {"placeholder": t.placeholder, "element_ref": t.element_ref}
                    for t in question_elem.input_targets
                ]

                # 写缓存
                try:
                    if result.answer and result.question_hash:
                        self._cache.insert(result.question_hash, "", result.answer, "ai")
                except Exception as exc:
                    logger.warning("AI 结果写缓存失败: %s", exc)

                return result
        except Exception as exc:
            logger.warning("AI 文本回答失败: %s", exc)

        return None

    def verify_answer_clicked(self, before_img, after_img, expected_answer: str) -> bool:
        """
        点击后验证：调用 AI 判断目标答案是否已被选中。
        若 AI 不可用，默认返回 True（乐观策略）。
        """
        if self._ai is None:
            return True
        try:
            result = self._ai.verify_click(before_img, after_img, expected_answer)
            # verify_click 现在返回 PromptCResult
            if hasattr(result, "confirmed"):
                return bool(result.confirmed)
            return bool(result)
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
