"""
AI 客户端模块 —— 封装 OpenAI SDK 调用（兼容 OpenAI / Claude / 本地模型）
"""

import logging
import base64
import io
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


class AIClient:
    """
    封装 AI 模型调用。
    支持：
    - 纯文字问答（题目文本 → 答案）
    - 图文混合问答（题目文本 + 截图 → 答案）
    - 点击验证（点击后截图 → AI 判断是否已选中）
    """

    def __init__(self, api_key: str, api_base_url: str, model: str, timeout: int = 30):
        self.model = model
        self.timeout = timeout
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

    def _chat(self, messages: list, temperature: float = 0.0) -> str:
        """
        发送 chat 请求，返回 assistant 回复内容字符串。
        出错时抛出异常（由调用方处理）。
        """
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        if not resp.choices:
            raise ValueError("AI 返回空 choices（可能被内容过滤）")
        content = resp.choices[0].message.content
        if content is None:
            raise ValueError("AI 返回 content 为 None（非文本响应）")
        return content.strip()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def answer_with_text(self, ocr_text: str) -> str:
        """
        仅凭 OCR 文本作答。
        返回答案字符串；多选题各选项以 |答案分隔| 连接。
        """
        system_prompt = (
            "你是一个企业培训考试答题助手。\n"
            "根据用户提供的题目文本，直接给出答案。\n"
            "规则：\n"
            "1. 单选题只回答选项字母（如：A）\n"
            "2. 多选题回答所有正确选项字母，用 |答案分隔| 连接（如：A|答案分隔|C）\n"
            "3. 判断题回答：正确 或 错误\n"
            "4. 简答题简洁作答，无字数要求时根据题意给出合适长度的答案\n"
            "5. 除答案本身外，不要输出任何解释或前缀"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"题目：\n{ocr_text}"},
        ]
        return self._chat(messages)

    def answer_with_image(self, ocr_text: str, screenshot_img) -> str:
        """
        结合 OCR 文本和屏幕截图共同作答。
        AI 自主决策以哪个来源为准。
        返回答案字符串；多选题各选项以 |答案分隔| 连接。
        """
        system_prompt = (
            "你是一个企业培训考试答题助手。\n"
            "用户会提供题目截图和 OCR 识别文本，请综合两者判断题目内容并作答。\n"
            "若 OCR 文本与截图不一致，以截图为准。\n"
            "规则：\n"
            "1. 单选题只回答选项字母（如：A）\n"
            "2. 多选题回答所有正确选项字母，用 |答案分隔| 连接（如：A|答案分隔|C）\n"
            "3. 判断题回答：正确 或 错误\n"
            "4. 简答题简洁作答，无字数要求时根据题意给出合适长度的答案\n"
            "5. 除答案本身外，不要输出任何解释或前缀"
        )
        img_b64 = self._image_to_b64(screenshot_img)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"OCR 识别文本：\n{ocr_text}\n\n请结合以下截图作答：",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": img_b64},
                    },
                ],
            },
        ]
        return self._chat(messages)

    def verify_click(self, before_img, after_img, expected_answer: str) -> bool:
        """
        点击后验证：将点击前后两张截图发给 AI，判断是否已成功选中目标答案。
        返回 True 表示点击成功，False 表示失败/不确定。
        """
        system_prompt = (
            "你是一个界面交互验证助手。\n"
            "用户会提供点击前后两张截图，以及期望选中的答案。\n"
            "请判断点击后截图中，期望答案是否已被选中（高亮、勾选、圆点填充等视觉变化）。\n"
            "只回答：已选中 或 未选中"
        )
        before_b64 = self._image_to_b64(before_img)
        after_b64 = self._image_to_b64(after_img)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"期望选中的答案：{expected_answer}\n\n点击前截图："},
                    {"type": "image_url", "image_url": {"url": before_b64}},
                    {"type": "text", "text": "点击后截图："},
                    {"type": "image_url", "image_url": {"url": after_b64}},
                ],
            },
        ]
        try:
            result = self._chat(messages)
            return "已选中" in result
        except Exception as e:
            logger.error("点击验证 AI 调用失败: %s", e)
            return False

    def locate_option(self, screenshot_img, answer: str) -> Optional[tuple[int, int]]:
        """
        让 AI 在截图中定位指定选项的坐标（相对于截图左上角）。
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
        img_b64 = self._image_to_b64(screenshot_img)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"需要点击的答案选项：{answer}\n截图："},
                    {"type": "image_url", "image_url": {"url": img_b64}},
                ],
            },
        ]
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
                if 0 <= x <= img_w and 0 <= y <= img_h:
                    return (x, y)
                logger.warning("AI 返回坐标越界: (%d, %d)，截图尺寸 %dx%d", x, y, img_w, img_h)
                return None
        except Exception as e:
            logger.error("AI 定位选项失败: %s", e)
        return None
