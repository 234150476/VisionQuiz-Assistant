"""
UI 错误映射器 —— 将底层异常与原始错误消息翻译成用户可见文案。
"""

import sqlite3


class UIErrorMapper:
    @classmethod
    def translate(cls, exc_or_msg) -> tuple[str, str]:
        if isinstance(exc_or_msg, BaseException):
            return cls._translate_exception(exc_or_msg)
        return cls._translate_message(str(exc_or_msg or ""))

    @classmethod
    def _translate_exception(cls, exc: BaseException) -> tuple[str, str]:
        exc_name = type(exc).__name__

        if isinstance(exc, ConnectionError) or exc_name == "APIConnectionError":
            return "AI 服务连接失败，请检查网络和 API Key", "error"
        if isinstance(exc, TimeoutError) or exc_name == "APITimeoutError":
            return "请求超时，请稍后重试", "error"
        if isinstance(exc, sqlite3.DatabaseError):
            return "题库数据损坏，请重新导入", "error"
        if isinstance(exc, PermissionError):
            return "文件访问失败，请检查权限", "error"
        if isinstance(exc, OSError):
            return "文件访问失败，请检查权限", "error"
        if isinstance(exc, ValueError):
            return "配置或输入内容无效，请检查后重试", "error"
        if isinstance(exc, RuntimeError):
            return "运行过程中发生异常，请稍后重试", "error"
        return f"发生未知错误：{exc_name}", "error"

    @classmethod
    def _translate_message(cls, msg: str) -> tuple[str, str]:
        text = msg.strip()
        if not text:
            return "发生未知错误：UnknownError", "error"

        lower = text.lower()
        if "timeout" in lower or "超时" in text:
            return "请求超时，请稍后重试", "error"
        if "connection" in lower or "network" in lower or "api key" in lower:
            return "AI 服务连接失败，请检查网络和 API Key", "error"
        if "截图异常" in text or "截图失败" in text:
            return "截图失败，请确认目标窗口可见后重试", "error"
        if "识别器未初始化" in text:
            return "识别器尚未就绪，请重新启动后重试", "error"
        if "识别失败" in text:
            return "识别失败，请稍后重试或调整题目区域", "error"
        if "识别异常" in text:
            return "识别过程中发生异常，请稍后重试", "error"
        if "自动点击失败" in text:
            return "自动点击失败，请手动完成当前题目", "error"
        if "自动点击异常" in text:
            return "自动点击过程中发生异常，请手动完成当前题目", "error"
        if "题库" in text and ("损坏" in text or "database" in lower):
            return "题库数据损坏，请重新导入", "error"
        if "权限" in text or "permission" in lower:
            return "文件访问失败，请检查权限", "error"
        if "运行异常" in text:
            return "运行过程中发生异常，请稍后重试", "error"
        return text, "error"
