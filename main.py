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
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from swarm.core.blackboard import Blackboard
from swarm.core.observer import observer
from swarm.core.storage import create_store
from swarm.llm import LLMClient
from swarm.agent import SwarmAgent
from swarm.skills.registry import SkillRegistry
from swarm.skills.builtin import CodeExecutionSkill, TaskDecomposeSkill
from swarm.skills.hotloader import SkillHotLoader
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
session_store = create_store(
    config.storage.db_url,
    pool_size=config.storage.pool_size,
    max_overflow=config.storage.pool_max_overflow,
    pool_recycle=config.storage.pool_recycle,
)
blackboard = Blackboard(store=session_store)
llm = LLMClient()
skill_registry = SkillRegistry()
mcp_manager = MCPManager(skill_registry)
skill_hotloader: SkillHotLoader | None = None
agents: list[SwarmAgent] = []
agent_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    global skill_hotloader

    # ── 启动 ──
    # 1. 注册内置技能
    skill_registry.register(CodeExecutionSkill())
    skill_registry.register(TaskDecomposeSkill())
    logger.info(f"内置技能注册完成: {skill_registry.skill_count} 个技能, {skill_registry.tool_count} 个工具")

    # 2. 启动技能热插拔监控
    if config.skill_hotloader.enabled:
        skill_hotloader = SkillHotLoader(
            registry=skill_registry,
            watch_dir=config.skill_hotloader.watch_dir,
            auto_scan=True,
        )
        hotloaded = skill_hotloader.start()
        if hotloaded:
            logger.info(f"[热插拔] 自动加载 {hotloaded} 个技能")

    # 3. 加载 MCP 服务器
    mcp_count = await mcp_manager.load_servers()
    if mcp_count:
        logger.info(f"MCP 服务器加载完成: {mcp_count} 个")

    # 4. 启动 Agent 池
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

    # 5. 启动观测器后台刷盘
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
    if skill_hotloader:
        skill_hotloader.stop()
    await mcp_manager.close()
    await observer.stop()
    logger.info("蜂群已关闭")


# ── FastAPI ──
app = FastAPI(title="蜂群 Agent 矩阵", lifespan=lifespan)

# ── 静态文件 ──
STATIC_DIR = Path(__file__).parent / "swarm" / "static"


@app.get("/")
async def index():
    """主页 → 控制台 UI。"""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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

    # 计算 turn_index（内存 + DB）
    history = blackboard.get_session_full_history(session_id)
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
    """黑板概览（包含 DB 中的历史会话）。"""
    snap = blackboard.snapshot()
    # 合并 DB 中的历史会话
    all_session_ids = blackboard.get_all_session_ids()
    return {
        "summary": snap["summary"],
        "sessions": snap["sessions"],
        "all_session_ids": all_session_ids,
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
    """指定会话的完整历史（支持从 DB 恢复）。"""
    # 优先从内存获取，否则回走 DB
    full_history = blackboard.get_session_full_history(session_id)
    if not full_history:
        return {"error": f"会话 {session_id} 不存在"}

    turns = []
    for rt in full_history:
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
        "total_turns": len(full_history),
        "total_tasks": len(full_history),
        "turns": turns,
    }


@app.get("/board/sessions/{session_id}/memory")
async def board_session_memory(session_id: str) -> dict:
    """指定会话的三层记忆：核心事实 + 滚动摘要 + 窗口状态。"""
    memory = blackboard.get_session_memory(session_id)
    facts = blackboard.get_session_facts(session_id)
    return {
        "session_id": session_id,
        "summary": {
            "text": memory.summary if memory else "",
            "up_to_turn": memory.summary_up_to_turn if memory else 0,
            "total_turns": memory.total_turns if memory else 0,
        },
        "facts": [
            {"key": f.fact_key, "value": f.fact_value, "source_turn": f.source_turn}
            for f in facts
        ],
        "fact_count": len(facts),
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


# ── 技能热插拔管理 API ────────────────────────────

class SkillLoadRequest(BaseModel):
    module: str  # 模块路径，如 "swarm.skills.builtin.my_skill"


@app.post("/skills/load")
async def load_skill(req: SkillLoadRequest) -> dict:
    """手动加载指定模块中的技能。"""
    if not skill_hotloader:
        return {"error": "技能热插拔未启用"}
    skill_name = skill_hotloader.load_module(req.module)
    if skill_name:
        return {
            "status": "ok",
            "skill_name": skill_name,
            "total_skills": skill_registry.skill_count,
        }
    return {"error": f"加载模块 {req.module} 失败"}


@app.post("/skills/reload/{skill_name}")
async def reload_skill(skill_name: str) -> dict:
    """热重载指定技能（从源文件重新加载）。"""
    if not skill_hotloader:
        return {"error": "技能热插拔未启用"}
    success = skill_hotloader.reload_skill(skill_name)
    if success:
        return {"status": "ok", "skill_name": skill_name}
    return {"error": f"重载技能 {skill_name} 失败"}


@app.delete("/skills/{skill_name}")
async def delete_skill(skill_name: str) -> dict:
    """注销指定技能。"""
    if skill_name in skill_registry._skills:
        skill_registry.unregister(skill_name)
        return {"status": "ok", "skill_name": skill_name}
    return {"error": f"技能 {skill_name} 不存在"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
