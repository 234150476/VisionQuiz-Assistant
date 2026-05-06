"""
AI 客户端模块 —— 封装 OpenAI SDK 调用（兼容 OpenAI / Claude / 本地模型）
"""

import logging
import base64
import io
import json
import random
import re
import threading
import time
from dataclasses import dataclass, field
from numbers import Real
from typing import Optional

from openai import OpenAI

try:
    from openai import APIConnectionError, APITimeoutError, APIStatusError
except ImportError:  # pragma: no cover - 兼容旧版本 SDK
    APIConnectionError = ConnectionError
    APITimeoutError = TimeoutError

    class APIStatusError(Exception):
        status_code = None

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Typed payload dataclasses (JSON prompt 合同)
# ------------------------------------------------------------------

@dataclass
class OptionCoord:
    """选项坐标"""
    text: str
    x: int
    y: int


@dataclass
class InputTarget:
    """输入框目标（填空/简答题）"""
    placeholder: str
    x: int
    y: int


@dataclass
class PromptAResult:
    """Prompt A 识别结果"""
    question_type: str  # 'single'|'multi'|'judge'|'fill'|'essay'
    question: str
    options: list = field(default_factory=list)  # list[OptionCoord]
    input_targets: list = field(default_factory=list)  # list[InputTarget]
    word_limit: Optional[int] = None
    recognition_source: str = 'vision'  # 'ocr'|'vision'
    confidence: float = 0.0


@dataclass
class PromptBResult:
    """Prompt B 答案结果"""
    answer: str
    answer_source: str = 'ai'  # 'bank'|'cache'|'ai'
    confidence: float = 0.0


@dataclass
class PromptCResult:
    """Prompt C 验证结果"""
    confirmed: bool = False
    confidence: float = 0.0


@dataclass
class ProviderProfile:
    """Provider capability profile — centralizes model-specific differences."""
    base_url: str = ""
    model: str = ""
    supports_vision: bool = True
    image_transport: str = "inline_base64"  # "inline_base64" | "public_url"
    extra_headers: Optional[dict] = None
    extra_body: Optional[dict] = None


class AIClient:
    """
    封装 AI 模型调用。
    支持：
    - 纯文字问答（题目文本 → 答案）
    - 图文混合问答（题目文本 + 截图 → 答案）
    - 点击验证（点击后截图 → AI 判断是否已选中）
    """

    def __init__(self, api_key: str, api_base_url: str, model: str, timeout: int = 30, profile: Optional[ProviderProfile] = None):
        self._profile = profile or ProviderProfile(base_url=api_base_url, model=model)
        self.model = self._profile.model or model
        self.timeout = timeout
        self._closed = False
        self._retry_budget = 30.0
        self._lock = threading.Lock()
        self._client = OpenAI(
            api_key=api_key,
            base_url=api_base_url,
            timeout=float(timeout),
        )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _image_to_b64(img) -> str:
        """PIL Image → base64 data URI。"""
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    def _encode_image(self, img) -> dict:
        """Encode image according to profile.image_transport strategy."""
        if self._profile.image_transport == "inline_base64":
            return {"type": "image_url", "image_url": {"url": self._image_to_b64(img)}}
        elif self._profile.image_transport == "public_url":
            raise NotImplementedError("public_url image transport not yet implemented")
        else:
            raise ValueError(f"Unknown image_transport: {self._profile.image_transport}")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("AIClient is closed")

    def _is_retryable(self, exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError, APITimeoutError, APIConnectionError)):
            return True
        if isinstance(exc, APIStatusError):
            return getattr(exc, "status_code", None) in (429, 502, 503, 504)
        return False

    def _sleep_with_close_check(self, delay: float) -> None:
        end_time = time.monotonic() + max(0.0, delay)
        while time.monotonic() < end_time:
            self._ensure_open()
            time.sleep(min(0.1, end_time - time.monotonic()))

    def _chat_once(self, messages: list, temperature: float = 0.0) -> str:
        extra = {}
        if self._profile.extra_body:
            extra.update(self._profile.extra_body)
        if self._profile.extra_headers:
            extra["extra_headers"] = self._profile.extra_headers
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            **extra,
        )
        if not resp.choices:
            raise ValueError("AI 返回空 choices（可能被内容过滤）")
        content = resp.choices[0].message.content
        if content is None:
            raise ValueError("AI 返回 content 为 None（非文本响应）")
        return content.strip()

    def _chat_with_retry(self, messages: list, **kwargs) -> str:
        base_delay = 1.0
        max_delay = 8.0
        max_retries = 3
        started_at = time.monotonic()
        last_exc: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            self._ensure_open()
            try:
                return self._chat_once(messages, **kwargs)
            except Exception as exc:
                last_exc = exc
                if not self._is_retryable(exc) or attempt >= max_retries:
                    raise

                elapsed = time.monotonic() - started_at
                if elapsed >= self._retry_budget:
                    break

                delay = min(base_delay * (2 ** attempt), max_delay)
                delay += random.uniform(0.0, 0.5)
                remaining = self._retry_budget - elapsed
                if remaining <= 0:
                    break
                delay = min(delay, remaining)
                logger.warning(
                    "AI 请求失败，将进行重试: attempt=%d delay=%.2fs error=%s",
                    attempt + 1,
                    delay,
                    exc,
                )
                self._sleep_with_close_check(delay)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("AI 请求失败：未知重试状态")

    def _chat(self, messages: list, temperature: float = 0.0) -> str:
        """
        发送 chat 请求，返回 assistant 回复内容字符串。
        出错时抛出异常（由调用方处理）。
        """
        return self._chat_with_retry(messages, temperature=temperature)

    @staticmethod
    def _validate_answer_text(answer: str) -> str:
        if not isinstance(answer, str):
            raise ValueError("AI 返回答案不是字符串")
        answer = answer.strip()
        if not answer:
            raise ValueError("AI 返回空答案")
        return answer

    @staticmethod
    def _validate_click_result(click_result: bool) -> bool:
        if not isinstance(click_result, bool):
            raise ValueError("点击验证返回值不是 bool")
        return click_result

    @staticmethod
    def _validate_coords(coords):
        if coords is None:
            return None
        if not isinstance(coords, tuple) or len(coords) != 2:
            raise ValueError("AI 返回坐标格式非法")
        if not all(isinstance(value, Real) for value in coords):
            raise ValueError("AI 返回坐标类型非法")
        return coords

    # ------------------------------------------------------------------
    # JSON 解析辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """剥离 MiMo 等模型输出的 thinking/reasoning 块。"""
        stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        stripped = re.sub(r"<reasoning>.*?</reasoning>", "", stripped, flags=re.DOTALL)
        return stripped.strip()

    @staticmethod
    def _extract_json(text: str) -> dict:
        """
        从 AI 回复中提取 JSON 对象。
        先剥离 thinking 块，再尝试整体解析，然后提取 ```json ... ``` 代码块，最后用正则匹配首尾花括号。
        """
        text = AIClient._strip_thinking(text)
        # 1. 直接解析
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        # 2. 提取 ```json ... ``` 代码块
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                pass
        # 3. 正则匹配第一个 { ... }
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                pass
        raise ValueError(f"AI 返回内容中未找到有效 JSON: {text[:200]}")

    @staticmethod
    def _parse_prompt_a(raw: dict) -> PromptAResult:
        """将原始 JSON 字典解析为 PromptAResult，字段缺失时使用默认值。"""
        question_type = raw.get("question_type") or raw.get("type") or "single"
        question = raw.get("question", "")
        recognition_source = raw.get("recognition_source") or raw.get("source") or "vision"
        confidence = float(raw.get("confidence", 0.0))
        word_limit = raw.get("word_limit")
        if word_limit is not None:
            try:
                word_limit = int(word_limit)
            except (ValueError, TypeError):
                word_limit = None

        options = []
        for opt in raw.get("options", []):
            if isinstance(opt, dict):
                text = opt.get("text", "")
                x = int(opt.get("x", 0))
                y = int(opt.get("y", 0))
                options.append(OptionCoord(text=text, x=x, y=y))

        input_targets = []
        for tgt in raw.get("input_targets", []):
            if isinstance(tgt, dict):
                placeholder = tgt.get("placeholder", "")
                x = int(tgt.get("x", 0))
                y = int(tgt.get("y", 0))
                input_targets.append(InputTarget(placeholder=placeholder, x=x, y=y))

        return PromptAResult(
            question_type=question_type,
            question=question,
            options=options,
            input_targets=input_targets,
            word_limit=word_limit,
            recognition_source=recognition_source,
            confidence=confidence,
        )

    @staticmethod
    def _parse_prompt_b(raw: dict) -> PromptBResult:
        """将原始 JSON 字典解析为 PromptBResult。"""
        answer = raw.get("answer", "")
        answer_source = raw.get("answer_source", "ai")
        confidence = float(raw.get("confidence", 0.0))
        return PromptBResult(answer=answer, answer_source=answer_source, confidence=confidence)

    @staticmethod
    def _parse_prompt_c(raw: dict) -> PromptCResult:
        """将原始 JSON 字典解析为 PromptCResult。"""
        confirmed = bool(raw.get("confirmed", False))
        confidence = float(raw.get("confidence", 0.0))
        return PromptCResult(confirmed=confirmed, confidence=confidence)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            client = self._client
            self._client = None
        if client is not None and hasattr(client, "close"):
            client.close()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def answer_with_text(self, ocr_text: str) -> PromptBResult:
        """
        仅凭 OCR 文本作答。
        返回 PromptBResult；多选题各选项以 |答案分隔| 连接。
        """
        system_prompt = (
            "You are an enterprise training exam assistant.\n"
            "Based on the question text provided by the user, give the answer directly.\n"
            "Rules:\n"
            "1. Single-choice: answer with option letter only (e.g. A)\n"
            "2. Multiple-choice: list all correct option letters joined by |答案分隔| (e.g. A|答案分隔|C)\n"
            "3. True/False: answer 正确 or 错误\n"
            "4. Short answer: answer concisely, adjust length to the question\n"
            "5. Output ONLY valid JSON, no extra text\n\n"
            "Return strict JSON:\n"
            '{"answer": "answer text here", "answer_source": "ai", "confidence": 0.9}\n\n'
            "answer_source should always be 'ai' for this call."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"题目：\n{ocr_text}"},
        ]
        self._ensure_open()
        raw_text = self._chat(messages)
        try:
            raw = self._extract_json(raw_text)
            result = self._parse_prompt_b(raw)
            if not result.answer:
                raise ValueError("AI 返回空答案")
            return result
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Prompt B JSON 解析失败，回退到文本解析: %s", e)
            fallback_answer = self._validate_answer_text(raw_text)
            return PromptBResult(answer=fallback_answer, answer_source="ai", confidence=0.0)

    def answer_with_image(self, ocr_text: str, screenshot_img) -> PromptAResult:
        """
        结合 OCR 文本和屏幕截图共同识别题目。
        AI 自主决策以哪个来源为准。
        返回 PromptAResult（含题目类型、题干、选项坐标等）。
        """
        system_prompt = (
            "You are an exam question recognition assistant.\n"
            "The user will provide an OCR text result and a screenshot of the exam interface.\n"
            "Analyze the screenshot and complete these tasks:\n"
            "1. Determine if OCR is accurate (if garbled/chaotic, prefer screenshot)\n"
            "2. Identify question type: single/multi/judge/fill/essay\n"
            "3. Extract the question text\n"
            "4. Extract all option texts with their center coordinates in the screenshot "
            "(relative to screenshot width/height as 0~1 float ratios)\n"
            "5. For fill/essay questions, extract input target positions\n"
            "6. If there is a word limit, extract it\n\n"
            "Output ONLY valid JSON, no extra text.\n"
            "Return strict JSON:\n"
            '{\n'
            '  "question_type": "single|multi|judge|fill|essay",\n'
            '  "question": "question text here",\n'
            '  "options": [{"text": "option A text", "x": 100, "y": 200}],\n'
            '  "input_targets": [{"placeholder": "enter answer", "x": 150, "y": 300}],\n'
            '  "word_limit": null,\n'
            '  "recognition_source": "ocr|vision",\n'
            '  "confidence": 0.95\n'
            '}\n\n'
            "For options and input_targets, x and y should be pixel coordinates relative to the screenshot top-left corner. "
            "recognition_source: 'ocr' if OCR text was used as primary, 'vision' if screenshot was primary."
        )
        img_content = self._encode_image(screenshot_img)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"OCR 识别文本：\n{ocr_text}\n\n请结合以下截图识别题目信息：",
                    },
                    img_content,
                ],
            },
        ]
        self._ensure_open()
        raw_text = self._chat(messages)
        try:
            raw = self._extract_json(raw_text)
            result = self._parse_prompt_a(raw)
            if not result.question:
                raise ValueError("AI 返回空题目")
            return result
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Prompt A JSON 解析失败，回退到文本解析: %s", e)
            # Fallback: 尝试将原始文本作为旧式答案字符串，构造默认 PromptAResult
            fallback_answer = raw_text.strip()
            return PromptAResult(
                question_type="single",
                question=ocr_text or "",
                options=[],
                input_targets=[],
                word_limit=None,
                recognition_source="vision",
                confidence=0.0,
            )

    def verify_click(self, before_img, after_img, expected_answer: str) -> PromptCResult:
        """
        点击后验证：将点击前后两张截图发给 AI，判断是否已成功选中目标答案。
        返回 PromptCResult（含 confirmed 和 confidence）。
        """
        system_prompt = (
            "You are a UI interaction verification assistant.\n"
            "The user will provide before and after screenshots of a click action,\n"
            "and the expected answer that should have been selected.\n"
            "Determine whether the expected answer is selected (highlighted, checked,\n"
            "radio filled, or any visual selection change) in the after screenshot.\n"
            "Output ONLY valid JSON, no extra text.\n"
            "Return strict JSON:\n"
            '{"confirmed": true, "confidence": 0.95}\n'
            "Set confirmed=true if the answer is selected, false otherwise."
        )
        before_content = self._encode_image(before_img)
        after_content = self._encode_image(after_img)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"期望选中的答案：{expected_answer}\n\n点击前截图："},
                    before_content,
                    {"type": "text", "text": "点击后截图："},
                    after_content,
                ],
            },
        ]
        self._ensure_open()
        try:
            raw_text = self._chat(messages)
            try:
                raw = self._extract_json(raw_text)
                return self._parse_prompt_c(raw)
            except (ValueError, json.JSONDecodeError) as e:
                logger.warning("Prompt C JSON 解析失败，回退到文本解析: %s", e)
                click_result = "已选中" in raw_text or "confirmed" in raw_text.lower()
                return PromptCResult(confirmed=click_result, confidence=0.0)
        except Exception as e:
            logger.error("点击验证 AI 调用失败: %s", e)
            return PromptCResult(confirmed=False, confidence=0.0)

    # DEPRECATED: Use PromptAResult.options instead
    def locate_option(self, screenshot_img, answer: str) -> Optional[tuple[int, int]]:
        """
        [DEPRECATED] 让 AI 在截图中定位指定选项的坐标（相对于截图左上角）。
        新代码请使用 answer_with_image() 返回的 PromptAResult.options。
        answer: 选项文本（如 "A" 或 "正确"）
        返回 (x, y) 坐标，失败返回 None。
        """
        system_prompt = (
            "你是一个界面元素定位助手。\n"
            "用户会提供一张答题界面截图和需要点击的答案选项。\n"
            "请在截图中找到该选项的可点击区域（选项文字或选项按钮），\n"
            "返回其中心点坐标，格式为：x,y（整数，相对于截图左上角，单位像素）。\n"
            "若找不到目标选项，返回：NOT_FOUND\n"
            "只输出坐标或 NOT_FOUND，不要其他内容。"
        )
        img_content = self._encode_image(screenshot_img)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"需要点击的答案选项：{answer}\n截图："},
                    img_content,
                ],
            },
        ]
        self._ensure_open()
        try:
            result = self._chat(messages).strip()
            if result == "NOT_FOUND" or "NOT_FOUND" in result:
                return None
            # 解析 "x,y"
            parts = result.replace("，", ",").split(",")
            if len(parts) >= 2:
                x = int(parts[0].strip())
                y = int(parts[1].strip())
                # 范围校验：坐标必须在截图范围内
                img_w, img_h = screenshot_img.size
                if 0 <= x < img_w and 0 <= y < img_h:
                    return self._validate_coords((x, y))
                logger.warning("AI 返回坐标越界: (%d, %d)，截图尺寸 %dx%d", x, y, img_w, img_h)
                return None
        except Exception as e:
            logger.error("AI 定位选项失败: %s", e)
        return None
