"""蜂群系统数据模型。

定义任务、集体知识（技能/拆分模式/经验教训）的数据结构。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from swarm.config import config


class TaskStatus(str, Enum):
    """任务状态（信息素）。"""
    PENDING = "pending"
    RUNNING = "running"
    DECOMPOSED = "decomposed"
    PENDING_REVIEW = "pending_review"
    DONE = "done"
    REJECTED = "rejected"
    FAILED = "failed"


class TaskType(str, Enum):
    """任务类型。"""
    NORMAL = "normal"
    REVIEW = "review"
    REFLECTION = "reflection"
    SESSION_SUMMARY = "session_summary"


@dataclass
class Task:
    """黑板上的任务。"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    action: str = ""
    status: TaskStatus = TaskStatus.PENDING
    task_type: TaskType = TaskType.NORMAL
    parent_id: str | None = None
    session_id: str | None = None
    turn_index: int = 0
    needs: list[str] = field(default_factory=list)
    context_refs: list[str] = field(default_factory=list)
    output_ref: str | None = None
    output_text: str | None = None
    claimed_by: str | None = None
    claim_expires: datetime | None = None
    retry_count: int = 0
    max_retries: int = field(default_factory=lambda: config.task.max_retries)
    priority: int = 0
    input_schema: str | None = None
    output_schema: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    # 反思层附带的经验
    lessons_extracted: list[dict] = field(default_factory=list)
    # 拆分来源
    decompose_source: str | None = None  # skill / pattern / scratch
    # ── 交叉评审字段 ──
    draft_output: str | None = None       # 初稿（提交评审前的执行结果）
    reviewer_id: str | None = None        # 评审者 agent_id
    review_comments: str | None = None    # 评审意见
    review_round: int = 0                 # 当前评审轮次

    def is_claimable(self) -> bool:
        """是否可被领取（新任务）。"""
        if self.status != TaskStatus.PENDING:
            return False
        if self.claimed_by and self.claim_expires and datetime.now() < self.claim_expires:
            return False
        return True

    def is_reviewable(self, exclude_agent: str) -> bool:
        """是否可被评审（排除执行者自己）。"""
        return (
            self.status == TaskStatus.PENDING_REVIEW
            and self.claimed_by != exclude_agent
        )

    def claim(self, agent_id: str, ttl_seconds: int | None = None) -> bool:
        """尝试领取（非线程安全，需外部加锁）。"""
        if not self.is_claimable():
            return False
        _ttl = ttl_seconds if ttl_seconds is not None else config.task.claim_ttl_seconds
        self.status = TaskStatus.RUNNING
        self.claimed_by = agent_id
        self.claim_expires = datetime.now() + timedelta(seconds=_ttl)
        self.updated_at = datetime.now()
        return True


@dataclass
class Lesson:
    """经验教训。"""
    lesson_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    context: str = ""
    lesson: str = ""
    source_task: str = ""
    confidence: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Pattern:
    """拆分模式。"""
    pattern_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    trigger: str = ""
    template: list[str] = field(default_factory=list)
    success_rate: float = 0.5
    used_count: int = 0
    confidence: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Skill:
    """技能：经过验证的完整执行方案。"""
    skill_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    trigger: str = ""
    description: str = ""
    procedure: list[dict[str, Any]] = field(default_factory=list)
    known_issues: list[str] = field(default_factory=list)
    source_tasks: list[str] = field(default_factory=list)
    confidence: float = 0.5
    success_count: int = 0
    fail_count: int = 0
    version: int = 1
    status: str = "active"
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class SessionMemory:
    """会话记忆：滚动摘要 + 窗口控制。

    采用业界主流的「滑动窗口 + 增量摘要」模式：
    - summary: 窗口外历史轮次的压缩摘要
    - summary_up_to_turn: 摘要覆盖到第几轮（含）
    - 窗口内的最近 N 轮保持原文，注入 prompt
    - 每次新轮次完成后，若超出窗口，触发增量压缩
    """
    session_id: str = ""
    summary: str = ""  # 窗口外历史的压缩摘要
    summary_up_to_turn: int = 0  # 摘要已覆盖到第几轮（含）
    total_turns: int = 0  # 当前会话总轮次
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class SessionFact:
    """会话事实：KV 结构的精确记忆。

    从对话中提取的结构化事实，始终注入 prompt，解决摘要有损压缩
    导致精确信息丢失的问题。例如：
    - tech_stack: "FastAPI + PostgreSQL"
    - api_prefix: "/api/v2"
    - project_name: "蜂群Agent"
    """
    session_id: str = ""
    fact_key: str = ""       # 事实键（如 tech_stack、project_name）
    fact_value: str = ""     # 事实值
    source_turn: int = 0     # 提取自第几轮对话
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class ReflectionResult:
    """第三层反思的输出。"""
    passed: bool = True
    summary: str = ""
    fix_plan: str = ""
    lessons: list[dict] = field(default_factory=list)
    skill_candidate: dict | None = None


@dataclass
class ReviewResult:
    """交叉评审的输出。"""
    approved: bool = True
    comments: str = ""          # 评审意见
    fix_suggestions: str = ""   # 具体修改建议（不通过时）
    quality_score: int = 0       # 质量评分 1-5
