"""
ElementProvider 抽象接口 —— 统一的元素读取与操作层

三种实现：
- BrowserElementProvider: 通过 Chrome DevTools Protocol 操作 Web 页面
- WindowsElementProvider: 通过 UI Automation 操作桌面程序
- 截图模式不需要 Provider（保留原有 screenshot→OCR→AI 路径）
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class OptionElement:
    """一个可选选项的元素描述。"""
    text: str                          # 选项文本内容
    element_ref: object = None         # 平台相关的元素引用（CDP nodeIndex / UIA control）
    selected: bool = False             # 当前是否已选中
    index: int = 0                     # 选项序号（0-based）


@dataclass
class InputTarget:
    """一个可输入的文本框目标。"""
    placeholder: str = ""              # 输入框 placeholder 或标签
    element_ref: object = None         # 平台相关的元素引用


@dataclass
class QuestionElement:
    """一道题目的完整元素信息。"""
    question_text: str                 # 题干文本
    question_type: str = ""            # 题型：single / multi / judge / fill / essay（可为空，由 AI 推断）
    options: list[OptionElement] = field(default_factory=list)
    input_targets: list[InputTarget] = field(default_factory=list)
    raw_hash: str = ""                 # 元素文本的哈希（用于去重和缓存查找）


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class ElementProvider(ABC):
    """
    元素提供器抽象接口。

    所有元素模式（browser / windows）的 Provider 都实现此接口。
    Engine 通过此接口读取题目元素、点击选项、输入文本。
    """

    @abstractmethod
    def connect(self, **kwargs) -> bool:
        """
        连接到目标环境。

        Returns
        -------
        bool
            True 表示连接成功，False 表示失败。
        """

    @abstractmethod
    def get_question_elements(self) -> Optional[QuestionElement]:
        """
        从当前页面/窗口中读取题目元素。

        Returns
        -------
        QuestionElement | None
            提取到的题目信息，无法提取时返回 None。
        """

    @abstractmethod
    def click_option(self, option: OptionElement) -> bool:
        """
        点击指定选项。

        Parameters
        ----------
        option : OptionElement
            要点击的选项（携带 element_ref）。

        Returns
        -------
        bool
            True 表示点击成功。
        """

    @abstractmethod
    def fill_input(self, target: InputTarget, text: str) -> bool:
        """
        在指定输入框中填入文本。

        Parameters
        ----------
        target : InputTarget
            目标输入框。
        text : str
            要填入的文本。

        Returns
        -------
        bool
            True 表示输入成功。
        """

    @abstractmethod
    def is_option_selected(self, option: OptionElement) -> bool:
        """
        查询指定选项是否已选中。

        Parameters
        ----------
        option : OptionElement
            要查询的选项。

        Returns
        -------
        bool
            True 表示已选中。
        """

    @abstractmethod
    def close(self):
        """关闭连接，释放资源。"""

    @property
    def name(self) -> str:
        """Provider 名称，用于日志和状态栏显示。"""
        return self.__class__.__name__
