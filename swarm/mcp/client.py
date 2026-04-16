"""MCP 客户端：连接外部 MCP 服务器，将其工具注册为技能。

配置文件: swarm/data/mcp_servers.json
格式:
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "enabled": true
    }
  ]
}

每个 MCP 服务器的工具会被包装成一个技能注册到 SkillRegistry。
"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from swarm.skills.base import BaseSkill
from swarm.skills.registry import SkillRegistry

logger = logging.getLogger("swarm.mcp")

DATA_DIR = Path(__file__).parent.parent / "data"
MCP_CONFIG_FILE = DATA_DIR / "mcp_servers.json"


class MCPServerSkill(BaseSkill):
    """包装单个 MCP 服务器的所有工具为一个技能。"""

    def __init__(
        self,
        server_name: str,
        server_description: str,
        tools: list[dict[str, Any]],
        call_tool_fn: Any,
    ) -> None:
        self._name = f"mcp_{server_name}"
        self._description = server_description
        self._tools = tools
        self._call_tool_fn = call_tool_fn

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def get_tools(self) -> list[dict[str, Any]]:
        return self._tools

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        try:
            result = await self._call_tool_fn(tool_name, args)
            return str(result)
        except Exception as e:
            return f"MCP 工具调用失败: {e}"


class MCPManager:
    """MCP 服务器管理器：读取配置，连接服务器，注册技能。"""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        self._exit_stack = AsyncExitStack()
        self._sessions: list[Any] = []

    async def load_servers(self) -> int:
        """从配置文件加载并连接所有 MCP 服务器。返回成功连接的数量。"""
        if not MCP_CONFIG_FILE.exists():
            logger.info("未找到 MCP 配置文件，跳过 MCP 加载")
            return 0

        try:
            with open(MCP_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            logger.error(f"读取 MCP 配置失败: {e}")
            return 0

        servers = config.get("servers", [])
        connected = 0

        for server_conf in servers:
            if not server_conf.get("enabled", True):
                continue
            name = server_conf.get("name", "unknown")
            try:
                await self._connect_server(server_conf)
                connected += 1
                logger.info(f"MCP 服务器连接成功: {name}")
            except Exception as e:
                logger.error(f"MCP 服务器连接失败: {name} | {e}")

        return connected

    async def _connect_server(self, server_conf: dict) -> None:
        """连接单个 MCP 服务器并注册其工具。"""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            logger.warning(
                "mcp 包未安装，跳过 MCP 服务器连接。"
                "安装方法: poetry add mcp"
            )
            return

        name = server_conf["name"]
        command = server_conf["command"]
        args = server_conf.get("args", [])
        env = server_conf.get("env")

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )

        # 使用 AsyncExitStack 管理嵌套的 context managers
        transport = stdio_client(server_params)
        read_stream, write_stream = await self._exit_stack.enter_async_context(transport)

        session = ClientSession(read_stream, write_stream)
        await self._exit_stack.enter_async_context(session)
        self._sessions.append(session)

        # 初始化
        await session.initialize()

        # 获取工具列表
        tools_result = await session.list_tools()

        # 转换为 OpenAI function calling 格式
        openai_tools = []
        for tool in tools_result.tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": f"mcp_{name}_{tool.name}",
                    "description": tool.description or f"MCP tool: {tool.name}",
                    "parameters": tool.inputSchema if tool.inputSchema else {
                        "type": "object", "properties": {},
                    },
                },
            }
            openai_tools.append(openai_tool)

        # 创建调用函数（闭包捕获 session 和 name）
        _session = session
        _prefix = f"mcp_{name}_"

        async def call_tool(tool_name: str, arguments: dict) -> str:
            original_name = tool_name[len(_prefix):] if tool_name.startswith(_prefix) else tool_name
            result = await _session.call_tool(original_name, arguments)
            parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                else:
                    parts.append(str(content))
            return "\n".join(parts)

        # 注册为技能
        tool_names = [t.name for t in tools_result.tools]
        skill = MCPServerSkill(
            server_name=name,
            server_description=f"MCP 服务器 '{name}' 提供的工具: {', '.join(tool_names)}",
            tools=openai_tools,
            call_tool_fn=call_tool,
        )
        self._registry.register(skill)

    async def close(self) -> None:
        """关闭所有 MCP 连接。"""
        try:
            await self._exit_stack.aclose()
        except Exception as e:
            logger.warning(f"关闭 MCP 连接时出现异常: {e}")
        self._sessions.clear()
        logger.info("所有 MCP 连接已关闭")
