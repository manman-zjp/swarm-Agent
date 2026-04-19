"""蜂群统一配置。

所有可调参数集中管理，从环境变量读取，提供合理默认值。
使用方式：from swarm.config import config
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _env_str(key: str, default: str) -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class LLMConfig:
    """LLM 调用相关配置。"""
    api_key: str = field(default_factory=lambda: _env_str("OPENAI_API_KEY", ""))
    base_url: str = field(default_factory=lambda: _env_str("OPENAI_API_BASE_URL", ""))
    model: str = field(default_factory=lambda: _env_str("MODEL_NAME", "qwen-max"))
    temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.3))
    max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 4096))
    max_tool_rounds: int = field(default_factory=lambda: _env_int("LLM_MAX_TOOL_ROUNDS", 10))
    reflection_temperature: float = field(default_factory=lambda: _env_float("LLM_REFLECTION_TEMPERATURE", 0.1))


@dataclass(frozen=True)
class AgentConfig:
    """Agent 行为配置。"""
    count: int = field(default_factory=lambda: _env_int("AGENT_COUNT", 3))
    task_wait_timeout: float = field(default_factory=lambda: _env_float("AGENT_TASK_WAIT_TIMEOUT", 10.0))
    # 反思触发阈值：工具调用次数 >= 此值，或执行耗时 > reflection_time_ms 时触发反思
    reflection_tool_threshold: int = field(default_factory=lambda: _env_int("AGENT_REFLECTION_TOOL_THRESHOLD", 2))
    reflection_time_ms: float = field(default_factory=lambda: _env_float("AGENT_REFLECTION_TIME_MS", 5000))
    # 反思时传给 LLM 的结果截断长度
    reflection_result_max_chars: int = field(default_factory=lambda: _env_int("AGENT_REFLECTION_RESULT_MAX_CHARS", 2000))


@dataclass(frozen=True)
class TaskConfig:
    """任务相关配置。"""
    chat_timeout: float = field(default_factory=lambda: _env_float("TASK_CHAT_TIMEOUT", 300.0))
    claim_ttl_seconds: int = field(default_factory=lambda: _env_int("TASK_CLAIM_TTL_SECONDS", 300))
    max_retries: int = field(default_factory=lambda: _env_int("TASK_MAX_RETRIES", 3))
    session_history_max_turns: int = field(default_factory=lambda: _env_int("TASK_SESSION_HISTORY_MAX_TURNS", 3))
    # 增量摘要配置
    summary_window_size: int = field(default_factory=lambda: _env_int("TASK_SUMMARY_WINDOW_SIZE", 3))
    summary_max_chars: int = field(default_factory=lambda: _env_int("TASK_SUMMARY_MAX_CHARS", 800))
    summary_turn_detail_chars: int = field(default_factory=lambda: _env_int("TASK_SUMMARY_TURN_DETAIL_CHARS", 500))


@dataclass(frozen=True)
class KnowledgeConfig:
    """集体知识查询阈值。"""
    skill_min_confidence: float = field(default_factory=lambda: _env_float("KNOWLEDGE_SKILL_MIN_CONFIDENCE", 0.5))
    pattern_min_confidence: float = field(default_factory=lambda: _env_float("KNOWLEDGE_PATTERN_MIN_CONFIDENCE", 0.3))
    lesson_min_confidence: float = field(default_factory=lambda: _env_float("KNOWLEDGE_LESSON_MIN_CONFIDENCE", 0.2))
    # 注入 prompt 的最大经验条数
    max_lessons_in_prompt: int = field(default_factory=lambda: _env_int("KNOWLEDGE_MAX_LESSONS_IN_PROMPT", 3))


@dataclass(frozen=True)
class ObserverConfig:
    """观测器配置。"""
    flush_interval: float = field(default_factory=lambda: _env_float("OBSERVER_FLUSH_INTERVAL", 1.0))
    flush_batch_size: int = field(default_factory=lambda: _env_int("OBSERVER_FLUSH_BATCH_SIZE", 50))
    trace_truncate_len: int = field(default_factory=lambda: _env_int("OBSERVER_TRACE_TRUNCATE_LEN", 500))


@dataclass(frozen=True)
class StorageConfig:
    """会话持久化存储配置。

    db_url 格式:
    - SQLite（默认）: sqlite:///swarm/data/sessions.db
    - MySQL:         mysql://user:pass@host:3306/swarm
    - PostgreSQL:    postgresql://user:pass@host:5432/swarm
    """
    db_url: str = field(default_factory=lambda: _env_str(
        "SESSION_DB_URL", "sqlite:///swarm/data/sessions.db",
    ))
    # 每个会话最多保留的 KV 事实条数
    fact_max_per_session: int = field(default_factory=lambda: _env_int(
        "SESSION_FACT_MAX_PER_SESSION", 50,
    ))
    # 连接池参数（仅 MySQL / PostgreSQL 生效，SQLite 使用单连接复用）
    pool_size: int = field(default_factory=lambda: _env_int("SESSION_POOL_SIZE", 5))
    pool_max_overflow: int = field(default_factory=lambda: _env_int("SESSION_POOL_MAX_OVERFLOW", 10))
    pool_recycle: int = field(default_factory=lambda: _env_int("SESSION_POOL_RECYCLE", 3600))


@dataclass(frozen=True)
class CodeExecConfig:
    """代码执行配置。"""
    timeout: float = field(default_factory=lambda: _env_float("CODE_EXEC_TIMEOUT", 120.0))


@dataclass(frozen=True)
class SwarmConfig:
    """蜂群系统顶层配置。"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    task: TaskConfig = field(default_factory=TaskConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    observer: ObserverConfig = field(default_factory=ObserverConfig)
    code_exec: CodeExecConfig = field(default_factory=CodeExecConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)


# 全局配置单例
config = SwarmConfig()
