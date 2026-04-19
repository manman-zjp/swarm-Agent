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

    def is_claimable(self) -> bool:
        """是否可被领取。"""
        if self.status != TaskStatus.PENDING:
            return False
        if self.claimed_by and self.claim_expires and datetime.now() < self.claim_expires:
            return False
        return True

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
class ReflectionResult:
    """第三层反思的输出。"""
    passed: bool = True
    summary: str = ""
    fix_plan: str = ""
    lessons: list[dict] = field(default_factory=list)
    skill_candidate: dict | None = None
