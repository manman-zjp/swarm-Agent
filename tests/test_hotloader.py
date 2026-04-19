"""技能热插拔管理器单元测试。"""

import tempfile
import textwrap
from pathlib import Path

from swarm.skills.base import BaseSkill
from swarm.skills.hotloader import SkillHotLoader
from swarm.skills.registry import SkillRegistry


class TestSkillHotLoader:
    """技能热插拔管理器测试。"""

    def _make_registry(self) -> SkillRegistry:
        return SkillRegistry()

    def _make_hotloader(self, watch_dir: str, auto_scan: bool = True) -> SkillHotLoader:
        registry = self._make_registry()
        return SkillHotLoader(registry=registry, watch_dir=watch_dir, auto_scan=auto_scan)

    def test_scan_and_load_existing_skills(self):
        """测试初始扫描能自动加载 builtin 目录中的技能。"""
        hotloader = self._make_hotloader("swarm/skills/builtin")
        count = hotloader.start()
        assert count >= 2  # code_exec + task_ops
        assert hotloader._registry.skill_count >= 2
        hotloader.stop()

    def test_load_module_manually(self):
        """测试手动加载指定模块。"""
        registry = self._make_registry()
        hotloader = SkillHotLoader(registry=registry, watch_dir=".", auto_scan=False)
        skill_name = hotloader.load_module("swarm.skills.builtin.task_ops")
        assert skill_name == "task_ops"
        assert "task_ops" in registry._skills

    def test_reload_skill(self):
        """测试热重载技能。"""
        hotloader = self._make_hotloader("swarm/skills/builtin")
        hotloader.start()
        success = hotloader.reload_skill("task_ops")
        assert success is True
        assert "task_ops" in hotloader._registry._skills
        hotloader.stop()

    def test_unregister_skill(self):
        """测试注销技能。"""
        hotloader = self._make_hotloader("swarm/skills/builtin")
        hotloader.start()
        hotloader._registry.unregister("task_ops")
        assert "task_ops" not in hotloader._registry._skills
        assert hotloader._registry.skill_count >= 1  # code_execution still there
        hotloader.stop()

    def test_load_nonexistent_module(self):
        """测试加载不存在的模块返回 None。"""
        hotloader = self._make_hotloader(".", auto_scan=False)
        result = hotloader.load_module("nonexistent.module")
        assert result is None

    def test_get_loaded_modules(self):
        """测试获取已加载模块列表。"""
        hotloader = self._make_hotloader("swarm/skills/builtin")
        hotloader.start()
        modules = hotloader.get_loaded_modules()
        assert len(modules) >= 2
        assert any("task_ops" in m for m in modules)
        hotloader.stop()

    def test_hotloader_discovers_skill_subclasses(self):
        """验证热加载器能自动发现 BaseSkill 子类。"""
        registry = self._make_registry()
        # 使用已有的 builtin 目录，只测试自动发现机制
        hotloader = SkillHotLoader(registry=registry, watch_dir="swarm/skills/builtin", auto_scan=True)
        count = hotloader.start()
        assert count >= 2  # code_exec + task_ops
        # 验证自动发现了 BaseSkill 子类
        assert "code_execution" in registry._skills
        assert "task_ops" in registry._skills
        hotloader.stop()

    def test_file_delete_unloads_skill(self):
        """测试删除文件会注销对应技能。"""
        hotloader = self._make_hotloader("swarm/skills/builtin")
        hotloader.start()
        assert "task_ops" in hotloader._registry._skills

        # 模拟删除 - 使用绝对路径
        task_ops_path = Path("swarm/skills/builtin/task_ops.py").resolve()
        hotloader._unload_skill_file(task_ops_path)
        assert "task_ops" not in hotloader._registry._skills

        # 恢复：重新加载
        hotloader._load_skill_file(task_ops_path)
        assert "task_ops" in hotloader._registry._skills
        hotloader.stop()
