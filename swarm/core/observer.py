"""观测器：Agent 推理 trace 日志。

记录 Agent 三层推理的每一步，写入 JSONL 文件。
"""

from __future__ import annotations

import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("swarm.observer")

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
TRACE_FILE = LOG_DIR / "agent_trace.jsonl"
KNOWLEDGE_FILE = LOG_DIR / "knowledge_changelog.jsonl"


class Observer:
    """观测器单例。"""

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
        """写入一条 Agent 推理 trace。"""
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
        # input/output 可能很大，截断
        if input_data is not None:
            record["input"] = self._truncate(input_data)
        if output_data is not None:
            record["output"] = self._truncate(output_data)

        self._write(TRACE_FILE, record)

    def log_knowledge_change(
        self,
        knowledge_type: str,
        action: str,
        detail: dict,
    ) -> None:
        """记录知识变更。"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "knowledge_type": knowledge_type,
            "action": action,
            **detail,
        }
        self._write(KNOWLEDGE_FILE, record)

    def get_traces_by_task(self, task_id: str) -> list[dict]:
        """按 task_id 查询所有推理 trace。"""
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

    @staticmethod
    def _truncate(data: Any, max_len: int = 500) -> Any:
        """截断过长的数据。"""
        s = str(data)
        if len(s) > max_len:
            return s[:max_len] + "...(truncated)"
        return data

    @staticmethod
    def _write(filepath: Path, record: dict) -> None:
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error(f"写入观测日志失败: {e}")


# 全局单例
observer = Observer()
