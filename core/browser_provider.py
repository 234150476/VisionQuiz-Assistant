"""
BrowserElementProvider —— 通过 Chrome DevTools Protocol 操作 Web 页面元素

连接 Chrome 远程调试端口，使用 Runtime.evaluate 执行 JS 查询 DOM。
支持外部 JSON 选择器配置文件，自动重连和降级逻辑。
"""

import json
import hashlib
import logging
import os
import time
from typing import Optional

try:
    import websocket
except ImportError:
    websocket = None

from core.element_provider import (
    ElementProvider, QuestionElement, OptionElement, InputTarget,
)

logger = logging.getLogger(__name__)

# 默认选择器配置
_DEFAULT_SELECTORS = {
    "question_text": ".question-text, #stem, .stem, .topic-text, [class*='question']",
    "option": ".option-item, .answer-choice, [class*='option'], label:has(input[type='radio']), label:has(input[type='checkbox'])",
    "option_selected": ".selected, .active, [aria-selected='true'], input:checked",
    "input_field": "input.answer-input, textarea, input[type='text']",
    "judge_option": ".judge-option, [class*='judge'], [class*='true-false']",
}


def _load_selectors(config_path: str) -> dict:
    """加载选择器配置文件，缺失字段用默认值补全。"""
    selectors = dict(_DEFAULT_SELECTORS)
    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user = json.load(f)
            selectors.update(user)
            logger.info("已加载选择器配置: %s", config_path)
        except Exception as exc:
            logger.warning("选择器配置加载失败，使用默认: %s", exc)
    return selectors


def _compute_text_hash(text: str) -> str:
    """计算文本的 MD5 哈希，用于去重和缓存查找。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class BrowserElementProvider(ElementProvider):
    """
    通过 Chrome DevTools Protocol 操作 Web 页面的元素提供器。

    要求 Chrome 启动时添加 --remote-debugging-port=9222 参数。
    """

    def __init__(
        self,
        debug_port: int = 9222,
        selector_config: str = "",
        timeout: float = 10.0,
    ):
        self._port = debug_port
        self._timeout = timeout
        self._selectors = _load_selectors(selector_config)
        self._ws: Optional[object] = None
        self._msg_id = 0
        self._connected = False

    @property
    def name(self) -> str:
        return f"Browser(CDP:{self._port})"

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self, **kwargs) -> bool:
        """连接到 Chrome CDP 调试端口。"""
        if websocket is None:
            logger.error("websocket-client 未安装，无法使用浏览器模式")
            return False

        port = kwargs.get("port", self._port)
        try:
            import urllib.request
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json", timeout=3
            )
            tabs = json.loads(resp.read().decode())
            ws_url = None
            for tab in tabs:
                if tab.get("type") == "page":
                    ws_url = tab.get("webSocketDebuggerUrl")
                    break
            if not ws_url:
                logger.warning("未找到可调试的页面标签")
                return False

            self._ws = websocket.create_connection(ws_url, timeout=self._timeout)
            self._connected = True
            logger.info("已连接 Chrome CDP: %s", ws_url)
            return True
        except Exception as exc:
            logger.warning("Chrome CDP 连接失败: %s", exc)
            self._connected = False
            return False

    def _ensure_connected(self) -> bool:
        """确保 WebSocket 连接可用，断线时尝试重连。"""
        if self._connected and self._ws:
            return True
        return self.connect()

    def close(self):
        """关闭 CDP 连接。"""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False
        logger.info("Chrome CDP 连接已关闭")

    # ------------------------------------------------------------------
    # CDP 通信
    # ------------------------------------------------------------------

    def _send_command(self, method: str, params: Optional[dict] = None, timeout: float = None) -> Optional[dict]:
        """发送 CDP 命令并等待响应。"""
        if not self._ensure_connected():
            return None

        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params

        try:
            self._ws.send(json.dumps(msg))
            deadline = time.monotonic() + (timeout or self._timeout)
            while time.monotonic() < deadline:
                self._ws.settimeout(max(0.1, deadline - time.monotonic()))
                resp = json.loads(self._ws.recv())
                if resp.get("id") == self._msg_id:
                    return resp.get("result")
            logger.warning("CDP 命令超时: %s", method)
            return None
        except Exception as exc:
            logger.warning("CDP 命令执行失败: %s — %s", method, exc)
            self._connected = False
            return None

    def _evaluate_js(self, expression: str) -> Optional[str]:
        """在页面中执行 JS 表达式，返回结果字符串。"""
        result = self._send_command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if result and "result" in result:
            r = result["result"]
            if r.get("type") == "string":
                return r.get("value", "")
            if r.get("value") is not None:
                return json.dumps(r["value"], ensure_ascii=False)
        return None

    # ------------------------------------------------------------------
    # 元素读取
    # ------------------------------------------------------------------

    def get_question_elements(self) -> Optional[QuestionElement]:
        """从当前页面读取题目元素。"""
        if not self._ensure_connected():
            return None

        try:
            question_text = self._extract_question_text()
            if not question_text:
                return None

            options = self._extract_options()
            input_targets = self._extract_input_targets()
            question_type = self._infer_type(options, input_targets)

            raw_hash = _compute_text_hash(question_text)

            return QuestionElement(
                question_text=question_text,
                question_type=question_type,
                options=options,
                input_targets=input_targets,
                raw_hash=raw_hash,
            )
        except Exception as exc:
            logger.warning("读取题目元素失败: %s", exc)
            return None

    def _extract_question_text(self) -> str:
        """提取题干文本。"""
        sel = self._selectors["question_text"]
        js = f"""
        (() => {{
            const el = document.querySelector('{sel}');
            return el ? el.innerText.trim() : '';
        }})()
        """
        result = self._evaluate_js(js)
        return result or ""

    def _extract_options(self) -> list[OptionElement]:
        """提取所有选项元素。"""
        sel = self._selectors["option"]
        sel_selected = self._selectors.get("option_selected", ".selected")
        js = f"""
        (() => {{
            const els = document.querySelectorAll('{sel}');
            const results = [];
            els.forEach((el, i) => {{
                const text = el.innerText.trim();
                if (!text) return;
                const selected = el.matches('{sel_selected}') ||
                    el.querySelector('input:checked') !== null;
                results.push({{text, index: i, selected}});
            }});
            return JSON.stringify(results);
        }})()
        """
        raw = self._evaluate_js(js)
        if not raw:
            return []

        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            return []

        return [
            OptionElement(
                text=item["text"],
                element_ref=item.get("index", i),
                selected=item.get("selected", False),
                index=i,
            )
            for i, item in enumerate(items)
        ]

    def _extract_input_targets(self) -> list[InputTarget]:
        """提取输入框元素。"""
        sel = self._selectors["input_field"]
        js = f"""
        (() => {{
            const els = document.querySelectorAll('{sel}');
            const results = [];
            els.forEach((el, i) => {{
                results.push({{
                    placeholder: el.placeholder || el.getAttribute('aria-label') || '',
                    index: i
                }});
            }});
            return JSON.stringify(results);
        }})()
        """
        raw = self._evaluate_js(js)
        if not raw:
            return []

        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            return []

        return [
            InputTarget(
                placeholder=item.get("placeholder", ""),
                element_ref=item.get("index", i),
            )
            for i, item in enumerate(items)
        ]

    def _infer_type(self, options: list[OptionElement], inputs: list[InputTarget]) -> str:
        """根据元素类型推断题型。"""
        if inputs and not options:
            return "fill"
        if len(options) == 2:
            texts = {o.text for o in options}
            judge_words = {"正确", "错误", "对", "错", "√", "×", "True", "False", "是", "否"}
            if texts & judge_words:
                return "judge"

        # 检查是否有 checkbox（多选）
        js_check = """
        (() => {
            const cbs = document.querySelectorAll('input[type="checkbox"]');
            const rbs = document.querySelectorAll('input[type="radio"]');
            return JSON.stringify({checkbox: cbs.length, radio: rbs.length});
        })()
        """
        raw = self._evaluate_js(js_check)
        if raw:
            try:
                counts = json.loads(raw)
                if counts.get("checkbox", 0) > 0:
                    return "multi"
                if counts.get("radio", 0) > 0:
                    return "single"
            except json.JSONDecodeError:
                pass

        return "single"

    # ------------------------------------------------------------------
    # 元素操作
    # ------------------------------------------------------------------

    def click_option(self, option: OptionElement) -> bool:
        """点击指定选项。"""
        if not self._ensure_connected():
            return False

        sel = self._selectors["option"]
        idx = option.element_ref if isinstance(option.element_ref, int) else option.index
        js = f"""
        (() => {{
            const els = document.querySelectorAll('{sel}');
            const el = els[{idx}];
            if (!el) return false;
            el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
            el.click();
            // 也尝试点击内部的 input
            const input = el.querySelector('input[type="radio"], input[type="checkbox"]');
            if (input) input.click();
            return true;
        }})()
        """
        result = self._evaluate_js(js)
        success = result == "true" or result is True
        if success:
            logger.info("已点击选项 #%d: %s", idx, option.text)
        else:
            logger.warning("点击选项失败 #%d: %s", idx, option.text)
        return success

    def fill_input(self, target: InputTarget, text: str) -> bool:
        """在指定输入框中填入文本。"""
        if not self._ensure_connected():
            return False

        sel = self._selectors["input_field"]
        idx = target.element_ref if isinstance(target.element_ref, int) else 0
        # 转义文本中的特殊字符
        escaped_text = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        js = f"""
        (() => {{
            const els = document.querySelectorAll('{sel}');
            const el = els[{idx}];
            if (!el) return false;
            el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
            el.focus();
            el.value = '{escaped_text}';
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }})()
        """
        result = self._evaluate_js(js)
        success = result == "true" or result is True
        if success:
            logger.info("已填入文本到输入框 #%d", idx)
        else:
            logger.warning("填入文本失败，输入框 #%d", idx)
        return success

    def is_option_selected(self, option: OptionElement) -> bool:
        """查询指定选项是否已选中。"""
        if not self._ensure_connected():
            return False

        sel = self._selectors["option"]
        sel_selected = self._selectors.get("option_selected", ".selected")
        idx = option.element_ref if isinstance(option.element_ref, int) else option.index
        js = f"""
        (() => {{
            const els = document.querySelectorAll('{sel}');
            const el = els[{idx}];
            if (!el) return false;
            return el.matches('{sel_selected}') ||
                el.querySelector('input:checked') !== null;
        }})()
        """
        result = self._evaluate_js(js)
        return result == "true" or result is True
