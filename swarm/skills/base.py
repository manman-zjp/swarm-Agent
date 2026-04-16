"""技能基类：所有技能的抽象接口。

每个技能提供：
1. 元信息（名称、描述）
2. 工具定义（OpenAI function calling 格式）
3. 执行逻辑（接收工具名和参数，返回结果）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSkill(ABC):
    """技能抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """技能名称（唯一标识）。"""

    @property
    @abstractmethod
    def description(self) -> str:
        """技能描述（给 LLM 看的，说明这个技能能做什么）。"""

    @abstractmethod
    def get_tools(self) -> list[dict[str, Any]]:
        """返回该技能提供的工具定义列表。

        格式：OpenAI function calling tool 格式，例如：
        [
            {
                "type": "function",
                "function": {
                    "name": "execute_python",
                    "description": "执行 Python 代码",
                    "parameters": { ... }
                }
            }
        ]
        """

    @abstractmethod
    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        """执行工具调用。

        Args:
            tool_name: 工具名（必须是 get_tools() 中定义的）
            args: 工具参数

        Returns:
            执行结果的文本描述
        """

    def handles(self, tool_name: str) -> bool:
        """判断该技能是否处理指定工具名。"""
        for tool_def in self.get_tools():
            if tool_def.get("function", {}).get("name") == tool_name:
                return True
        return False
