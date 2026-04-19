"""蜂群 Agent：统一执行架构。

所有 Agent 完全同质——相同代码、相同 LLM、共享技能注册表。
每个 Agent 实例是一个持续运行的协程，从黑板领取任务并处理。

架构：
- 单一 ReAct 执行层：LLM 自主决定直接回答 / 调用工具 / 拆分任务
- 条件反思：仅在使用了工具时触发反思验证
- 技能驱动：所有工具能力来自 SkillRegistry（内置技能 + MCP 技能）
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any

from swarm.core.blackboard import Blackboard
from swarm.core.models import Task, TaskStatus, ReflectionResult
from swarm.core.observer import observer
from swarm.llm import LLMClient
from swarm.skills.registry import SkillRegistry
from swarm.prompts import (
    SYSTEM_PROMPT_TEMPLATE, USER_PROMPT_TEMPLATE,
    REFLECTION_SYSTEM, REFLECTION_USER_TEMPLATE,
)
from swarm.config import config

logger = logging.getLogger("swarm.agent")


class SwarmAgent:
    """蜂群 Agent：统一执行 + 条件反思。"""

    def __init__(
        self,
        agent_id: str,
        blackboard: Blackboard,
        llm: LLMClient,
        skills: SkillRegistry,
    ) -> None:
        self.agent_id = agent_id
        self.blackboard = blackboard
        self.llm = llm
        self.skills = skills
        self._running = False

    async def run_forever(self) -> None:
        """Agent 主循环：领取 → 处理 → 提交，循环往复。"""
        self._running = True
        logger.info(f"[{self.agent_id}] 加入蜂群")
        while self._running:
            task = await self.blackboard.claim_pending(self.agent_id)
            if task is None:
                await self.blackboard.wait_for_task(timeout=config.agent.task_wait_timeout)
                continue
            try:
                await self.process_task(task)
            except Exception as e:
                logger.error(f"[{self.agent_id}] 处理任务异常: {e}", exc_info=True)
                await self.blackboard.mark_failed(task, str(e))

    def stop(self) -> None:
        self._running = False

    # ── 核心处理流程 ──────────────────────────────────

    async def process_task(self, task: Task) -> None:
        """统一处理流程：ReAct 执行 → 条件反思。"""
        trace_id = str(uuid.uuid4())[:8]
        task_start = time.time()
        logger.info(f"[{self.agent_id}] 开始处理: {task.task_id} | {task.action[:60]}")

        # ── 1. 统一 ReAct 执行 ──
        t0 = time.time()
        result, tool_records, usage = await self._execute(task, trace_id)
        exec_ms = (time.time() - t0) * 1000
        observer.trace(
            trace_id=trace_id, task_id=task.task_id, agent_id=self.agent_id,
            layer="execution", step_seq=1, action="react_execute",
            input_data=task.action[:300], output_data=result[:300],
            duration_ms=exec_ms, session_id=task.session_id,
        )

        # ── 2. 检查是否触发了任务拆分 ──
        decompose_result = self._check_decompose(tool_records)
        if decompose_result:
            subtasks = await self.blackboard.decompose(
                task, decompose_result, source="llm_decision",
            )
            logger.info(f"[{self.agent_id}] LLM 决定拆分为 {len(subtasks)} 个子任务")
            observer.trace(
                trace_id=trace_id, task_id=task.task_id, agent_id=self.agent_id,
                layer="execution", step_seq=2, action="decompose",
                input_data=task.action[:200],
                output_data={"subtask_count": len(subtasks)},
                duration_ms=(time.time() - t0) * 1000, session_id=task.session_id,
            )
            return

        # ── 3. 条件反思（仅复杂工具调用后） ──
        # 过滤掉 decompose_task，只看实际执行类工具
        exec_tools = [r for r in tool_records if r["tool"] != "decompose_task"]
        # 只有多步工具调用或耗时超阈值才触发反思，简单任务直接提交
        needs_reflection = (
            len(exec_tools) >= config.agent.reflection_tool_threshold
            or exec_ms > config.agent.reflection_time_ms
        )
        if exec_tools and needs_reflection:
            t0 = time.time()
            reflection = await self._reflect(task, result, trace_id)
            observer.trace(
                trace_id=trace_id, task_id=task.task_id, agent_id=self.agent_id,
                layer="reflection", step_seq=3, action="reflect",
                input_data=result[:200],
                output_data={"passed": reflection.passed, "summary": reflection.summary[:200]},
                duration_ms=(time.time() - t0) * 1000, session_id=task.session_id,
            )
            if not reflection.passed:
                # 修复执行
                t0 = time.time()
                result, _, _ = await self._execute(task, trace_id, fix_plan=reflection.fix_plan)
                observer.trace(
                    trace_id=trace_id, task_id=task.task_id, agent_id=self.agent_id,
                    layer="execution", step_seq=4, action="fix_execute",
                    input_data=reflection.fix_plan[:200], output_data=result[:300],
                    duration_ms=(time.time() - t0) * 1000, session_id=task.session_id,
                )
            await self.blackboard.submit_result(
                task, result,
                reflection.lessons if reflection.passed else [],
            )
        else:
            # 纯文本回答或无工具调用 → 直接提交
            observer.trace(
                trace_id=trace_id, task_id=task.task_id, agent_id=self.agent_id,
                layer="reflection", step_seq=3, action="skip_reflection",
                input_data="no_exec_tools", output_data={"reason": "无执行类工具调用，跳过反思"},
                duration_ms=0, session_id=task.session_id,
            )
            await self.blackboard.submit_result(task, result, [])

        total_ms = (time.time() - task_start) * 1000
        logger.info(
            f"[{self.agent_id}] 任务完成: {task.task_id} | "
            f"{total_ms:.0f}ms | tools={len(tool_records)}"
        )

    # ── 执行层 ──────────────────────────────────────

    async def _execute(
        self, task: Task, trace_id: str, fix_plan: str | None = None,
    ) -> tuple[str, list[dict], dict]:
        """统一 ReAct 执行：构建动态工具列表 + 调用 LLM。"""
        # 构建知识上下文
        cautions = "无"
        knowledge = self.blackboard.query_knowledge(task)
        if knowledge["lessons"]:
            cautions = "\n".join(
                f"- {les.context}: {les.lesson}" for les in knowledge["lessons"][:config.knowledge.max_lessons_in_prompt]
            )

        # 构建会话上下文
        session_context = "无历史"
        if task.session_id:
            history = self.blackboard.get_session_history(task.session_id)
            if history:
                parts = []
                for h in history:
                    parts.append(
                        f"[第{h.turn_index}轮] {h.action[:80]} → "
                        f"{(h.output_text or '')[:200]}"
                    )
                session_context = "\n".join(parts)

        # 动态构建系统提示词（包含当前可用技能描述）
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            skill_descriptions=self.skills.get_skill_descriptions(),
        )

        # 构建用户提示词
        action = task.action
        if fix_plan:
            action = f"{task.action}\n\n## 修复方案\n{fix_plan}"

        user_prompt = USER_PROMPT_TEMPLATE.format(
            action=action,
            session_context=session_context,
            cautions=cautions,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # 获取动态工具列表
        tools = self.skills.get_all_tools()

        result, tool_records, usage = await self.llm.chat_with_tools(
            messages, tools, self.skills.execute,
        )

        # 记录工具调用 trace
        for i, tr in enumerate(tool_records):
            observer.trace(
                trace_id=trace_id, task_id=task.task_id, agent_id=self.agent_id,
                layer="execution", step_seq=100 + i,
                action=f"tool_call:{tr['tool']}",
                input_data=tr["args_preview"],
                output_data=tr["result_preview"],
                session_id=task.session_id,
            )

        return result, tool_records, usage

    # ── 反思层 ──────────────────────────────────────

    async def _reflect(
        self, task: Task, result: str, trace_id: str,
    ) -> ReflectionResult:
        """反思层：纯推理，自检结果 + 提取经验。"""
        messages = [
            {"role": "system", "content": REFLECTION_SYSTEM},
            {"role": "user", "content": REFLECTION_USER_TEMPLATE.format(
                action=task.action,
                result=result[:config.agent.reflection_result_max_chars],
            )},
        ]

        response, usage = await self.llm.chat(messages, temperature=config.llm.reflection_temperature)
        return self._parse_reflection(response)

    # ── 辅助方法 ──────────────────────────────────

    @staticmethod
    def _check_decompose(tool_records: list[dict]) -> list[str] | None:
        """检查工具调用记录中是否有 decompose_task，返回子任务列表。"""
        for record in tool_records:
            if record["tool"] == "decompose_task":
                try:
                    data = json.loads(record["result_preview"])
                    if data.get("action") == "decompose":
                        return data.get("subtasks", [])
                except (json.JSONDecodeError, KeyError):
                    pass
        return None

    def _parse_reflection(self, text: str) -> ReflectionResult:
        """从 LLM 输出中解析反思结果。"""
        data = self._extract_json(text)
        if not data:
            return ReflectionResult(passed=True, summary=text)

        if data.get("passed", True):
            return ReflectionResult(
                passed=True,
                summary=data.get("summary", ""),
                lessons=data.get("lessons", []),
            )
        else:
            return ReflectionResult(
                passed=False,
                summary=data.get("reason", ""),
                fix_plan=data.get("fix_plan", ""),
            )

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """从文本中提取 JSON（支持 ```json 代码块和裸 JSON）。"""
        match = re.search(r"```json\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None
