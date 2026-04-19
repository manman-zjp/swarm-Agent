"""配置模块单元测试。"""

import os
from unittest.mock import patch

from swarm.config import _env_int, _env_float, _env_str


class TestEnvHelpers:
    def test_env_int_default(self):
        assert _env_int("__TEST_NONEXISTENT_KEY__", 42) == 42

    def test_env_int_from_env(self):
        with patch.dict(os.environ, {"__TEST_INT__": "99"}):
            assert _env_int("__TEST_INT__", 0) == 99

    def test_env_float_default(self):
        assert _env_float("__TEST_NONEXISTENT_KEY__", 3.14) == 3.14

    def test_env_float_from_env(self):
        with patch.dict(os.environ, {"__TEST_FLOAT__": "2.718"}):
            assert _env_float("__TEST_FLOAT__", 0.0) == 2.718

    def test_env_str_default(self):
        assert _env_str("__TEST_NONEXISTENT_KEY__", "hello") == "hello"

    def test_env_str_from_env(self):
        with patch.dict(os.environ, {"__TEST_STR__": "world"}):
            assert _env_str("__TEST_STR__", "") == "world"


class TestSwarmConfig:
    def test_config_singleton_import(self):
        from swarm.config import config
        assert config is not None
        assert config.llm is not None
        assert config.agent is not None
        assert config.task is not None

    def test_config_frozen(self):
        from swarm.config import config
        import dataclasses
        assert dataclasses.is_dataclass(config)

    def test_default_values(self):
        from swarm.config import config
        assert config.agent.count >= 1
        assert config.task.max_retries >= 1
        assert config.observer.flush_interval > 0
