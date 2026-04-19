"""存储层单元测试。"""

import tempfile
from pathlib import Path

from swarm.core.models import SessionFact, SessionMemory
from swarm.core.storage import SessionStore, SQLiteSessionStore, MySQLSessionStore, PgSessionStore, create_store


class TestSQLiteSessionStore:
    """SQLite 存储后端测试。"""

    def _make_store(self, tmp_path: str) -> SQLiteSessionStore:
        db_path = str(Path(tmp_path) / "test.db")
        return create_store(f"sqlite:///{db_path}")

    def test_init_schema_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.init_schema()  # 二次调用不报错

    # ── SessionMemory ──

    def test_save_and_load_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            mem = SessionMemory(
                session_id="s1",
                summary="用户在做电商项目",
                summary_up_to_turn=3,
                total_turns=5,
            )
            store.save_memory(mem)
            loaded = store.load_memory("s1")
            assert loaded is not None
            assert loaded.session_id == "s1"
            assert loaded.summary == "用户在做电商项目"
            assert loaded.summary_up_to_turn == 3
            assert loaded.total_turns == 5

    def test_load_nonexistent_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            assert store.load_memory("not-exist") is None

    def test_upsert_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            mem = SessionMemory(session_id="s1", summary="v1", summary_up_to_turn=1, total_turns=2)
            store.save_memory(mem)
            mem.summary = "v2"
            mem.summary_up_to_turn = 3
            store.save_memory(mem)
            loaded = store.load_memory("s1")
            assert loaded.summary == "v2"
            assert loaded.summary_up_to_turn == 3

    def test_load_all_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.save_memory(SessionMemory(session_id="s1", summary="a"))
            store.save_memory(SessionMemory(session_id="s2", summary="b"))
            all_mem = store.load_all_memories()
            assert len(all_mem) == 2
            ids = {m.session_id for m in all_mem}
            assert ids == {"s1", "s2"}

    # ── SessionFact ──

    def test_save_and_load_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            facts = [
                SessionFact(session_id="s1", fact_key="tech_stack", fact_value="FastAPI", source_turn=1),
                SessionFact(session_id="s1", fact_key="database", fact_value="PostgreSQL", source_turn=2),
            ]
            store.save_facts(facts)
            loaded = store.load_facts("s1")
            assert len(loaded) == 2
            keys = {f.fact_key for f in loaded}
            assert keys == {"tech_stack", "database"}

    def test_upsert_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.save_facts([SessionFact(session_id="s1", fact_key="db", fact_value="MySQL")])
            store.save_facts([SessionFact(session_id="s1", fact_key="db", fact_value="PostgreSQL")])
            loaded = store.load_facts("s1")
            assert len(loaded) == 1
            assert loaded[0].fact_value == "PostgreSQL"

    def test_delete_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.save_facts([
                SessionFact(session_id="s1", fact_key="a", fact_value="1"),
                SessionFact(session_id="s1", fact_key="b", fact_value="2"),
            ])
            store.delete_fact("s1", "a")
            loaded = store.load_facts("s1")
            assert len(loaded) == 1
            assert loaded[0].fact_key == "b"

    def test_empty_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.save_facts([])  # 不报错
            assert store.load_facts("nonexistent") == []

    def test_facts_isolated_by_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.save_facts([
                SessionFact(session_id="s1", fact_key="a", fact_value="1"),
                SessionFact(session_id="s2", fact_key="a", fact_value="2"),
            ])
            s1_facts = store.load_facts("s1")
            s2_facts = store.load_facts("s2")
            assert len(s1_facts) == 1
            assert s1_facts[0].fact_value == "1"
            assert len(s2_facts) == 1
            assert s2_facts[0].fact_value == "2"

    # ── SessionTurn ──

    def test_save_and_load_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.save_turn("s1", 1, "你好", "你好！有什么可以帮忙的？", "done", "t-001")
            store.save_turn("s1", 2, "天气如何", "今天天气不错", "done", "t-002")
            turns = store.load_turns("s1")
            assert len(turns) == 2
            assert turns[0]["turn_index"] == 1
            assert turns[0]["action"] == "你好"
            assert turns[0]["output_text"] == "你好！有什么可以帮忙的？"
            assert turns[0]["task_id"] == "t-001"
            assert turns[1]["turn_index"] == 2

    def test_upsert_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.save_turn("s1", 1, "你好", "旧回复", "done", "t-001")
            store.save_turn("s1", 1, "你好", "新回复", "done", "t-001")
            turns = store.load_turns("s1")
            assert len(turns) == 1
            assert turns[0]["output_text"] == "新回复"

    def test_load_turns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            assert store.load_turns("not-exist") == []

    def test_turns_isolated_by_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.save_turn("s1", 1, "msg1", "out1", "done")
            store.save_turn("s2", 1, "msg2", "out2", "done")
            assert len(store.load_turns("s1")) == 1
            assert len(store.load_turns("s2")) == 1
            assert store.load_turns("s1")[0]["action"] == "msg1"

    def test_load_all_session_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.save_turn("s1", 1, "a", "b", "done")
            store.save_turn("s2", 1, "c", "d", "done")
            store.save_turn("s1", 2, "e", "f", "done")
            ids = store.load_all_session_ids()
            assert set(ids) == {"s1", "s2"}

    def test_load_all_session_ids_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            assert store.load_all_session_ids() == []


class TestCreateStore:
    def test_sqlite_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            store = create_store(f"sqlite:///{db_path}")
            assert isinstance(store, SQLiteSessionStore)

    def test_invalid_url_raises(self):
        try:
            create_store("redis://localhost")
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass

    def test_mysql_not_installed_raises_import_error(self):
        """MySQL 后端已实现，但未安装 pymysql 时报 ImportError。"""
        # 如果当前环境没装 pymysql，应报 ImportError
        # 如果已安装，则会尝试连接（连接失败也算正常）
        try:
            import pymysql  # noqa: F401
            # pymysql 已安装，跳过此测试
        except ImportError:
            try:
                create_store("mysql://root:pass@localhost/testdb")
                assert False, "应该抛出 ImportError"
            except ImportError:
                pass

    def test_pgsql_not_installed_raises_import_error(self):
        """PostgreSQL 后端已实现，但未安装 psycopg2 时报 ImportError。"""
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            try:
                create_store("postgresql://user:pass@localhost/testdb")
                assert False, "应该抛出 ImportError"
            except ImportError:
                pass

    def test_mysql_store_class_exists(self):
        """验证 MySQLSessionStore 类已实现。"""
        assert MySQLSessionStore is not None
        assert issubclass(MySQLSessionStore, SessionStore)

    def test_pg_store_class_exists(self):
        """验证 PgSessionStore 类已实现。"""
        assert PgSessionStore is not None
        assert issubclass(PgSessionStore, SessionStore)
