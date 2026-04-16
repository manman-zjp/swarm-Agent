"""LLM 客户端封装。

封装 OpenAI 兼容 API 的调用，支持：
- 普通对话（反思层）
- 带工具调用的 ReAct 循环（动态工具列表）
"""

from __future__ import annotations

import json
import os
import re
import logging
from typing import Any

from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("swarm.llm")


class LLMClient:
    """异步 OpenAI 兼容客户端。"""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_API_BASE_URL", ""),
        )
        self.model = os.getenv("MODEL_NAME", "GLM4.6")

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[str, dict]:
        """普通对话调用，返回 (文本, token_usage)。"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""
            content = self._strip_thinking(content)
            usage = {}
            if response.usage:
                usage = {
                    "prompt": response.usage.prompt_tokens,
                    "completion": response.usage.completion_tokens,
                }
            return content, usage
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return f"[LLM 错误] {e}", {}

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict[str, Any]],
        tool_executor: Any,
        max_rounds: int = 10,
    ) -> tuple[str, list[dict], dict]:
        """带工具调用的 ReAct 循环（动态工具列表）。

        Args:
            messages: 对话消息列表
            tools: OpenAI function calling 格式的工具定义列表
            tool_executor: 工具执行回调 async (tool_name, args) -> str
            max_rounds: 最大工具调用轮次

        Returns:
            (最终文本, 工具调用记录列表, 累计token_usage)
        """
        tool_records = []
        total_usage = {"prompt": 0, "completion": 0}

        for round_idx in range(max_rounds):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 4096,
                }
                if tools:
                    kwargs["tools"] = tools
                response = await self.client.chat.completions.create(**kwargs)
            except Exception as e:
                logger.error(f"LLM 工具调用失败: {e}")
                return f"[LLM 错误] {e}", tool_records, total_usage

            if response.usage:
                total_usage["prompt"] += response.usage.prompt_tokens
                total_usage["completion"] += response.usage.completion_tokens

            choice = response.choices[0]
            msg = choice.message

            # 如果模型没有调用工具，返回文本
            if not msg.tool_calls:
                content = msg.content or ""
                content = self._strip_thinking(content)
                return content, tool_records, total_usage

            # 将 assistant 消息加入历史
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            # 执行每个工具调用
            for tc in msg.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    func_args = {"raw": tc.function.arguments}

                logger.info(f"[ReAct] 调用工具: {func_name}")
                result = await tool_executor(func_name, func_args)

                tool_records.append({
                    "round": round_idx + 1,
                    "tool": func_name,
                    "args_preview": str(func_args)[:200],
                    "result_preview": str(result)[:200],
                })

                # 工具结果加入历史
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                })

        # 超过最大轮次
        return "工具调用超过最大轮次限制。", tool_records, total_usage

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """移除 <think>...</think> 标签。"""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
