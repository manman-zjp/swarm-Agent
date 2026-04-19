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
from swarm.core.models import Task, TaskStatus, ReflectionResult, SessionFact
from swarm.core.observer import observer
from swarm.llm import LLMClient
from swarm.skills.registry import SkillRegistry
from swarm.prompts import (
    SYSTEM_PROMPT_TEMPLATE, USER_PROMPT_TEMPLATE,
    REFLECTION_SYSTEM, REFLECTION_USER_TEMPLATE,
    SUMMARY_SYSTEM, SUMMARY_USER_TEMPLATE,
    FACT_EXTRACT_SYSTEM, FACT_EXTRACT_USER_TEMPLATE,
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

        # ── 4. 任务完成后，异步触发增量摘要 + 事实提取 ──
        if task.session_id and task.parent_id is None:
            asyncio.create_task(self._maybe_summarize(task))
            asyncio.create_task(self._maybe_extract_facts(task, result))

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

        # 构建会话上下文（滑动窗口 + 增量摘要）
        session_context = self._build_session_context(task)

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

    # ── 会话上下文构建（滑动窗口 + 增量摘要）────────

    def _build_session_context(self, task: Task) -> str:
        """构建会话上下文：核心事实（KV）+ 摘要（窗口外）+ 近期原文（窗口内）。
    
        结构：
        ### 核心事实
        - tech_stack: FastAPI + PostgreSQL
        - project_name: 电商平台
        ### 历史摘要（第1-5轮压缩）
        用户在做一个电商项目...
        ### 近期对话
        [第6轮] xxx → yyy
        """
        if not task.session_id:
            return "无历史"
    
        window_size = config.task.summary_window_size
        all_done = self.blackboard.get_session_full_history(task.session_id)
        history = [t for t in all_done if t.task_id != task.task_id]
    
        parts = []
    
        # 1. 核心事实（KV，始终在 prompt 最前面）
        facts = self.blackboard.get_session_facts(task.session_id)
        if facts:
            fact_lines = [f"- {f.fact_key}: {f.fact_value}" for f in facts]
            parts.append("### 核心事实\n" + "\n".join(fact_lines))
    
        if not history:
            return "\n\n".join(parts) if parts else "无历史"
    
        # 2. 摘要部分（窗口外的压缩历史）
        memory = self.blackboard.get_session_memory(task.session_id)
        if memory and memory.summary:
            parts.append(
                f"### 历史摘要（第1-{memory.summary_up_to_turn}轮压缩）\n"
                f"{memory.summary}"
            )
    
        # 3. 窗口内近期轮次（原文）
        recent = history[-window_size:]
        if recent:
            detail_chars = config.task.summary_turn_detail_chars
            recent_lines = []
            for h in recent:
                action_preview = h.action[:100]
                output_preview = (h.output_text or '')[:detail_chars]
                recent_lines.append(
                    f"[第{h.turn_index}轮] 用户: {action_preview}\n"
                    f"回复: {output_preview}"
                )
            parts.append("### 近期对话\n" + "\n\n".join(recent_lines))
    
        return "\n\n".join(parts) if parts else "无历史"

    async def _maybe_summarize(self, task: Task) -> None:
        """任务完成后检查是否需要触发增量摘要压缩。

        触发条件：当前轮次 > 窗口大小，且有未被摘要覆盖的历史轮次。
        压缩范围：将窗口外的轮次（包含旧摘要 + 新溢出轮次）压缩成新摘要。
        """
        try:
            session_id = task.session_id
            if not session_id:
                return

            window_size = config.task.summary_window_size
            all_done = self.blackboard.get_session_full_history(session_id)
            total_turns = len(all_done)

            # 轮次还在窗口内，不需要摘要
            if total_turns <= window_size:
                return

            # 计算需要被摘要覆盖的轮次范围
            memory = self.blackboard.get_session_memory(session_id)
            current_summary = memory.summary if memory else ""
            already_covered = memory.summary_up_to_turn if memory else 0

            # 窗口外的轮次 = 全部轮次去掉最后 window_size 个
            out_of_window = all_done[:-window_size]
            new_cutoff = out_of_window[-1].turn_index if out_of_window else 0

            # 如果摘要已经覆盖到最新的窗口边界，无需更新
            if new_cutoff <= already_covered:
                return

            # 取出新溢出窗口的轮次（尚未被摘要覆盖的）
            new_turns = [t for t in out_of_window if t.turn_index > already_covered]
            if not new_turns and not current_summary:
                return

            # 构建摘要输入
            detail_chars = config.task.summary_turn_detail_chars
            existing_part = ""
            if current_summary:
                existing_part = f"### 已有摘要（第1-{already_covered}轮）\n{current_summary}\n\n"

            new_parts = []
            for t in new_turns:
                new_parts.append(
                    f"[第{t.turn_index}轮] 用户: {t.action[:150]}\n"
                    f"回复: {(t.output_text or '')[:detail_chars]}"
                )
            new_turns_text = "### 新增对话\n" + "\n\n".join(new_parts) if new_parts else ""

            # 调 LLM 压缩
            max_chars = config.task.summary_max_chars
            messages = [
                {"role": "system", "content": SUMMARY_SYSTEM.format(max_chars=max_chars)},
                {"role": "user", "content": SUMMARY_USER_TEMPLATE.format(
                    existing_summary=existing_part,
                    new_turns=new_turns_text,
                )},
            ]
            summary_text, _ = await self.llm.chat(
                messages, temperature=0.1, max_tokens=max_chars + 200,
            )

            # 截断保护
            if len(summary_text) > max_chars:
                summary_text = summary_text[:max_chars]

            # 写回黑板
            self.blackboard.update_session_memory(
                session_id=session_id,
                summary=summary_text,
                up_to_turn=new_cutoff,
                total_turns=total_turns,
            )
            observer.trace(
                trace_id=str(uuid.uuid4())[:8],
                task_id=task.task_id,
                agent_id=self.agent_id,
                layer="memory",
                step_seq=0,
                action="session_summarize",
                input_data=f"turns={already_covered+1}-{new_cutoff}, total={total_turns}",
                output_data=summary_text[:300],
                session_id=session_id,
            )
        except Exception as e:
            logger.warning(f"[{self.agent_id}] 会话摘要失败: {e}")

    async def _maybe_extract_facts(self, task: Task, result: str) -> None:
        """任务完成后异步提取 KV 事实。

        调 LLM 从本轮对话中提取结构化事实，写入黑板并持久化。
        """
        try:
            session_id = task.session_id
            if not session_id:
                return

            # 构建已有事实上下文
            existing = self.blackboard.get_session_facts(session_id)
            if existing:
                existing_text = "\n".join(
                    f"- {f.fact_key}: {f.fact_value}" for f in existing
                )
            else:
                existing_text = "无"

            messages = [
                {"role": "system", "content": FACT_EXTRACT_SYSTEM.format(
                    existing_facts=existing_text,
                )},
                {"role": "user", "content": FACT_EXTRACT_USER_TEMPLATE.format(
                    user_message=task.action[:500],
                    assistant_reply=result[:500],
                )},
            ]
            response, _ = await self.llm.chat(
                messages, temperature=0.1, max_tokens=500,
            )

            # 解析 JSON 数组
            facts_data = self._extract_json_array(response)
            if not facts_data:
                return

            new_facts = []
            for item in facts_data:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key", "")).strip()
                value = str(item.get("value", "")).strip()
                if key and value:
                    new_facts.append(SessionFact(
                        session_id=session_id,
                        fact_key=key,
                        fact_value=value,
                        source_turn=task.turn_index,
                    ))

            if new_facts:
                self.blackboard.update_session_facts(session_id, new_facts)
                observer.trace(
                    trace_id=str(uuid.uuid4())[:8],
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    layer="memory",
                    step_seq=0,
                    action="fact_extract",
                    input_data=f"turn={task.turn_index}",
                    output_data={f.fact_key: f.fact_value for f in new_facts},
                    session_id=session_id,
                )
        except Exception as e:
            logger.warning(f"[{self.agent_id}] 事实提取失败: {e}")

    @staticmethod
    def _extract_json_array(text: str) -> list[dict] | None:
        """从文本中提取 JSON 数组。"""
        # 尝试代码块内的 JSON
        match = re.search(r"```json\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass
        # 直接解析
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
        # 匹配 […] 片段
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(0))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass
        return None
