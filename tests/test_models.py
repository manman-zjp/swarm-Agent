"""数据模型单元测试。"""

from datetime import datetime, timedelta

from swarm.core.models import (
    Lesson,
    Pattern,
    ReflectionResult,
    SessionFact,
    SessionMemory,
    Skill,
    Task,
    TaskStatus,
    TaskType,
)


class TestTaskStatus:
    def test_enum_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.DECOMPOSED == "decomposed"

    def test_str_comparison(self):
        assert TaskStatus.PENDING == "pending"
        assert str(TaskStatus.RUNNING) == "TaskStatus.RUNNING"


class TestTask:
    def test_default_creation(self):
        task = Task()
        assert task.task_id  # non-empty
        assert task.status == TaskStatus.PENDING
        assert task.task_type == TaskType.NORMAL
        assert task.retry_count == 0
        assert isinstance(task.created_at, datetime)

    def test_is_claimable_when_pending(self):
        task = Task(status=TaskStatus.PENDING)
        assert task.is_claimable() is True

    def test_is_not_claimable_when_running(self):
        task = Task(status=TaskStatus.RUNNING)
        assert task.is_claimable() is False

    def test_claim_success(self):
        task = Task()
        result = task.claim("agent-01", ttl_seconds=60)
        assert result is True
        assert task.status == TaskStatus.RUNNING
        assert task.claimed_by == "agent-01"
        assert task.claim_expires is not None

    def test_claim_fail_when_already_claimed(self):
        task = Task()
        task.claim("agent-01", ttl_seconds=300)
        result = task.claim("agent-02", ttl_seconds=300)
        assert result is False

    def test_claim_succeeds_after_ttl_expired(self):
        task = Task(status=TaskStatus.PENDING)
        task.claimed_by = "agent-01"
        task.claim_expires = datetime.now() - timedelta(seconds=1)
        assert task.is_claimable() is True

    def test_custom_fields(self):
        task = Task(
            action="test action",
            parent_id="parent-01",
            session_id="sess-01",
            priority=5,
        )
        assert task.action == "test action"
        assert task.parent_id == "parent-01"
        assert task.session_id == "sess-01"
        assert task.priority == 5


class TestLesson:
    def test_default_creation(self):
        lesson = Lesson()
        assert lesson.lesson_id
        assert lesson.confidence == 0.5

    def test_custom_values(self):
        lesson = Lesson(context="test", lesson="learned something", confidence=0.9)
        assert lesson.context == "test"
        assert lesson.confidence == 0.9


class TestPattern:
    def test_default_creation(self):
        pattern = Pattern()
        assert pattern.pattern_id
        assert pattern.template == []
        assert pattern.success_rate == 0.5


class TestSkill:
    def test_default_creation(self):
        skill = Skill()
        assert skill.skill_id
        assert skill.status == "active"
        assert skill.version == 1


class TestReflectionResult:
    def test_default_passed(self):
        result = ReflectionResult()
        assert result.passed is True
        assert result.lessons == []

    def test_failed_reflection(self):
        result = ReflectionResult(passed=False, fix_plan="retry with different approach")
        assert result.passed is False
        assert result.fix_plan == "retry with different approach"


class TestSessionMemory:
    def test_default_creation(self):
        mem = SessionMemory()
        assert mem.session_id == ""
        assert mem.summary == ""
        assert mem.summary_up_to_turn == 0
        assert mem.total_turns == 0

    def test_with_values(self):
        mem = SessionMemory(
            session_id="sess-01",
            summary="用户在做电商项目",
            summary_up_to_turn=5,
            total_turns=8,
        )
        assert mem.session_id == "sess-01"
        assert mem.summary == "用户在做电商项目"
        assert mem.summary_up_to_turn == 5
        assert mem.total_turns == 8
        assert isinstance(mem.created_at, datetime)


class TestSessionFact:
    def test_default_creation(self):
        fact = SessionFact()
        assert fact.session_id == ""
        assert fact.fact_key == ""
        assert fact.fact_value == ""
        assert fact.source_turn == 0

    def test_with_values(self):
        fact = SessionFact(
            session_id="sess-01",
            fact_key="tech_stack",
            fact_value="FastAPI + PostgreSQL",
            source_turn=3,
        )
        assert fact.fact_key == "tech_stack"
        assert fact.fact_value == "FastAPI + PostgreSQL"
        assert fact.source_turn == 3
        assert isinstance(fact.created_at, datetime)
