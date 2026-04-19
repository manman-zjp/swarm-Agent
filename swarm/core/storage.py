"""会话记忆持久化存储层。

基于 SQLAlchemy Engine 统一管理连接池，支持 SQLite / MySQL / PostgreSQL。
用户通过 SESSION_DB_URL 配置选择后端，无需关心连接管理。

存储内容：SessionMemory（滚动摘要）+ SessionFact（KV 事实）+ SessionTurn（对话历史）。

使用方式：
    store = create_store("sqlite:///swarm/data/sessions.db")
    store.save_memory(memory)
    facts = store.load_facts("session-abc")
    turns = store.load_turns("session-abc")
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from swarm.core.models import SessionFact, SessionMemory

logger = logging.getLogger("swarm.storage")


# ── 抽象接口 ───────────────────────────────────────


class SessionStore(ABC):
    """会话存储抽象基类。"""

    @abstractmethod
    def init_schema(self) -> None:
        """初始化数据库表结构（幂等）。"""

    # ── SessionMemory ──

    @abstractmethod
    def save_memory(self, memory: SessionMemory) -> None:
        """保存或更新会话滚动摘要。"""

    @abstractmethod
    def load_memory(self, session_id: str) -> SessionMemory | None:
        """加载指定会话的滚动摘要。"""

    @abstractmethod
    def load_all_memories(self) -> list[SessionMemory]:
        """加载所有会话摘要（启动时预热）。"""

    # ── SessionFact ──

    @abstractmethod
    def save_facts(self, facts: list[SessionFact]) -> None:
        """批量保存事实（UPSERT 语义：同 session_id + fact_key 则更新）。"""

    @abstractmethod
    def load_facts(self, session_id: str) -> list[SessionFact]:
        """加载指定会话的全部事实。"""

    @abstractmethod
    def delete_fact(self, session_id: str, fact_key: str) -> None:
        """删除指定事实。"""

    # ── SessionTurn（对话历史） ──

    @abstractmethod
    def save_turn(self, session_id: str, turn_index: int,
                  action: str, output_text: str, status: str,
                  task_id: str = "") -> None:
        """保存一轮对话（UPSERT：同 session_id + turn_index 则更新）。"""

    @abstractmethod
    def load_turns(self, session_id: str) -> list[dict]:
        """加载指定会话的全部对话轮次（按 turn_index 排序）。"""

    @abstractmethod
    def load_all_session_ids(self) -> list[str]:
        """加载所有有对话记录的 session_id（去重）。"""


# ── SQLAlchemy 统一实现 ──────────────────────────────


# DDL 模板：SQLite/PostgreSQL 通用
_DDL_STANDARD = """
CREATE TABLE IF NOT EXISTS session_memories (
    session_id          VARCHAR(64) PRIMARY KEY,
    summary             TEXT NOT NULL DEFAULT '',
    summary_up_to_turn  INTEGER NOT NULL DEFAULT 0,
    total_turns         INTEGER NOT NULL DEFAULT 0,
    created_at          VARCHAR(32) NOT NULL,
    updated_at          VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS session_facts (
    session_id   VARCHAR(64) NOT NULL,
    fact_key     VARCHAR(128) NOT NULL,
    fact_value   TEXT NOT NULL DEFAULT '',
    source_turn  INTEGER NOT NULL DEFAULT 0,
    created_at   VARCHAR(32) NOT NULL,
    updated_at   VARCHAR(32) NOT NULL,
    PRIMARY KEY (session_id, fact_key)
);

CREATE INDEX IF NOT EXISTS idx_facts_session ON session_facts(session_id);

CREATE TABLE IF NOT EXISTS session_turns (
    session_id   VARCHAR(64) NOT NULL,
    turn_index   INTEGER NOT NULL,
    task_id      VARCHAR(64) NOT NULL DEFAULT '',
    action       TEXT NOT NULL DEFAULT '',
    output_text  TEXT NOT NULL DEFAULT '',
    status       VARCHAR(32) NOT NULL DEFAULT 'done',
    created_at   VARCHAR(32) NOT NULL,
    updated_at   VARCHAR(32) NOT NULL,
    PRIMARY KEY (session_id, turn_index)
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON session_turns(session_id);
"""

# MySQL DDL（ENGINE + CHARSET + LONGTEXT）
_DDL_MYSQL = [
    """
    CREATE TABLE IF NOT EXISTS session_memories (
        session_id          VARCHAR(64) PRIMARY KEY,
        summary             TEXT NOT NULL,
        summary_up_to_turn  INT NOT NULL DEFAULT 0,
        total_turns         INT NOT NULL DEFAULT 0,
        created_at          VARCHAR(32) NOT NULL,
        updated_at          VARCHAR(32) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS session_facts (
        session_id   VARCHAR(64) NOT NULL,
        fact_key     VARCHAR(128) NOT NULL,
        fact_value   TEXT NOT NULL,
        source_turn  INT NOT NULL DEFAULT 0,
        created_at   VARCHAR(32) NOT NULL,
        updated_at   VARCHAR(32) NOT NULL,
        PRIMARY KEY (session_id, fact_key),
        INDEX idx_facts_session (session_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS session_turns (
        session_id   VARCHAR(64) NOT NULL,
        turn_index   INT NOT NULL,
        task_id      VARCHAR(64) NOT NULL DEFAULT '',
        action       TEXT NOT NULL,
        output_text  LONGTEXT NOT NULL,
        status       VARCHAR(32) NOT NULL DEFAULT 'done',
        created_at   VARCHAR(32) NOT NULL,
        updated_at   VARCHAR(32) NOT NULL,
        PRIMARY KEY (session_id, turn_index),
        INDEX idx_turns_session (session_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

# UPSERT 模板 —— MySQL 用 ON DUPLICATE KEY UPDATE，SQLite/PgSQL 用 ON CONFLICT
_UPSERT_MEMORY_STD = """
INSERT INTO session_memories
    (session_id, summary, summary_up_to_turn, total_turns, created_at, updated_at)
VALUES (:sid, :summary, :up_to, :total, :created, :updated)
ON CONFLICT(session_id) DO UPDATE SET
    summary = excluded.summary,
    summary_up_to_turn = excluded.summary_up_to_turn,
    total_turns = excluded.total_turns,
    updated_at = excluded.updated_at
"""

_UPSERT_MEMORY_MYSQL = """
INSERT INTO session_memories
    (session_id, summary, summary_up_to_turn, total_turns, created_at, updated_at)
VALUES (:sid, :summary, :up_to, :total, :created, :updated)
ON DUPLICATE KEY UPDATE
    summary = VALUES(summary),
    summary_up_to_turn = VALUES(summary_up_to_turn),
    total_turns = VALUES(total_turns),
    updated_at = VALUES(updated_at)
"""

_UPSERT_FACT_STD = """
INSERT INTO session_facts
    (session_id, fact_key, fact_value, source_turn, created_at, updated_at)
VALUES (:sid, :fkey, :fval, :turn, :created, :updated)
ON CONFLICT(session_id, fact_key) DO UPDATE SET
    fact_value = excluded.fact_value,
    source_turn = excluded.source_turn,
    updated_at = excluded.updated_at
"""

_UPSERT_FACT_MYSQL = """
INSERT INTO session_facts
    (session_id, fact_key, fact_value, source_turn, created_at, updated_at)
VALUES (:sid, :fkey, :fval, :turn, :created, :updated)
ON DUPLICATE KEY UPDATE
    fact_value = VALUES(fact_value),
    source_turn = VALUES(source_turn),
    updated_at = VALUES(updated_at)
"""

_UPSERT_TURN_STD = """
INSERT INTO session_turns
    (session_id, turn_index, task_id, action, output_text, status, created_at, updated_at)
VALUES (:sid, :tidx, :task_id, :action, :output, :status, :created, :updated)
ON CONFLICT(session_id, turn_index) DO UPDATE SET
    task_id = excluded.task_id,
    action = excluded.action,
    output_text = excluded.output_text,
    status = excluded.status,
    updated_at = excluded.updated_at
"""

_UPSERT_TURN_MYSQL = """
INSERT INTO session_turns
    (session_id, turn_index, task_id, action, output_text, status, created_at, updated_at)
VALUES (:sid, :tidx, :task_id, :action, :output, :status, :created, :updated)
ON DUPLICATE KEY UPDATE
    task_id = VALUES(task_id),
    action = VALUES(action),
    output_text = VALUES(output_text),
    status = VALUES(status),
    updated_at = VALUES(updated_at)
"""


class SQLAlchemySessionStore(SessionStore):
    """基于 SQLAlchemy Engine 的统一存储实现。

    内置连接池（QueuePool），支持 SQLite / MySQL / PostgreSQL。
    - SQLite:      StaticPool，单连接复用（文件数据库特性）
    - MySQL/PgSQL: QueuePool，pool_size + max_overflow 控制并发
    - pool_pre_ping=True，自动检测并替换失效连接
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._is_mysql = engine.dialect.name == "mysql"

    def init_schema(self) -> None:
        with self._engine.begin() as conn:
            if self._is_mysql:
                for ddl in _DDL_MYSQL:
                    conn.execute(text(ddl))
            else:
                # SQLite 和 PostgreSQL 共用标准 DDL
                for stmt in _DDL_STANDARD.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(text(stmt))
        pool = self._engine.pool
        pool_info = f"pool_size={pool.size()}" if hasattr(pool, "size") else "StaticPool"
        logger.info(f"[存储] {self._engine.dialect.name} 初始化完成 | {pool_info} | {self._engine.url}")

    # ── SessionMemory ──

    def save_memory(self, memory: SessionMemory) -> None:
        now = datetime.now().isoformat()
        sql = _UPSERT_MEMORY_MYSQL if self._is_mysql else _UPSERT_MEMORY_STD
        with self._engine.begin() as conn:
            conn.execute(text(sql), {
                "sid": memory.session_id,
                "summary": memory.summary,
                "up_to": memory.summary_up_to_turn,
                "total": memory.total_turns,
                "created": memory.created_at.isoformat(),
                "updated": now,
            })

    def load_memory(self, session_id: str) -> SessionMemory | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM session_memories WHERE session_id = :sid"),
                {"sid": session_id},
            ).mappings().fetchone()
        if not row:
            return None
        return self._row_to_memory(row)

    def load_all_memories(self) -> list[SessionMemory]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM session_memories")
            ).mappings().fetchall()
        return [self._row_to_memory(r) for r in rows]

    # ── SessionFact ──

    def save_facts(self, facts: list[SessionFact]) -> None:
        if not facts:
            return
        now = datetime.now().isoformat()
        sql = _UPSERT_FACT_MYSQL if self._is_mysql else _UPSERT_FACT_STD
        params = [
            {
                "sid": f.session_id, "fkey": f.fact_key, "fval": f.fact_value,
                "turn": f.source_turn, "created": f.created_at.isoformat(), "updated": now,
            }
            for f in facts
        ]
        with self._engine.begin() as conn:
            for p in params:
                conn.execute(text(sql), p)

    def load_facts(self, session_id: str) -> list[SessionFact]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM session_facts WHERE session_id = :sid ORDER BY source_turn"),
                {"sid": session_id},
            ).mappings().fetchall()
        return [self._row_to_fact(r) for r in rows]

    def delete_fact(self, session_id: str, fact_key: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM session_facts WHERE session_id = :sid AND fact_key = :fkey"),
                {"sid": session_id, "fkey": fact_key},
            )

    # ── SessionTurn ──

    def save_turn(self, session_id: str, turn_index: int,
                  action: str, output_text: str, status: str,
                  task_id: str = "") -> None:
        now = datetime.now().isoformat()
        sql = _UPSERT_TURN_MYSQL if self._is_mysql else _UPSERT_TURN_STD
        with self._engine.begin() as conn:
            conn.execute(text(sql), {
                "sid": session_id, "tidx": turn_index, "task_id": task_id,
                "action": action, "output": output_text, "status": status,
                "created": now, "updated": now,
            })

    def load_turns(self, session_id: str) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM session_turns WHERE session_id = :sid ORDER BY turn_index"),
                {"sid": session_id},
            ).mappings().fetchall()
        return [dict(r) for r in rows]

    def load_all_session_ids(self) -> list[str]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT session_id FROM session_turns ORDER BY session_id")
            ).fetchall()
        return [r[0] for r in rows]

    # ── 内部方法 ──

    @staticmethod
    def _row_to_memory(row) -> SessionMemory:
        return SessionMemory(
            session_id=row["session_id"],
            summary=row["summary"],
            summary_up_to_turn=row["summary_up_to_turn"],
            total_turns=row["total_turns"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_fact(row) -> SessionFact:
        return SessionFact(
            session_id=row["session_id"],
            fact_key=row["fact_key"],
            fact_value=row["fact_value"],
            source_turn=row["source_turn"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


# ── 向后兼容别名 ────────────────────────────────────

# 旧类名指向统一实现，避免已有 import 报错
SQLiteSessionStore = SQLAlchemySessionStore
MySQLSessionStore = SQLAlchemySessionStore
PgSessionStore = SQLAlchemySessionStore


# ── 工厂函数 ─────────────────────────────────────


def create_store(
    db_url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_recycle: int = 3600,
) -> SessionStore:
    """根据 db_url 创建对应的存储后端，内置连接池，开箱即用。

    支持格式：
    - sqlite:///path/to/db.db            → StaticPool（无额外依赖）
    - mysql+pymysql://user:pass@host/db  → QueuePool（需 pip install pymysql）
    - postgresql://user:pass@host/db     → QueuePool（需 pip install psycopg2-binary）

    连接池参数（仅 MySQL/PostgreSQL 生效）：
    - pool_size:     连接池常驻连接数（默认 5）
    - max_overflow:  超出 pool_size 后允许的最大临时连接数（默认 10）
    - pool_recycle:  连接回收时间/秒，防止被数据库服务端超时断开（默认 3600）
    """
    engine_kwargs: dict = {
        "pool_pre_ping": True,  # 使用前检测连接存活，自动替换失效连接
    }

    if db_url.startswith("sqlite"):
        # SQLite 文件数据库：确保目录存在
        db_path = db_url.replace("sqlite:///", "")
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # SQLite 使用 StaticPool（单连接复用），不需要连接池参数
        from sqlalchemy.pool import StaticPool
        engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    elif db_url.startswith("mysql"):
        # 自动补全驱动后缀
        if db_url.startswith("mysql://"):
            db_url = db_url.replace("mysql://", "mysql+pymysql://", 1)
        try:
            import pymysql  # noqa: F401
        except ImportError:
            raise ImportError(
                "使用 MySQL 后端需安装 pymysql：\n"
                "  pip install 'swarm-agent[mysql]'\n"
                "  或 pip install pymysql"
            )
        engine_kwargs["pool_size"] = pool_size
        engine_kwargs["max_overflow"] = max_overflow
        engine_kwargs["pool_recycle"] = pool_recycle

    elif db_url.startswith("postgresql") or db_url.startswith("postgres://"):
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            raise ImportError(
                "使用 PostgreSQL 后端需安装 psycopg2：\n"
                "  pip install 'swarm-agent[pgsql]'\n"
                "  或 pip install psycopg2-binary"
            )
        engine_kwargs["pool_size"] = pool_size
        engine_kwargs["max_overflow"] = max_overflow
        engine_kwargs["pool_recycle"] = pool_recycle

    else:
        raise ValueError(
            f"不支持的数据库 URL: {db_url}\n"
            f"支持的格式：\n"
            f"  - sqlite:///path/to/db.db\n"
            f"  - mysql://user:pass@host:3306/dbname\n"
            f"  - postgresql://user:pass@host:5432/dbname"
        )

    engine = create_engine(db_url, **engine_kwargs)
    store = SQLAlchemySessionStore(engine)
    store.init_schema()
    return store
