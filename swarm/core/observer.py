"""观测器：Agent 推理 trace 日志。

记录 Agent 推理的每一步，通过内存队列异步批量写入 JSONL 文件，
避免同步文件 I/O 阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("swarm.observer")

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
TRACE_FILE = LOG_DIR / "agent_trace.jsonl"
KNOWLEDGE_FILE = LOG_DIR / "knowledge_changelog.jsonl"

# 刷盘间隔（秒）和每批最大条数
_FLUSH_INTERVAL = 1.0
_FLUSH_BATCH_SIZE = 50


class Observer:
    """观测器单例：内存队列 + 后台刷盘。"""

    def __init__(self) -> None:
        self._trace_queue: deque[dict] = deque()
        self._knowledge_queue: deque[dict] = deque()
        self._flush_task: asyncio.Task | None = None

    def start(self) -> None:
        """启动后台刷盘协程（在事件循环启动后调用）。"""
        if self._flush_task is None:
            self._flush_task = asyncio.ensure_future(self._flush_loop())

    async def stop(self) -> None:
        """停止刷盘并刷完剩余数据。"""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        self._do_flush()

    def trace(
        self,
        trace_id: str,
        task_id: str,
        agent_id: str,
        layer: str,
        step_seq: int,
        action: str,
        input_data: Any = None,
        output_data: Any = None,
        duration_ms: float = 0,
        token_usage: dict | None = None,
        session_id: str | None = None,
    ) -> None:
        """写入一条 Agent 推理 trace（放入队列，不阻塞）。"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "trace_id": trace_id,
            "task_id": task_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "layer": layer,
            "step_seq": step_seq,
            "action": action,
            "duration_ms": round(duration_ms, 1),
            "token_usage": token_usage,
        }
        if input_data is not None:
            record["input"] = self._truncate(input_data)
        if output_data is not None:
            record["output"] = self._truncate(output_data)
        self._trace_queue.append(record)

    def log_knowledge_change(
        self,
        knowledge_type: str,
        action: str,
        detail: dict,
    ) -> None:
        """记录知识变更（放入队列）。"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "knowledge_type": knowledge_type,
            "action": action,
            **detail,
        }
        self._knowledge_queue.append(record)

    def get_traces_by_task(self, task_id: str) -> list[dict]:
        """按 task_id 查询所有推理 trace。"""
        # 先刷盘确保数据完整
        self._do_flush()
        results = []
        try:
            with open(TRACE_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if record.get("task_id") == task_id:
                        results.append(record)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"读取 trace 日志失败: {e}")
        return results

    # ── 内部方法 ───────────────────────────────

    async def _flush_loop(self) -> None:
        """后台循环：每隔 _FLUSH_INTERVAL 秒刷盘一次。"""
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL)
            self._do_flush()

    def _do_flush(self) -> None:
        """将队列中的记录批量写入文件。"""
        self._flush_queue(self._trace_queue, TRACE_FILE)
        self._flush_queue(self._knowledge_queue, KNOWLEDGE_FILE)

    @staticmethod
    def _flush_queue(queue: deque, filepath: Path) -> None:
        """把队列内容一次性写入文件。"""
        if not queue:
            return
        lines = []
        count = 0
        while queue and count < _FLUSH_BATCH_SIZE:
            lines.append(json.dumps(queue.popleft(), ensure_ascii=False, default=str))
            count += 1
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            logger.error(f"写入观测日志失败: {e}")

    @staticmethod
    def _truncate(data: Any, max_len: int = 500) -> Any:
        """截断过长的数据。"""
        s = str(data)
        if len(s) > max_len:
            return s[:max_len] + "...(truncated)"
        return data


# 全局单例
observer = Observer()
