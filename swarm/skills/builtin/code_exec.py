"""代码执行技能：在本地子进程中执行 Python / Shell 代码。"""

from __future__ import annotations

import asyncio
from typing import Any

from swarm.skills.base import BaseSkill
from swarm.config import config


class CodeExecutionSkill(BaseSkill):
    """代码执行技能，提供 execute_python 和 execute_shell 两个工具。"""

    @property
    def name(self) -> str:
        return "code_execution"

    @property
    def description(self) -> str:
        return "在本地执行 Python 代码或 Shell 命令，获取运行结果"

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "execute_python",
                    "description": "执行 Python 代码。必须用 print() 输出结果。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "要执行的 Python 代码",
                            }
                        },
                        "required": ["code"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_shell",
                    "description": "执行 Shell 命令。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "要执行的 Shell 命令",
                            }
                        },
                        "required": ["command"],
                    },
                },
            },
        ]

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "execute_python":
            code = args.get("code", "")
            return await self._run_local(["python3", "-u", "-c", code])
        elif tool_name == "execute_shell":
            command = args.get("command", "")
            return await self._run_local(["bash", "-c", command])
        return f"未知工具: {tool_name}"

    @staticmethod
    async def _run_local(cmd: list[str], timeout: float | None = None) -> str:
        """在本地子进程中执行命令。"""
        _timeout = timeout if timeout is not None else config.code_exec.timeout
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_timeout,
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
            if proc.returncode == 0:
                return f"执行成功:\n{stdout}" if stdout else "执行成功（无输出）"
            else:
                return f"执行失败 (code={proc.returncode}):\nstdout: {stdout}\nstderr: {stderr}"
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"执行超时（{_timeout}秒），已强制终止。"
