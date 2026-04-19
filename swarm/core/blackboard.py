"""黑板系统（内存版）。

系统唯一的共享空间，存储任务数据和集体知识。
所有操作通过 asyncio.Lock 保证原子性（CAS 语义）。
生产环境可替换为 Redis 实现。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from swarm.core.models import (
    Task, TaskStatus, TaskType,
    Skill, Pattern, Lesson,
)
from swarm.config import config

logger = logging.getLogger("swarm.blackboard")

# 观测日志目录
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
EVENTS_FILE = LOG_DIR / "task_events.jsonl"
SNAPSHOT_FILE = DATA_DIR / "board_snapshot.json"
SKILLS_FILE = DATA_DIR / "skills.json"
PATTERNS_FILE = DATA_DIR / "patterns.json"
LESSONS_FILE = DATA_DIR / "lessons.json"


def _serialize_dt(obj: Any) -> Any:
    """JSON 序列化 datetime。"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class Blackboard:
    """内存黑板，asyncio 安全。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # 任务存储
        self._tasks: dict[str, Task] = {}
        # 索引：parent_id -> 子任务id列表
        self._children_index: dict[str, list[str]] = {}
        # 索引：session_id -> 根任务id列表
        self._session_index: dict[str, list[str]] = {}
        # 集体知识（从磁盘加载）
        self._skills: list[Skill] = self._load_skills()
        self._patterns: list[Pattern] = self._load_patterns()
        self._lessons: list[Lesson] = self._load_lessons()
        # 事件通知：有新的 pending 任务时 set
        self._task_available = asyncio.Event()
        # 任务完成回调：task_id -> Future
        self._completion_futures: dict[str, asyncio.Future] = {}
        logger.info(
            f"[黑板] 知识加载完成: {len(self._skills)} 技能, "
            f"{len(self._patterns)} 模式, {len(self._lessons)} 经验"
        )

    # ── 任务管理 ──────────────────────────────────────

    async def add_task(self, task: Task) -> Task:
        """添加任务到黑板。"""
        async with self._lock:
            self._tasks[task.task_id] = task
            self._index_task(task)
            self._task_available.set()
            self._log_event(task, "task_added", {})
            logger.info(f"[黑板] 新任务: {task.task_id} | {task.action[:50]}")
        return task

    async def create_root_task(
        self, action: str, session_id: str, turn_index: int = 1,
        context_refs: list[str] | None = None,
    ) -> tuple[Task, asyncio.Future]:
        """创建根任务并返回完成 Future，用于 HTTP 等待。"""
        task = Task(
            action=action,
            session_id=session_id,
            turn_index=turn_index,
            context_refs=context_refs or [],
        )
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        async with self._lock:
            self._tasks[task.task_id] = task
            self._index_task(task)
            self._completion_futures[task.task_id] = future
            self._task_available.set()
            self._log_event(task, "task_added", {"is_root": True})
        logger.info(f"[黑板] 根任务: {task.task_id} | session={session_id}")
        return task, future

    async def claim_pending(self, agent_id: str) -> Task | None:
        """尝试领取一个 pending 任务（CAS 语义）。"""
        async with self._lock:
            # 按优先级排序，优先领取高优先级任务
            candidates = [
                t for t in self._tasks.values() if t.is_claimable()
            ]
            if not candidates:
                self._task_available.clear()
                return None
            candidates.sort(key=lambda t: (-t.priority, t.created_at))
            task = candidates[0]
            task.claim(agent_id)
            self._log_event(task, "claimed", {"agent_id": agent_id})
            logger.info(f"[黑板] {agent_id} 领取: {task.task_id}")
            return task

    async def decompose(
        self, parent: Task, subtask_actions: list[str], source: str = "scratch",
    ) -> list[Task]:
        """将任务拆分为子任务。"""
        subtasks = []
        async with self._lock:
            parent.status = TaskStatus.DECOMPOSED
            parent.decompose_source = source
            parent.updated_at = datetime.now()
            for i, action in enumerate(subtask_actions):
                sub = Task(
                    action=action,
                    parent_id=parent.task_id,
                    session_id=parent.session_id,
                    priority=parent.priority,
                )
                self._tasks[sub.task_id] = sub
                self._index_task(sub)
                subtasks.append(sub)
            self._task_available.set()
            self._log_event(parent, "decomposed", {
                "subtask_ids": [s.task_id for s in subtasks],
                "source": source,
            })
        logger.info(
            f"[黑板] {parent.task_id} 拆分为 {len(subtasks)} 个子任务"
        )
        return subtasks

    async def submit_result(
        self,
        task: Task,
        output_text: str,
        lessons: list[dict] | None = None,
    ) -> None:
        """提交任务结果。"""
        async with self._lock:
            task.status = TaskStatus.DONE
            task.output_text = output_text
            task.lessons_extracted = lessons or []
            task.updated_at = datetime.now()

            # 保存经验教训到集体知识
            for les in (lessons or []):
                self._lessons.append(Lesson(
                    context=les.get("context", ""),
                    lesson=les.get("lesson", ""),
                    source_task=task.task_id,
                ))
            if lessons:
                self._save_lessons()

            self._log_event(task, "done", {"has_lessons": bool(lessons)})
            logger.info(f"[黑板] 任务完成: {task.task_id}")

            # 检查父任务是否所有子任务都完成了
            if task.parent_id:
                await self._check_parent_completion(task.parent_id)
            # 检查是否有等待这个任务完成的 Future
            self._resolve_future(task.task_id)

    async def mark_failed(self, task: Task, reason: str = "") -> None:
        """标记任务失败。"""
        async with self._lock:
            task.status = TaskStatus.FAILED
            task.updated_at = datetime.now()
            self._log_event(task, "failed", {"reason": reason})
            logger.warning(f"[黑板] 任务失败: {task.task_id} | {reason}")
            if task.parent_id:
                await self._check_parent_completion(task.parent_id)
            self._resolve_future(task.task_id)

    async def _check_parent_completion(self, parent_id: str) -> None:
        """检查父任务的所有子任务是否完成（已持有锁）。"""
        child_ids = self._children_index.get(parent_id, [])
        children = [self._tasks[cid] for cid in child_ids if cid in self._tasks]
        if not children:
            return
        all_done = all(
            t.status in (TaskStatus.DONE, TaskStatus.FAILED) for t in children
        )
        if all_done:
            parent = self._tasks.get(parent_id)
            if parent and parent.status == TaskStatus.DECOMPOSED:
                parent.status = TaskStatus.DONE
                # 汇总子任务产出
                outputs = []
                for child in children:
                    if child.output_text:
                        outputs.append(f"【{child.action[:30]}】\n{child.output_text}")
                parent.output_text = "\n\n---\n\n".join(outputs)
                parent.updated_at = datetime.now()
                self._log_event(parent, "auto_done", {
                    "child_count": len(children),
                })
                logger.info(f"[黑板] 父任务自动完成: {parent_id}")
                # 递归检查更上层的父任务
                if parent.parent_id:
                    await self._check_parent_completion(parent.parent_id)
                self._resolve_future(parent_id)

    def _resolve_future(self, task_id: str) -> None:
        """完成等待中的 Future（已持有锁）。"""
        future = self._completion_futures.pop(task_id, None)
        if future and not future.done():
            task = self._tasks[task_id]
            future.set_result(task)

    async def wait_for_task(self, timeout: float = 30.0) -> None:
        """等待新任务出现。"""
        try:
            await asyncio.wait_for(self._task_available.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    # ── 集体知识查询 ─────────────────────────────────

    def query_knowledge(self, task: Task) -> dict[str, Any]:
        """查询与任务相关的集体知识（技能 > 模式 > 教训）。"""
        action_lower = task.action.lower()
        result: dict[str, Any] = {
            "skill": None, "pattern": None, "lessons": [],
        }
        # 查技能
        for skill in self._skills:
            if skill.status == "active" and skill.confidence >= config.knowledge.skill_min_confidence:
                if skill.trigger.lower() in action_lower or action_lower in skill.trigger.lower():
                    result["skill"] = skill
                    break
        # 查拆分模式
        if not result["skill"]:
            for pattern in self._patterns:
                if pattern.confidence >= config.knowledge.pattern_min_confidence:
                    if pattern.trigger.lower() in action_lower:
                        result["pattern"] = pattern
                        break
        # 查经验教训（关键词匹配，只返回相关的）
        for lesson in self._lessons:
            if lesson.confidence >= config.knowledge.lesson_min_confidence:
                ctx = lesson.context.lower()
                les = lesson.lesson.lower()
                if ctx in action_lower or action_lower in ctx or any(
                    word in les for word in action_lower.split()[:5] if len(word) > 1
                ):
                    result["lessons"].append(lesson)
        return result

    def add_skill(self, skill: Skill) -> None:
        self._skills.append(skill)
        self._save_skills()

    def add_pattern(self, pattern: Pattern) -> None:
        self._patterns.append(pattern)
        self._save_patterns()

    # ── 会话查询 ──────────────────────────────────────

    def get_session_history(self, session_id: str, max_turns: int = 3) -> list[Task]:
        """获取会话历史（最近 N 轮的完成任务）。"""
        task_ids = self._session_index.get(session_id, [])
        tasks = [
            self._tasks[tid] for tid in task_ids
            if tid in self._tasks
            and self._tasks[tid].status == TaskStatus.DONE
        ]
        tasks.sort(key=lambda t: t.turn_index)
        return tasks[-max_turns:]

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def get_children(self, parent_id: str) -> list[Task]:
        child_ids = self._children_index.get(parent_id, [])
        return [self._tasks[cid] for cid in child_ids if cid in self._tasks]

    # ── 知识磁盘 I/O ───────────────────────────────

    @staticmethod
    def _load_skills() -> list[Skill]:
        if not SKILLS_FILE.exists():
            return []
        try:
            with open(SKILLS_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
            return [
                Skill(
                    skill_id=d.get("skill_id", ""),
                    name=d.get("name", ""),
                    trigger=d.get("trigger", ""),
                    description=d.get("description", ""),
                    procedure=d.get("procedure", []),
                    known_issues=d.get("known_issues", []),
                    source_tasks=d.get("source_tasks", []),
                    confidence=d.get("confidence", 0.5),
                    success_count=d.get("success_count", 0),
                    fail_count=d.get("fail_count", 0),
                    version=d.get("version", 1),
                    status=d.get("status", "active"),
                )
                for d in items
            ]
        except Exception as e:
            logger.error(f"加载 skills.json 失败: {e}")
            return []

    @staticmethod
    def _load_patterns() -> list[Pattern]:
        if not PATTERNS_FILE.exists():
            return []
        try:
            with open(PATTERNS_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
            return [
                Pattern(
                    pattern_id=d.get("pattern_id", ""),
                    trigger=d.get("trigger", ""),
                    template=d.get("template", []),
                    success_rate=d.get("success_rate", 0.5),
                    used_count=d.get("used_count", 0),
                    confidence=d.get("confidence", 0.5),
                )
                for d in items
            ]
        except Exception as e:
            logger.error(f"加载 patterns.json 失败: {e}")
            return []

    @staticmethod
    def _load_lessons() -> list[Lesson]:
        if not LESSONS_FILE.exists():
            return []
        try:
            with open(LESSONS_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
            return [
                Lesson(
                    lesson_id=d.get("lesson_id", ""),
                    context=d.get("context", ""),
                    lesson=d.get("lesson", ""),
                    source_task=d.get("source_task", ""),
                    confidence=d.get("confidence", 0.5),
                )
                for d in items
            ]
        except Exception as e:
            logger.error(f"加载 lessons.json 失败: {e}")
            return []

    def _save_skills(self) -> None:
        try:
            with open(SKILLS_FILE, "w", encoding="utf-8") as f:
                json.dump([self._skill_to_dict(s) for s in self._skills], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存 skills.json 失败: {e}")

    def _save_patterns(self) -> None:
        try:
            with open(PATTERNS_FILE, "w", encoding="utf-8") as f:
                json.dump([self._pattern_to_dict(p) for p in self._patterns], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存 patterns.json 失败: {e}")

    def _save_lessons(self) -> None:
        try:
            with open(LESSONS_FILE, "w", encoding="utf-8") as f:
                json.dump([self._lesson_to_dict(l) for l in self._lessons], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存 lessons.json 失败: {e}")

    # ── 快照与序列化 ─────────────────────────────────

    def snapshot(self) -> dict:
        """生成黑板完整快照（用于可观测 API 和持久化）。"""
        status_counts = {}
        for t in self._tasks.values():
            s = t.status.value
            status_counts[s] = status_counts.get(s, 0) + 1

        sessions = {}
        for t in self._tasks.values():
            if t.session_id and t.parent_id is None:
                sessions.setdefault(t.session_id, []).append(t.turn_index)

        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_tasks": len(self._tasks),
                "status_counts": status_counts,
                "total_skills": len(self._skills),
                "total_patterns": len(self._patterns),
                "total_lessons": len(self._lessons),
                "active_sessions": len(sessions),
            },
            "tasks": {
                tid: self._task_to_dict(t) for tid, t in self._tasks.items()
            },
            "knowledge": {
                "skills": [self._skill_to_dict(s) for s in self._skills],
                "patterns": [self._pattern_to_dict(p) for p in self._patterns],
                "lessons": [self._lesson_to_dict(l) for l in self._lessons],
            },
            "sessions": {
                sid: sorted(set(turns)) for sid, turns in sessions.items()
            },
        }

    @staticmethod
    def _task_to_dict(t: Task) -> dict:
        return {
            "task_id": t.task_id,
            "action": t.action,
            "status": t.status.value,
            "task_type": t.task_type.value,
            "parent_id": t.parent_id,
            "session_id": t.session_id,
            "turn_index": t.turn_index,
            "claimed_by": t.claimed_by,
            "priority": t.priority,
            "output_text": (t.output_text[:500] + "...") if t.output_text and len(t.output_text) > 500 else t.output_text,
            "lessons_extracted": t.lessons_extracted,
            "decompose_source": t.decompose_source,
            "retry_count": t.retry_count,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
        }

    @staticmethod
    def _skill_to_dict(s: Skill) -> dict:
        return {
            "skill_id": s.skill_id, "name": s.name, "trigger": s.trigger,
            "description": s.description, "confidence": s.confidence,
            "success_count": s.success_count, "fail_count": s.fail_count,
            "version": s.version, "status": s.status,
            "source_tasks": s.source_tasks,
            "created_at": s.created_at.isoformat(),
        }

    @staticmethod
    def _pattern_to_dict(p: Pattern) -> dict:
        return {
            "pattern_id": p.pattern_id, "trigger": p.trigger,
            "template": p.template, "success_rate": p.success_rate,
            "used_count": p.used_count, "confidence": p.confidence,
            "created_at": p.created_at.isoformat(),
        }

    @staticmethod
    def _lesson_to_dict(l: Lesson) -> dict:
        return {
            "lesson_id": l.lesson_id, "context": l.context,
            "lesson": l.lesson, "source_task": l.source_task,
            "confidence": l.confidence,
            "created_at": l.created_at.isoformat(),
        }

    def _persist_snapshot(self) -> None:
        """将黑板快照持久化到 JSON 文件（每次状态变更后调用）。"""
        try:
            data = self.snapshot()
            with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=_serialize_dt)
        except Exception as e:
            logger.error(f"持久化快照失败: {e}")

    # ── 观测日志 ──────────────────────────────────────

    def _index_task(self, task: Task) -> None:
        """维护索引（已持有锁时调用）。"""
        if task.parent_id:
            self._children_index.setdefault(task.parent_id, []).append(task.task_id)
        if task.session_id and task.parent_id is None:
            self._session_index.setdefault(task.session_id, []).append(task.task_id)

    def _log_event(self, task: Task, event_type: str, metadata: dict) -> None:
        """写入任务事件日志（实时追加 JSONL）。"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "task_id": task.task_id,
            "session_id": task.session_id,
            "parent_id": task.parent_id,
            "event_type": event_type,
            "status": task.status.value,
            "agent_id": task.claimed_by,
            "action_preview": task.action[:80],
            **metadata,
        }
        try:
            with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @property
    def tasks(self):
        return self._tasks
