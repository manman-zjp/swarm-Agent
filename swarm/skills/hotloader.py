"""技能热插拔管理器。

基于 watchdog 监控技能目录，实现技能的自动发现、热加载与注册。
支持：
1. 新增 .py 文件 → 自动 import + 实例化 + 注册
2. 修改 .py 文件 → 重新 import + 重新注册（覆盖旧版本）
3. 删除 .py 文件 → 从注册表中注销

使用方式：
    hotloader = SkillHotLoader(skill_registry, watch_dir="swarm/skills/builtin")
    hotloader.start()  # 启动后台监控线程
    hotloader.stop()   # 关闭时调用
"""

from __future__ import annotations

import importlib
import inspect
import logging
import sys
from pathlib import Path
from threading import Thread
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from swarm.skills.base import BaseSkill
from swarm.skills.registry import SkillRegistry

logger = logging.getLogger("swarm.skills.hotloader")


class _SkillFileHandler(FileSystemEventHandler):
    """文件系统事件处理器：监听 .py 文件变更。"""

    def __init__(self, hotloader: "SkillHotLoader") -> None:
        self._hotloader = hotloader

    def on_created(self, event) -> None:  # noqa: ANN001
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix == ".py" and not path.name.startswith("_"):
            logger.info(f"[热插拔] 检测到新技能文件: {path.name}")
            self._hotloader._load_skill_file(path)

    def on_modified(self, event) -> None:  # noqa: ANN001
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix == ".py" and not path.name.startswith("_"):
            logger.info(f"[热插拔] 检测到技能文件修改: {path.name}")
            self._hotloader._load_skill_file(path)

    def on_deleted(self, event) -> None:  # noqa: ANN001
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix == ".py" and not path.name.startswith("_"):
            logger.info(f"[热插拔] 检测到技能文件删除: {path.name}")
            self._hotloader._unload_skill_file(path)


class SkillHotLoader:
    """技能热插拔管理器。

    职责：
    - 启动/停止 watchdog 监控线程
    - 从 .py 文件动态加载 BaseSkill 子类并注册
    - 支持手动加载指定模块
    """

    def __init__(
        self,
        registry: SkillRegistry,
        watch_dir: str,
        auto_scan: bool = True,
    ) -> None:
        self._registry = registry
        self._watch_dir = Path(watch_dir).resolve()
        self._auto_scan = auto_scan
        self._observer: Observer | None = None
        self._thread: Thread | None = None
        # 记录已加载的模块路径 → 技能名映射
        self._loaded_modules: dict[str, str] = {}  # module_name → skill_name

    def start(self) -> int:
        """启动热插拔监控。

        Returns:
            初始扫描并注册的技能数量
        """
        if not self._watch_dir.is_dir():
            logger.warning(f"[热插拔] 监控目录不存在: {self._watch_dir}")
            return 0

        loaded = 0
        if self._auto_scan:
            loaded = self._scan_and_load()
            logger.info(f"[热插拔] 初始扫描完成，已加载 {loaded} 个技能")

        # 启动 watchdog 监控线程
        event_handler = _SkillFileHandler(self)
        self._observer = Observer()
        self._observer.schedule(event_handler, str(self._watch_dir), recursive=False)
        self._observer.start()
        logger.info(f"[热插拔] 监控已启动: {self._watch_dir}")

        return loaded

    def stop(self) -> None:
        """停止热插拔监控。"""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("[热插拔] 监控已停止")

    def load_module(self, module_name: str) -> str | None:
        """手动加载指定模块中的技能。

        Args:
            module_name: 模块路径，如 "swarm.skills.builtin.my_skill"

        Returns:
            成功注册的技能名，失败返回 None
        """
        try:
            module = importlib.import_module(module_name)
            return self._register_skills_from_module(module, module_name)
        except Exception as e:
            logger.error(f"[热插拔] 加载模块 {module_name} 失败: {e}")
            return None

    def reload_skill(self, skill_name: str) -> bool:
        """重新加载指定技能（热重载）。

        Args:
            skill_name: 已注册的技能名

        Returns:
            是否成功重载
        """
        # 查找技能对应的模块
        module_name = None
        for mod_name, s_name in self._loaded_modules.items():
            if s_name == skill_name:
                module_name = mod_name
                break

        if not module_name:
            logger.warning(f"[热插拔] 未找到技能 {skill_name} 对应的模块")
            return False

        try:
            module = sys.modules.get(module_name)
            if module:
                importlib.reload(module)
                logger.info(f"[热插拔] 模块已重新加载: {module_name}")
            return self._register_skills_from_module(module, module_name) is not None
        except Exception as e:
            logger.error(f"[热插拔] 重载技能 {skill_name} 失败: {e}")
            return False

    def get_loaded_modules(self) -> list[str]:
        """获取已加载的模块列表。"""
        return list(self._loaded_modules.keys())

    # ── 内部方法 ──────────────────────────────────

    def _scan_and_load(self) -> int:
        """扫描目录下所有 .py 文件并加载。"""
        count = 0
        for py_file in sorted(self._watch_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            if self._load_skill_file(py_file):
                count += 1
        return count

    def _load_skill_file(self, file_path: Path) -> bool:
        """从文件路径推导模块名并加载。"""
        # 推导模块名：file_path → 相对路径 → 点分模块名
        try:
            # 从项目根目录推导（swarm 的父目录）
            project_root = Path(__file__).resolve().parent.parent.parent
            rel_path = file_path.resolve().relative_to(project_root)
            module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
        except ValueError:
            # 回退：尝试从当前工作目录推导
            try:
                rel_path = file_path.resolve().relative_to(Path.cwd())
                module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
            except ValueError:
                logger.error(f"[热插拔] 无法推导模块名: {file_path}")
                return False

        try:
            module = importlib.import_module(module_name)
            return self._register_skills_from_module(module, module_name) is not None
        except Exception as e:
            logger.error(f"[热插拔] 加载文件 {file_path.name} 失败: {e}")
            return False

    def _unload_skill_file(self, file_path: Path) -> None:
        """卸载文件对应的技能。"""
        try:
            project_root = Path(__file__).resolve().parent.parent.parent
            rel_path = file_path.resolve().relative_to(project_root)
            module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
        except ValueError:
            try:
                rel_path = file_path.resolve().relative_to(Path.cwd())
                module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
            except ValueError:
                logger.warning(f"[热插拔] 无法推导模块名: {file_path}")
                return

        skill_name = self._loaded_modules.pop(module_name, None)
        if skill_name:
            self._registry.unregister(skill_name)
            logger.info(f"[热插拔] 已注销技能: {skill_name}")

    def _register_skills_from_module(self, module: Any, module_name: str) -> str | None:
        """从模块中找出所有 BaseSkill 子类并注册。

        Returns:
            成功注册的第一个技能名，无技能则返回 None
        """
        registered_name = None

        # 找出模块中所有 BaseSkill 的非抽象子类
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseSkill)
                and obj is not BaseSkill
                and not inspect.isabstract(obj)
                and obj.__module__ == module.__name__  # 只处理本模块定义的类
            ):
                try:
                    skill_instance = obj()
                    # 如果该技能已存在，先注销旧版本
                    if skill_instance.name in self._registry._skills:
                        self._registry.unregister(skill_instance.name)
                        logger.info(f"[热插拔] 覆盖旧版本技能: {skill_instance.name}")

                    self._registry.register(skill_instance)
                    self._loaded_modules[module_name] = skill_instance.name
                    registered_name = skill_instance.name
                    logger.info(f"[热插拔] 注册技能: {skill_instance.name} (来自 {module_name})")
                except Exception as e:
                    logger.error(f"[热插拔] 实例化技能 {name} 失败: {e}")

        return registered_name

