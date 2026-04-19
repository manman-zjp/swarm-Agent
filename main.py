"""蜂群 Agent 矩阵 — FastAPI 入口。

启动时：
1. 创建黑板和技能注册表
2. 注册内置技能（代码执行、任务拆分）
3. 加载 MCP 服务器（如有配置）
4. 启动 Agent 池

用户通过 POST /chat 发送消息，系统在黑板上创建任务并等待完成。
"""

import asyncio
import logging
import uuid

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel

from swarm.core.blackboard import Blackboard
from swarm.core.observer import observer
from swarm.llm import LLMClient
from swarm.agent import SwarmAgent
from swarm.skills.registry import SkillRegistry
from swarm.skills.builtin import CodeExecutionSkill, TaskDecomposeSkill
from swarm.mcp.client import MCPManager
from swarm.config import config

# ── 日志配置 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("swarm.main")

# ── 全局组件 ──
blackboard = Blackboard()
llm = LLMClient()
skill_registry = SkillRegistry()
mcp_manager = MCPManager(skill_registry)
agents: list[SwarmAgent] = []
agent_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # ── 启动 ──
    # 1. 注册内置技能
    skill_registry.register(CodeExecutionSkill())
    skill_registry.register(TaskDecomposeSkill())
    logger.info(f"内置技能注册完成: {skill_registry.skill_count} 个技能, {skill_registry.tool_count} 个工具")

    # 2. 加载 MCP 服务器
    mcp_count = await mcp_manager.load_servers()
    if mcp_count:
        logger.info(f"MCP 服务器加载完成: {mcp_count} 个")

    # 3. 启动 Agent 池
    logger.info(f"启动蜂群：{config.agent.count} 个 Agent")
    for i in range(config.agent.count):
        agent = SwarmAgent(
            agent_id=f"agent-{i+1:02d}",
            blackboard=blackboard,
            llm=llm,
            skills=skill_registry,
        )
        agents.append(agent)
        task = asyncio.create_task(agent.run_forever())
        agent_tasks.append(task)

    # 4. 启动观测器后台刷盘
    observer.start()

    logger.info(
        f"蜂群就绪 | {skill_registry.skill_count} 技能 | "
        f"{skill_registry.tool_count} 工具 | {config.agent.count} Agent"
    )

    yield

    # ── 关闭 ──
    logger.info("关闭蜂群...")
    for agent in agents:
        agent.stop()
    for task in agent_tasks:
        task.cancel()
    await mcp_manager.close()
    await observer.stop()
    logger.info("蜂群已关闭")


# ── FastAPI ──
app = FastAPI(title="蜂群 Agent 矩阵", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    task_id: str


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """用户入口：发送消息，等待蜂群处理后返回结果。"""
    session_id = req.session_id or str(uuid.uuid4())[:8]

    # 计算 turn_index
    history = blackboard.get_session_history(session_id, max_turns=100)
    turn_index = len(history) + 1

    # 构建上下文引用（最近 3 轮）
    context_refs = []
    for h in history[-3:]:
        if h.output_text:
            context_refs.append(f"turn_{h.turn_index}: {h.output_text[:200]}")

    logger.info(f"[请求] session={session_id} turn={turn_index} | {req.message[:80]}")

    # 在黑板上创建根任务
    task, future = await blackboard.create_root_task(
        action=req.message,
        session_id=session_id,
        turn_index=turn_index,
        context_refs=context_refs,
    )

    # 等待任务完成（带超时）
    try:
        completed_task = await asyncio.wait_for(future, timeout=config.task.chat_timeout)
        reply = completed_task.output_text or "任务完成，但无输出。"
    except asyncio.TimeoutError:
        reply = f"任务处理超时（{int(config.task.chat_timeout)}秒），请稍后重试。"

    logger.info(f"[回复] session={session_id} | {reply[:80]}")

    return ChatResponse(
        session_id=session_id,
        reply=reply,
        task_id=task.task_id,
    )


@app.get("/health")
async def health() -> dict:
    """健康检查。"""
    return {
        "status": "ok",
        "agents": len(agents),
        "skills": skill_registry.list_skills(),
        "pending_tasks": sum(
            1 for t in blackboard._tasks.values()
            if t.status.value == "pending"
        ),
    }


# ── 可观测 API ────────────────────────────────────

@app.get("/board")
async def board_overview() -> dict:
    """黑板概览。"""
    snap = blackboard.snapshot()
    return {
        "summary": snap["summary"],
        "sessions": snap["sessions"],
    }


@app.get("/board/tasks")
async def board_tasks(status: str | None = None, session_id: str | None = None) -> dict:
    """任务列表，支持按 status 和 session_id 过滤。"""
    tasks = list(blackboard._tasks.values())
    if status:
        tasks = [t for t in tasks if t.status.value == status]
    if session_id:
        tasks = [t for t in tasks if t.session_id == session_id]
    tasks.sort(key=lambda t: t.created_at, reverse=True)
    return {
        "count": len(tasks),
        "tasks": [blackboard._task_to_dict(t) for t in tasks],
    }


@app.get("/board/task/{task_id}")
async def board_task_detail(task_id: str) -> dict:
    """单任务详情 + 子任务树 + 推理 trace。"""
    task = blackboard.get_task(task_id)
    if not task:
        return {"error": f"任务 {task_id} 不存在"}
    children = blackboard.get_children(task_id)
    traces = observer.get_traces_by_task(task_id)
    return {
        "task": blackboard._task_to_dict(task),
        "children": [blackboard._task_to_dict(c) for c in children],
        "traces": traces,
    }


@app.get("/board/knowledge")
async def board_knowledge() -> dict:
    """集体知识全量。"""
    snap = blackboard.snapshot()
    return snap["knowledge"]


@app.get("/board/sessions/{session_id}")
async def board_session(session_id: str) -> dict:
    """指定会话的完整历史。"""
    all_tasks = [
        t for t in blackboard.tasks.values()
        if t.session_id == session_id
    ]
    if not all_tasks:
        return {"error": f"会话 {session_id} 不存在"}
    all_tasks.sort(key=lambda t: (t.turn_index, t.created_at))
    root_tasks = [t for t in all_tasks if t.parent_id is None]
    turns = []
    for rt in root_tasks:
        children = blackboard.get_children(rt.task_id)
        turns.append({
            "turn_index": rt.turn_index,
            "action": rt.action,
            "status": rt.status.value,
            "output_text": (
                (rt.output_text[:500] + "...")
                if rt.output_text and len(rt.output_text) > 500
                else rt.output_text
            ),
            "task_id": rt.task_id,
            "children_count": len(children),
            "created_at": rt.created_at.isoformat(),
        })
    return {
        "session_id": session_id,
        "total_turns": len(root_tasks),
        "total_tasks": len(all_tasks),
        "turns": turns,
    }


@app.get("/board/traces/{task_id}")
async def board_traces(task_id: str) -> dict:
    """指定任务的推理 trace 日志。"""
    traces = observer.get_traces_by_task(task_id)
    return {
        "task_id": task_id,
        "count": len(traces),
        "traces": traces,
    }


@app.get("/skills")
async def list_skills() -> dict:
    """列出所有已注册技能。"""
    return {
        "count": skill_registry.skill_count,
        "tools_count": skill_registry.tool_count,
        "skills": skill_registry.list_skills(),
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
