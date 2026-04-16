"""任务操作技能：任务拆分（decompose）。

当 LLM 判断任务需要拆分时，调用 decompose_task 工具。
Agent 收到拆分结果后在黑板上创建子任务。
"""

from __future__ import annotations

import json
from typing import Any

from swarm.skills.base import BaseSkill


class TaskDecomposeSkill(BaseSkill):
    """任务拆分技能。

    提供 decompose_task 工具，让 LLM 自主决定是否需要拆分。
    """

    @property
    def name(self) -> str:
        return "task_ops"

    @property
    def description(self) -> str:
        return "任务拆分：当任务包含多个完全独立的子目标时，拆分为子任务并行处理"

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "decompose_task",
                    "description": (
                        "将复杂任务拆分为多个独立子任务。"
                        "仅当任务包含 2 个以上完全独立、互不依赖的子目标时使用。"
                        "绝大多数任务不需要拆分。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subtasks": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "子任务描述列表，每个子任务必须自包含完整上下文",
                            }
                        },
                        "required": ["subtasks"],
                    },
                },
            },
        ]

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        """decompose_task 的执行结果由 Agent 层拦截处理，这里只做格式校验。"""
        if tool_name == "decompose_task":
            subtasks = args.get("subtasks", [])
            if not subtasks or len(subtasks) < 2:
                return "拆分失败：至少需要 2 个子任务"
            return json.dumps({
                "action": "decompose",
                "subtasks": subtasks,
            }, ensure_ascii=False)
        return f"未知工具: {tool_name}"
