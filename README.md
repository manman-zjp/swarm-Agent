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

**MCP Protocol Native**
- JSON config → auto-connect to any MCP server
- Tools auto-discovered and registered at startup
- Compatible with the entire MCP ecosystem

**Full Observability**
- Task lifecycle events + reasoning traces
- JSONL logs for every agent decision
- REST API for real-time inspection

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
git clone https://github.com/AuroraAI-bat/swarm-agent.git
cd swarm-agent

poetry install            # Core dependencies
poetry install -E mcp     # + MCP support (recommended)
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

<br>

## Extending Skills

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
│   ├── agent.py                 # Agent core: ReAct + conditional reflection
│   ├── llm.py                   # LLM client (OpenAI-compatible)
│   ├── prompts.py               # System prompt templates
│   ├── core/
│   │   ├── blackboard.py        # Blackboard: tasks + knowledge + persistence
│   │   ├── models.py            # Data models (Task, Skill, Pattern, Lesson)
│   │   └── observer.py          # Observer: reasoning trace logger
│   ├── skills/
│   │   ├── base.py              # Skill abstract base class
│   │   ├── registry.py          # Skill registry + tool routing
│   │   └── builtin/
│   │       ├── code_exec.py     # Built-in: Python/Shell execution
│   │       └── task_ops.py      # Built-in: Task decomposition
│   ├── mcp/
│   │   └── client.py            # MCP client: external server connector
│   └── data/
│       └── mcp_servers.json     # MCP server configuration
├── docs/
│   └── architecture.md          # Architecture design document
├── .env.example                 # Environment template
├── pyproject.toml               # Project metadata & dependencies
└── LICENSE                      # Apache-2.0
```

<br>

## Configuration

| Parameter | Location | Default | Description |
|---|---|---|---|
| Agent count | `main.py` | 3 | Number of concurrent agents |
| Request timeout | `main.py` | 300s | Max wait time per chat request |
| Max tool rounds | `swarm/llm.py` | 10 | ReAct loop tool-call limit |
| Task claim TTL | `swarm/core/models.py` | 300s | Task lock timeout |

<br>

## Tech Stack

| Component | Technology |
|---|---|
| Runtime | Python 3.10+ / asyncio |
| Web Framework | FastAPI + Uvicorn |
| LLM Client | OpenAI Python SDK |
| Tool Protocol | MCP (Model Context Protocol) |
| Storage | In-memory + JSON file persistence |

<br>

## Roadmap

- [ ] Redis backend for production-grade blackboard
- [ ] Dynamic agent scaling
- [ ] Web UI dashboard
- [ ] Pre-configured MCP server templates
- [ ] Docker sandbox for code execution
- [ ] Automatic skill extraction & evolution
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
