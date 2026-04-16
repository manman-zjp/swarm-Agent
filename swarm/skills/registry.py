"""技能注册表：发现、加载、管理所有技能，统一路由工具调用。"""

from __future__ import annotations

import logging
from typing import Any

from swarm.skills.base import BaseSkill

logger = logging.getLogger("swarm.skills.registry")


class SkillRegistry:
    """技能注册表。

    管理所有已注册的技能，提供：
    - 统一的工具定义列表（供 LLM 使用）
    - 工具调用路由（根据 tool_name 分发到对应技能）
    """

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}  # name -> skill
        self._tool_map: dict[str, BaseSkill] = {}  # tool_name -> skill

    def register(self, skill: BaseSkill) -> None:
        """注册一个技能。"""
        if skill.name in self._skills:
            logger.warning(f"技能 '{skill.name}' 已存在，将被覆盖")
        self._skills[skill.name] = skill
        # 建立 tool_name -> skill 的映射
        for tool_def in skill.get_tools():
            tool_name = tool_def.get("function", {}).get("name", "")
            if tool_name:
                self._tool_map[tool_name] = skill
                logger.debug(f"注册工具: {tool_name} → 技能 '{skill.name}'")
        logger.info(f"注册技能: {skill.name} ({len(skill.get_tools())} 个工具)")

    def unregister(self, skill_name: str) -> None:
        """注销一个技能。"""
        skill = self._skills.pop(skill_name, None)
        if skill:
            for tool_def in skill.get_tools():
                tool_name = tool_def.get("function", {}).get("name", "")
                self._tool_map.pop(tool_name, None)
            logger.info(f"注销技能: {skill_name}")

    def get_all_tools(self) -> list[dict[str, Any]]:
        """获取所有已注册技能的工具定义列表（供 LLM chat_with_tools 使用）。"""
        tools = []
        for skill in self._skills.values():
            tools.extend(skill.get_tools())
        return tools

    def get_skill_descriptions(self) -> str:
        """生成所有技能的描述文本（供系统提示词使用）。"""
        if not self._skills:
            return "暂无可用技能。"
        parts = []
        for skill in self._skills.values():
            tool_names = [
                t.get("function", {}).get("name", "")
                for t in skill.get_tools()
            ]
            parts.append(f"- {skill.name}: {skill.description} (工具: {', '.join(tool_names)})")
        return "\n".join(parts)

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        """路由工具调用到对应技能执行。"""
        skill = self._tool_map.get(tool_name)
        if not skill:
            return f"未知工具: {tool_name}（没有技能注册该工具）"
        return await skill.execute(tool_name, args)

    @property
    def skill_count(self) -> int:
        return len(self._skills)

    @property
    def tool_count(self) -> int:
        return len(self._tool_map)

    def list_skills(self) -> list[dict[str, Any]]:
        """列出所有已注册技能的摘要信息。"""
        result = []
        for skill in self._skills.values():
            tool_names = [
                t.get("function", {}).get("name", "")
                for t in skill.get_tools()
            ]
            result.append({
                "name": skill.name,
                "description": skill.description,
                "tools": tool_names,
            })
        return result
