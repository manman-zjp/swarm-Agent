"""Markdown 技能解析器：从 .md 文件自动生成 Skill 实例。

支持格式：
# 技能名称
> 技能描述

## 工具1名称
> 工具描述
- 参数1: 类型 (必填) - 描述
- 参数2: 类型 (可选) - 描述

## 工具2名称
...

使用方式：
    skill = MarkdownSkill.from_file("path/to/skill.md")
"""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any

from swarm.skills.base import BaseSkill

logger = logging.getLogger("swarm.skills.md_skill")


class MarkdownSkill(BaseSkill):
    """从 Markdown 文件解析的技能实例。"""

    def __init__(
        self,
        name: str,
        description: str,
        tools: list[dict[str, Any]],
        md_content: str,
    ) -> None:
        self._name = name
        self._description = description
        self._tools = tools
        self._md_content = md_content

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def get_tools(self) -> list[dict[str, Any]]:
        return self._tools

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        """Markdown 技能的执行逻辑：返回技能文档内容供 LLM 参考。"""
        # 找到对应工具的文档段落
        tool_doc = self._extract_tool_doc(tool_name)
        if tool_doc:
            return f"【{tool_name}】文档参考：\n\n{tool_doc}\n\n完整技能文档：\n{self._md_content[:2000]}"
        return f"未找到工具 {tool_name} 的文档。\n\n完整技能文档：\n{self._md_content[:2000]}"

    def _extract_tool_doc(self, tool_name: str) -> str:
        """提取指定工具的文档段落。"""
        # 匹配 ## 工具名称 到下一个 ## 之间的内容
        pattern = rf"## {re.escape(tool_name)}\s*\n(.*?)(?=## |\Z)"
        match = re.search(pattern, self._md_content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    @classmethod
    def from_file(cls, file_path: str | Path) -> MarkdownSkill:
        """从 Markdown 文件解析技能。

        Args:
            file_path: .md 文件路径

        Returns:
            MarkdownSkill 实例
        """
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")
        return cls._parse(content)

    @classmethod
    def _parse(cls, content: str) -> MarkdownSkill:
        """解析 Markdown 内容为技能。

        解析规则：
        1. 第一个 # 标题 → 技能名称
        2. 第一个 > 引用 → 技能描述
        3. 每个 ## 标题 → 工具名称
        4. ## 下的 > 引用 → 工具描述
        5. ## 下的 - 列表 → 工具参数
        """
        lines = content.split("\n")

        # 提取技能名称（第一个 # 标题）
        name = "unknown_skill"
        for line in lines:
            if line.startswith("# ") and not line.startswith("## "):
                name = line[2:].strip()
                break

        # 转换为合法的标识符（仅保留字母数字和下划线）
        name = re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()
        # 合并连续下划线
        name = re.sub(r"_+", "_", name).strip("_")
        if not name or name[0].isdigit():
            name = "skill_" + name

        # 提取技能描述（第一个 > 引用）
        description = ""
        for line in lines:
            if line.startswith("> "):
                description = line[2:].strip()
                break

        if not description:
            description = f"从 Markdown 文件加载的技能：{name}"

        # 提取工具定义
        tools = cls._parse_tools(content)

        return cls(
            name=name,
            description=description,
            tools=tools,
            md_content=content,
        )

    @classmethod
    def _parse_tools(cls, content: str) -> list[dict[str, Any]]:
        """解析 Markdown 中的工具定义。"""
        tools = []

        # 匹配所有 ## 标题
        sections = re.split(r"^## ", content, flags=re.MULTILINE)

        for section in sections[1:]:  # 跳过第一个（## 之前的内容）
            # 提取工具名称（第一行）
            first_newline = section.find("\n")
            if first_newline == -1:
                continue

            tool_name = section[:first_newline].strip()
            rest = section[first_newline:]

            # 提取工具描述（第一个 > 引用）
            tool_desc = ""
            for line in rest.split("\n"):
                if line.startswith("> "):
                    tool_desc = line[2:].strip()
                    break

            if not tool_desc:
                tool_desc = f"工具：{tool_name}"

            # 提取参数（- 开头的列表项）
            parameters = cls._parse_parameters(rest)

            tools.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_desc,
                    "parameters": parameters,
                }
            })

        return tools

    @classmethod
    def _parse_parameters(cls, section: str) -> dict[str, Any]:
        """解析参数列表。

        支持格式：
        - 参数名: 类型 (必填) - 描述
        - 参数名: 类型 - 描述
        """
        properties = {}
        required = []

        for line in section.split("\n"):
            line = line.strip()
            if not line.startswith("- "):
                continue

            # 移除 "- " 前缀
            param_line = line[2:].strip()

            # 解析：参数名: 类型 (必填) - 描述
            match = re.match(r"(\w+):\s*(\w+)(?:\s*\(必填\))?\s*[-:]\s*(.*)", param_line)
            if not match:
                # 简化格式：参数名: 描述
                match = re.match(r"(\w+):\s*(.*)", param_line)
                if match:
                    param_name = match.group(1)
                    param_desc = match.group(2).strip()
                    properties[param_name] = {
                        "type": "string",
                        "description": param_desc,
                    }
                continue

            param_name = match.group(1)
            param_type = match.group(2)
            param_desc = match.group(3).strip()

            # 转换类型
            type_map = {
                "string": "string",
                "str": "string",
                "int": "integer",
                "integer": "integer",
                "float": "number",
                "number": "number",
                "bool": "boolean",
                "boolean": "boolean",
                "list": "array",
                "array": "array",
                "object": "object",
            }
            json_type = type_map.get(param_type.lower(), "string")

            properties[param_name] = {
                "type": json_type,
                "description": param_desc,
            }

            # 检查是否必填
            if "(必填)" in param_line:
                required.append(param_name)

        schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return schema
