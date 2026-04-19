<div align="center">

# Swarm Agent

**Decentralized Swarm Intelligence Agent System**

*No Manager. No Chain-of-Command. No Fixed Routes.*<br>
*Just autonomous agents, a shared blackboard, and emergent intelligence.*

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-Compatible-00B4D8?style=flat-square)](https://modelcontextprotocol.io)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)

[English](#overview) | [中文说明](#中文说明)

---

</div>

## Overview

Swarm Agent is a **self-organizing multi-agent system** built on the blackboard architecture. Unlike traditional orchestration frameworks with a central manager, every agent in Swarm Agent is **equal** — they compete for tasks, collaborate through shared state, and collectively accumulate knowledge over time.

> *Inspired by swarm intelligence in nature: no leader, yet the colony thrives.*

<br>

## Why Swarm Agent?

| | Traditional (Manager/Worker) | Swarm Agent |
|---|---|---|
| **Topology** | Fixed hierarchy | Flat, fully decentralized |
| **Single Point of Failure** | Manager goes down = system down | Any agent can take over |
| **Task Routing** | Hardcoded or rule-based | Autonomous competition |
| **Scalability** | Modify routing logic | Just add more agents |
| **Knowledge** | Per-agent, siloed | Collective, shared & persistent |
| **Tool Discovery** | Pre-configured per agent | Auto-discovered via MCP |

<br>

## Architecture

```
                          ┌─────────────────────────┐
                          │      User Request        │
                          │      POST /chat          │
                          └───────────┬─────────────┘
                                      │
                                      ▼
              ┌───────────────────────────────────────────┐
              │             B L A C K B O A R D           │
              │                                           │
              │  ┌─────────┐ ┌──────────┐ ┌────────────┐  │
              │  │  Tasks   │ │Collective│ │   Event    │  │
              │  │  Queue   │ │Knowledge │ │    Log     │  │
              │  └─────────┘ └──────────┘ └────────────┘  │
              └──────┬──────────┬──────────┬──────────────┘
                     │          │          │
            ┌────────┼──────────┼──────────┼────────┐
            │        │          │          │        │
            ▼        ▼          ▼          ▼        ▼
       ┌─────────┐ ┌─────────┐ ┌─────────┐     ┌─────────┐
       │ Agent 1 │ │ Agent 2 │ │ Agent 3 │ ... │ Agent N │
       └────┬────┘ └────┬────┘ └────┬────┘     └────┬────┘
            │           │           │               │
            └───────────┴─────┬─────┴───────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │      S K I L L   R E G I S T R Y      │
              ├───────────┬───────────┬───────────────┤
              │  Built-in │    MCP    │    Custom     │
              │ code_exec │   fetch   │    ...        │
              │ task_ops  │ filesystem│               │
              └───────────┴───────────┴───────────────┘
```

<br>

## Key Features

**Decentralized Collaboration**
- Homogeneous agents with zero hierarchy
- Blackboard-based indirect coordination
- Competitive task claiming with atomic locks

**Unified ReAct Execution**
- LLM autonomously decides: answer / use tools / decompose
- Conditional reflection — only after tool use, saving tokens
- Up to N rounds of tool-calling loops

**Collective Intelligence**
- Auto-extracts skills, patterns, and lessons from execution
- Persisted to disk, shared across all agents
- The swarm gets smarter over time

**Three-Layer Memory & Persistence**
- Core Memory: KV facts auto-extracted per session
- Summary Memory: incremental rolling summary (sliding window)
- Working Memory: recent turn context window
- Multi-backend: SQLite (default) / MySQL / PostgreSQL — switch via `.env`
- SQLAlchemy Engine with built-in connection pooling (`QueuePool` + `pool_pre_ping`)

**Web Dashboard**
- Built-in single-page frontend (no build step)
- Real-time task monitoring, session history, knowledge browser
- Served at `http://localhost:8000/` alongside API

**MCP Protocol Native**
- JSON config → auto-connect to any MCP server
- Tools auto-discovered and registered at startup
- Compatible with the entire MCP ecosystem

**Full Observability**
- Task lifecycle events + reasoning traces
- JSONL logs for every agent decision
- REST API for real-time inspection

**Hot-Pluggable Skills**
- File system monitoring via `watchdog` — skills auto-discovered on file change
- Drop a new `.py` file into `swarm/skills/builtin/` → instantly available to agents
- `importlib.reload()` for live updates without restart
- HTTP management API: `/skills/load`, `/skills/reload/{name}`, `DELETE /skills/{name}`

<br>

## Quick Start

### Prerequisites

| Requirement | Version | Note |
|---|---|---|
| Python | >= 3.10 | |
| Poetry | >= 2.0 | [Install Guide](https://python-poetry.org/docs/#installation) |
| uvx | (optional) | For MCP Python servers |
| Node.js + npx | (optional) | For MCP TypeScript servers |

### Installation

```bash
git clone https://github.com/manman-zjp/swarm-Agent.git
cd swarm-Agent

poetry install            # Core dependencies (includes SQLAlchemy)
poetry install -E mcp     # + MCP support (recommended)
poetry install -E hotloader  # + Skill hot-plugging (watchdog)

# Optional database backends (default SQLite needs no extra deps)
poetry install -E mysql   # + MySQL support (pymysql)
poetry install -E pgsql   # + PostgreSQL support (psycopg2)
poetry install -E all-db  # + All database backends
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env` with your LLM provider credentials:

```env
MODEL_NAME="qwen-max"
OPENAI_API_KEY="sk-your-key-here"
OPENAI_API_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

> **Compatible with any OpenAI-format API**: Qwen (DashScope), GLM (Zhipu), DeepSeek, GPT-4o, local vLLM/Ollama, etc.

All runtime parameters are configurable via environment variables. See the [Configuration](#configuration) section for the full list.

### Launch

```bash
python main.py
```

You should see:
```
 INFO   Swarm Agent started | agents=3 | skills=4 | tools=18
 INFO   Uvicorn running on http://0.0.0.0:8000
```

### Chat

```bash
# Single turn
curl -s http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Write a quicksort in Python"}' | jq .reply

# Multi-turn (pass session_id)
curl -s http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Now make it descending", "session_id": "abc123"}' | jq .reply
```

<br>

## MCP Integration

Connect to any [MCP server](https://github.com/modelcontextprotocol/servers) via `swarm/data/mcp_servers.json`:

```json
{
  "servers": [
    {
      "name": "fetch",
      "command": "uvx",
      "args": ["mcp-server-fetch"],
      "enabled": true
    },
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/your/path"],
      "enabled": false
    }
  ]
}
```

<details>
<summary><b>Popular MCP Servers</b></summary>

| Server | Command | Capability |
|---|---|---|
| **fetch** | `uvx mcp-server-fetch` | HTTP requests, web scraping |
| **filesystem** | `npx @modelcontextprotocol/server-filesystem` | File I/O, directory ops |
| **git** | `uvx mcp-server-git` | Git operations |
| **brave-search** | `npx @modelcontextprotocol/server-brave-search` | Web search (API key required) |
| **sqlite** | `uvx mcp-server-sqlite` | SQLite database operations |
| **puppeteer** | `npx @modelcontextprotocol/server-puppeteer` | Browser automation |

See [MCP Servers Registry](https://github.com/modelcontextprotocol/servers) for the full list.

</details>

<br>

## API Reference

<details>
<summary><b>Core Endpoints</b></summary>

| Method | Path | Description |
|---|---|---|
| `POST` | `/chat` | Send a message to the swarm |
| `GET` | `/health` | Health check (agent count, skills, pending tasks) |
| `GET` | `/skills` | List all registered skills and tools |
| `POST` | `/skills/load` | Manually load a skill module |
| `POST` | `/skills/reload/{name}` | Hot-reload a specific skill |
| `DELETE` | `/skills/{name}` | Unregister a skill |

</details>

<details>
<summary><b>Observability Endpoints</b></summary>

| Method | Path | Description |
|---|---|---|
| `GET` | `/board` | Blackboard overview (task stats, sessions) |
| `GET` | `/board/tasks` | Task list (filter: `?status=` `?session_id=`) |
| `GET` | `/board/task/{id}` | Task detail + subtree + reasoning trace |
| `GET` | `/board/knowledge` | Collective knowledge (skills/patterns/lessons) |
| `GET` | `/board/sessions/{id}` | Full session history |
| `GET` | `/board/traces/{id}` | Reasoning trace for a specific task |

</details>

<details>
<summary><b>Storage & Connection Pool</b></summary>

| Variable | Default | Description |
|---|---|---|
| `SESSION_DB_URL` | `sqlite:///swarm/data/sessions.db` | Database URL (sqlite / mysql / postgresql) |
| `SESSION_FACT_MAX_PER_SESSION` | `50` | Max KV facts per session |
| `SESSION_POOL_SIZE` | `5` | Connection pool size (MySQL/PgSQL only) |
| `SESSION_POOL_MAX_OVERFLOW` | `10` | Max overflow connections (MySQL/PgSQL only) |
| `SESSION_POOL_RECYCLE` | `3600` | Connection recycle interval in seconds |

</details>

<details>
<summary><b>Summary & Context Window</b></summary>

| Variable | Default | Description |
|---|---|---|
| `TASK_SUMMARY_WINDOW_SIZE` | `3` | Turns per summary batch |
| `TASK_SUMMARY_MAX_CHARS` | `800` | Max summary length |
| `TASK_SUMMARY_TURN_DETAIL_CHARS` | `500` | Max chars per turn in summary input |

</details>

<details>
<summary><b>Skill Hot-Plugging</b></summary>

| Variable | Default | Description |
|---|---|---|
| `SKILL_HOTLOADER_ENABLED` | `true` | Enable/disable skill hot-plugging |
| `SKILL_HOTLOADER_WATCH_DIR` | `swarm/skills/builtin` | Directory to monitor for new skills |

</details>

<br>

## Extending Skills

### Static Registration

Create a custom skill by subclassing `BaseSkill`:

```python
from swarm.skills.base import BaseSkill

class WeatherSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "weather"

    @property
    def description(self) -> str:
        return "Query real-time weather information"

    def get_tools(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"}
                    },
                    "required": ["city"],
                },
            },
        }]

    async def execute(self, tool_name: str, args: dict) -> str:
        return f"Weather in {args['city']}: 25 C, Sunny"
```

Register in `main.py`:

```python
skill_registry.register(WeatherSkill())
```

### Hot-Plugging (Zero Restart)

With `watchdog` installed (`poetry install -E hotloader`), simply drop a new `.py` file into the watched directory:

```bash
# 1. Create a new skill file
cat > swarm/skills/builtin/weather.py << 'EOF'
from swarm.skills.base import BaseSkill
from typing import Any

class WeatherSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "weather"

    @property
    def description(self) -> str:
        return "Query real-time weather information"

    def get_tools(self) -> list[dict[str, Any]]:
        return [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"}
                    },
                    "required": ["city"],
                },
            },
        }]

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        return f"Weather in {args['city']}: 25 C, Sunny"
EOF

# 2. The system automatically detects and registers it!
# No restart required — agents can use it immediately.
```

**HTTP API for manual management:**

```bash
# Load a skill module by path
curl -X POST http://localhost:8000/skills/load \
  -H "Content-Type: application/json" \
  -d '{"module": "swarm.skills.builtin.weather"}'

# Hot-reload an existing skill
curl -X POST http://localhost:8000/skills/reload/weather

# Unregister a skill
curl -X DELETE http://localhost:8000/skills/weather
```

<br>

## Collective Knowledge

Agents automatically extract and persist execution experience:

| Type | File | Description |
|---|---|---|
| **Skills** | `skills.json` | Verified execution plans with steps and tools |
| **Patterns** | `patterns.json` | Task decomposition templates |
| **Lessons** | `lessons.json` | Failure cases and cautionary notes |

Knowledge priority: **Skills > Patterns > Lessons**. When a new task arrives, agents consult collective knowledge before acting.

<br>

## Project Structure

```
swarm-agent/
├── main.py                      # FastAPI entrypoint & routes
├── swarm/
│   ├── config.py                # Centralized configuration (env-driven)
│   ├── agent.py                 # Agent core: ReAct + conditional reflection
│   ├── llm.py                   # LLM client (OpenAI-compatible)
│   ├── prompts.py               # System prompt templates
│   ├── core/
│   │   ├── blackboard.py        # Blackboard: tasks + knowledge + indexing
│   │   ├── models.py            # Data models (Task, Skill, Pattern, Lesson, SessionMemory)
│   │   ├── storage.py           # Persistence: SQLAlchemy Engine + multi-backend
│   │   └── observer.py          # Observer: async buffered trace logger
│   ├── skills/
│   │   ├── base.py              # Skill abstract base class
│   │   ├── registry.py          # Skill registry + tool routing
│   │   ├── hotloader.py         # Hot-plug manager (watchdog + importlib)
│   │   └── builtin/
│   │       ├── code_exec.py     # Built-in: Python/Shell execution
│   │       └── task_ops.py      # Built-in: Task decomposition
│   │       └── weather.py       # Example: Custom hot-pluggable skill
│   ├── mcp/
│   │   └── client.py            # MCP client: external server connector
│   ├── static/
│   │   └── index.html           # Built-in web dashboard (single-page)
│   └── data/
│       └── mcp_servers.json     # MCP server configuration
├── tests/                       # Unit tests (pytest)
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_storage.py
│   └── test_hotloader.py
├── docs/
│   └── architecture.md          # Architecture design document
├── .env.example                 # Environment template (all parameters)
├── pyproject.toml               # Project metadata & dependencies
└── LICENSE                      # Apache-2.0
```

<br>

## Configuration

All parameters are centralized in `swarm/config.py` and driven by environment variables (with sensible defaults). Just set them in `.env` — no code changes needed.

<details>
<summary><b>LLM Settings</b></summary>

| Variable | Default | Description |
|---|---|---|
| `MODEL_NAME` | `qwen-max` | LLM model name |
| `OPENAI_API_KEY` | (empty) | API key for LLM provider |
| `OPENAI_API_BASE_URL` | (empty) | Base URL for OpenAI-compatible API |
| `LLM_TEMPERATURE` | `0.3` | Default sampling temperature |
| `LLM_MAX_TOKENS` | `4096` | Max tokens per LLM call |
| `LLM_MAX_TOOL_ROUNDS` | `10` | Max ReAct tool-calling rounds |
| `LLM_REFLECTION_TEMPERATURE` | `0.1` | Temperature for reflection calls |

</details>

<details>
<summary><b>Agent Behavior</b></summary>

| Variable | Default | Description |
|---|---|---|
| `AGENT_COUNT` | `3` | Number of concurrent agents |
| `AGENT_TASK_WAIT_TIMEOUT` | `10.0` | Seconds to wait before re-polling for tasks |
| `AGENT_REFLECTION_TOOL_THRESHOLD` | `2` | Min tool calls to trigger reflection |
| `AGENT_REFLECTION_TIME_MS` | `5000` | Min execution time (ms) to trigger reflection |
| `AGENT_REFLECTION_RESULT_MAX_CHARS` | `2000` | Max chars of result sent to reflection LLM |

</details>

<details>
<summary><b>Task Settings</b></summary>

| Variable | Default | Description |
|---|---|---|
| `TASK_CHAT_TIMEOUT` | `300.0` | Max seconds to wait for chat response |
| `TASK_CLAIM_TTL_SECONDS` | `300` | Task lock expiry (prevents stuck tasks) |
| `TASK_MAX_RETRIES` | `3` | Max retry attempts for failed tasks |
| `TASK_SESSION_HISTORY_MAX_TURNS` | `3` | Recent turns included in session context |

</details>

<details>
<summary><b>Knowledge Thresholds</b></summary>

| Variable | Default | Description |
|---|---|---|
| `KNOWLEDGE_SKILL_MIN_CONFIDENCE` | `0.5` | Min confidence to use a learned skill |
| `KNOWLEDGE_PATTERN_MIN_CONFIDENCE` | `0.3` | Min confidence to use a decomposition pattern |
| `KNOWLEDGE_LESSON_MIN_CONFIDENCE` | `0.2` | Min confidence to include a lesson |
| `KNOWLEDGE_MAX_LESSONS_IN_PROMPT` | `3` | Max lessons injected into prompt |

</details>

<details>
<summary><b>Observer & Code Execution</b></summary>

| Variable | Default | Description |
|---|---|---|
| `OBSERVER_FLUSH_INTERVAL` | `1.0` | Seconds between trace log flushes |
| `OBSERVER_FLUSH_BATCH_SIZE` | `50` | Max records per flush batch |
| `OBSERVER_TRACE_TRUNCATE_LEN` | `500` | Max chars for trace data truncation |
| `CODE_EXEC_TIMEOUT` | `120.0` | Seconds before killing a code execution |

</details>

<br>

## Tech Stack

| Component | Technology |
|---|---|
| Runtime | Python 3.10+ / asyncio |
| Web Framework | FastAPI + Uvicorn |
| LLM Client | OpenAI Python SDK |
| Tool Protocol | MCP (Model Context Protocol) |
| Persistence | SQLAlchemy 2.0 (SQLite / MySQL / PostgreSQL) |
| Connection Pool | SQLAlchemy QueuePool (pool_pre_ping + auto-recycle) |
| Frontend | Built-in SPA (vanilla JS, no build step) |
| Hot-Plugging | watchdog (file system monitoring + importlib reload) |

<br>

## Roadmap

- [x] ~~Web UI dashboard~~ — Built-in SPA with session history & knowledge browser
- [x] ~~Multi-backend persistence~~ — SQLite / MySQL / PostgreSQL via SQLAlchemy
- [x] ~~Three-layer memory~~ — KV facts + rolling summary + context window
- [x] ~~Connection pooling~~ — SQLAlchemy QueuePool with pre-ping & auto-recycle
- [x] ~~Hot-pluggable skills~~ — File monitoring + zero-restart skill registration
- [x] ~~Automatic skill extraction & evolution~~ — Collective knowledge system
- [ ] Redis backend for production-grade blackboard
- [ ] Dynamic agent scaling
- [ ] Docker sandbox for code execution
- [ ] Vector-based knowledge retrieval
- [ ] Streaming response support

<br>

---

<div align="center">

## 中文说明

</div>

Swarm Agent 是一个**去中心化蜂群智能体系统**。

没有 Manager，没有指令链，没有固定路由。所有 Agent 完全同质，通过共享黑板自主竞争任务、协同工作、积累集体知识。系统灵感来源于自然界的蜂群智能 —— 没有领导者，但整个群体依然高效运转。

**核心设计**：
- 黑板架构：所有通信通过黑板间接完成，Agent 之间零耦合
- 统一 ReAct：LLM 自主决策 —— 直接回答 / 调用工具 / 拆分子任务
- 集体学习：执行经验自动沉淀为技能、模式、教训，群体越用越聪明
- MCP 原生：通过 JSON 配置接入任意 MCP 服务器，工具自动发现注册

详细架构设计请参阅 [docs/architecture.md](docs/architecture.md)。

<br>

---

<div align="center">

**If this project helps you, consider giving it a star!**

Made with determination and lots of coffee.

</div>
