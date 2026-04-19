# Swarm Matrix 架构设计文档

## 1. 核心设计哲学

- **去中心化 (Decentralized)**：放弃 Manager → Worker 的指令链路，所有 Agent 完全同质
- **环境驱动 (Stigmergy)**：Agent 通过修改共享黑板上的任务状态来间接协作
- **局部感知 (Local Perception)**：Agent 不阅读全量上下文，只感知当前任务 + 相关集体知识
- **动态涌现 (Emergence)**：复杂的协作路径不是预设的，而是根据任务拆分自动形成

---

## 2. 系统组件

### 2.1 黑板 (Blackboard)

系统唯一的共享空间，所有 Agent 通过黑板间接通信。

**存储内容：**

| 区域 | 说明 | 数据结构 |
| --- | --- | --- |
| 任务池 | 所有任务及其状态 | `dict[task_id, Task]` |
| 集体知识 | 技能 + 拆分模式 + 经验教训 | `skills.json` / `patterns.json` / `lessons.json` |
| 事件日志 | 所有任务状态变更记录 | `task_events.jsonl` |
| 完成回调 | HTTP 请求等待的 Future | `dict[task_id, Future]` |

**任务状态流转：**

```
pending → running → done
                  → failed
                  → decomposed → 子任务 pending → ...
```

**并发安全：**
- 所有任务操作通过 `asyncio.Lock` 保证原子性
- 任务领取使用 CAS 语义（Check-And-Set），防止多个 Agent 抢同一任务
- 任务领取有 TTL 锁（默认 300s），超时自动释放

### 2.2 Agent

所有 Agent 完全同质——相同代码、相同 LLM、共享技能注册表。

**Agent 主循环：**

```python
while running:
    task = blackboard.claim_pending(agent_id)  # 竞争领取
    if task:
        await process_task(task)               # 处理任务
    else:
        await blackboard.wait_for_task()       # 等待新任务
```

**任务处理流程：**

```
process_task(task)
    │
    ├── 1. ReAct 执行
    │       构建系统提示词（含技能描述）
    │       构建用户提示词（任务 + 会话上下文 + 历史经验）
    │       调用 LLM（带动态工具列表）
    │       LLM 自主决定：
    │         ├── 直接回答 → 返回文本
    │         ├── 调用工具 → 执行工具 → 继续循环
    │         └── 调用 decompose_task → 拆分子任务
    │
    ├── 2. 检查拆分
    │       如果调用了 decompose_task → 在黑板创建子任务 → 返回
    │
    └── 3. 条件反思（仅工具调用后触发）
            调用 LLM 自检结果
            ├── 通过 → 提取经验 → 提交结果
            └── 不通过 → 修复执行 → 提交结果
```

**设计决策：为什么不是固定三层推理？**

早期设计是感知→执行→反思三层固定流程。问题在于简单问答（如"你好"）也要走三层，浪费 Token 和时间。

当前方案：
- 统一 ReAct 执行层，LLM 通过工具调用自主决策
- 反思仅在使用了执行类工具后触发（纯文本回答跳过）
- 任务拆分作为一个工具（`decompose_task`），由 LLM 自主判断是否需要

### 2.3 技能系统 (SkillRegistry)

所有工具能力通过技能系统统一管理。

```
SkillRegistry
    ├── 内置技能
    │   ├── code_execution (execute_python, execute_shell)
    │   └── task_ops (decompose_task)
    └── MCP 技能（启动时自动发现）
        ├── mcp_fetch (fetch)
        └── mcp_filesystem (read_file, write_file, ...)
```

**技能接口（BaseSkill）：**

| 方法 | 说明 |
| --- | --- |
| `name` | 技能名称（唯一标识） |
| `description` | 技能描述（给 LLM 看的） |
| `get_tools()` | 返回 OpenAI function calling 格式的工具定义 |
| `execute(tool_name, args)` | 执行工具调用 |

**工具路由：** `SkillRegistry` 维护 `tool_name → skill` 映射，LLM 调用任意工具时自动路由到对应技能。

### 2.4 MCP 客户端

通过 [Model Context Protocol](https://modelcontextprotocol.io/) 接入外部工具服务器。

**连接流程：**

```
读取 mcp_servers.json
    │
    ▼ 对每个 enabled 的服务器
启动子进程 (stdio_client)
    │
    ▼
ClientSession.initialize()
    │
    ▼
session.list_tools() → 转换为 OpenAI 格式
    │
    ▼
注册为 MCPServerSkill → SkillRegistry
```

**生命周期管理：** 使用 `AsyncExitStack` 管理所有 MCP 连接的嵌套 context manager，应用关闭时自动清理。

### 2.5 LLM 客户端

封装 OpenAI 兼容 API，支持两种调用模式：

| 模式 | 方法 | 用途 |
| --- | --- | --- |
| 普通对话 | `chat()` | 反思层（纯推理，不调工具） |
| ReAct 循环 | `chat_with_tools()` | 执行层（动态工具列表 + 多轮工具调用） |

**ReAct 循环逻辑：**

```
for round in range(max_rounds):
    response = LLM(messages, tools)
    if no tool_calls:
        return response.content    # 最终回答
    for tool_call in tool_calls:
        result = execute(tool_call)
        messages.append(tool_result)
    # 继续下一轮
```

### 2.6 观测器 (Observer)

记录 Agent 推理过程的结构化 trace 日志。

**日志文件：**

| 文件 | 格式 | 内容 |
| --- | --- | --- |
| `agent_trace.jsonl` | JSONL | Agent 每一步推理的输入/输出/耗时 |
| `task_events.jsonl` | JSONL | 任务状态变更事件 |
| `knowledge_changelog.jsonl` | JSONL | 知识变更记录 |

**trace 记录结构：**

```json
{
  "trace_id": "abc12345",
  "task_id": "task-001",
  "agent_id": "agent-01",
  "layer": "execution",
  "step_seq": 1,
  "action": "react_execute",
  "input": "用户任务描述...",
  "output": "执行结果...",
  "duration_ms": 3200,
  "session_id": "session-xyz"
}
```

**链路串联字段：**

| 字段 | 串联维度 |
| --- | --- |
| `trace_id` | 同一任务的同一次处理 |
| `task_id` | 同一任务（跨重试） |
| `session_id` | 同一用户会话（跨轮次） |
| `agent_id` | 同一 Agent 的所有操作 |
| `parent_id` | 父子任务树 |

---

## 3. 集体知识系统

Agent 群体通过执行任务积累三类知识：

### 3.1 技能 (Skill)

经过验证的完整执行方案——包括步骤、工具选择、注意事项。

```json
{
  "skill_id": "skill-001",
  "name": "科研数据可视化报告",
  "trigger": "需要对科研数据进行分析并生成可视化报告",
  "procedure": [
    {"step": 1, "action": "明确数据来源和分析目标", "tools": []},
    {"step": 2, "action": "数据获取和清洗", "tools": ["execute_python"]},
    {"step": 3, "action": "统计分析和图表生成", "tools": ["execute_python"]},
    {"step": 4, "action": "报告撰写", "tools": []}
  ],
  "known_issues": ["matplotlib 中文需设置字体"],
  "confidence": 0.8,
  "success_count": 5,
  "fail_count": 0
}
```

### 3.2 拆分模式 (Pattern)

任务拆分的触发条件和模板。

```json
{
  "trigger": "同时包含多个独立目标",
  "template": ["目标1的完整描述", "目标2的完整描述"],
  "success_rate": 0.9,
  "confidence": 0.7
}
```

### 3.3 经验教训 (Lesson)

失败经验和注意事项，在构建提示词时注入上下文。

```json
{
  "context": "使用 pandas 处理大文件时",
  "lesson": "应该用 chunksize 参数分批读取，避免内存溢出",
  "confidence": 0.6
}
```

### 知识查询优先级

```
新任务到来
    │
    ▼
1. 查技能（完整方案，最高效）
   → 匹配到 → 基于技能方案执行
    │
    ▼
2. 查拆分模式
   → 匹配到 → 参考模板拆分任务
    │
    ▼
3. 查经验教训
   → 注入到提示词上下文中
    │
    ▼
4. 都没有 → 从零推理
```

---

## 4. 多轮对话

通过 `session_id` 串联多轮对话。

**机制：**
- 每个请求携带 `session_id`（可选，不传则自动生成）
- 黑板按 `session_id` 查询历史任务（最近 3 轮的完成任务）
- 历史上下文注入到用户提示词中
- 任何 Agent 都能接手同一 session 的不同轮次

---

## 5. 任务拆分与并行

当 LLM 判断任务包含多个独立子目标时，调用 `decompose_task` 工具拆分。

**拆分流程：**

```
父任务 (pending)
    │ Agent-01 领取
    ▼
Agent-01 执行 → LLM 调用 decompose_task(subtasks=[...])
    │
    ▼
父任务状态 → decomposed
子任务 1 (pending)  ← Agent-02 领取并执行
子任务 2 (pending)  ← Agent-03 领取并执行
    │
    ▼ 所有子任务完成
父任务自动汇总 → done
    │
    ▼
HTTP Future 解析 → 返回结果给用户
```

---

## 6. 数据流全景

```
用户 POST /chat
    │
    ▼
main.py: 创建根任务 + Future → 黑板
    │
    ▼
Agent 主循环: claim_pending() 竞争领取
    │
    ▼
Agent._execute():
    构建提示词 (系统 + 用户 + 知识上下文)
    LLM.chat_with_tools(messages, tools)
        │
        ├── 工具调用 → SkillRegistry.execute() → 结果回注
        └── 最终回答
    │
    ▼
Agent._reflect() [条件触发]
    LLM.chat(反思提示词)
    解析 JSON → ReflectionResult
    │
    ▼
blackboard.submit_result(task, output, lessons)
    保存经验 → lessons.json
    检查父任务是否完成
    解析 Future → HTTP 响应返回用户
```

---

## 7. 与传统架构对比

| 特性 | Swarm Matrix（蜂群） | 传统 Manager 模式 |
| :--- | :--- | :--- |
| 调度方式 | Agent 自主竞争领取 | Manager 显式分发 |
| 扩展性 | 增加 Agent 数量即可，无需改路由 | 需修改 Manager 路由逻辑 |
| 鲁棒性 | 单个 Agent 崩溃，其他自动补位 | Manager 崩溃则全系统瘫痪 |
| Token 效率 | 仅在工具调用后反思，简单问答零额外开销 | 所有任务走固定流程 |
| 工具管理 | 技能注册表 + MCP 自动发现 | 工具硬编码在代码中 |
| 知识积累 | 集体知识自动提取、持久化、复用 | 无群体学习能力 |
| 通信方式 | 黑板间接通信（环境驱动） | 直接消息传递（指令驱动） |

---

## 8. 生产化路线图

| 阶段 | 改进 | 说明 |
| --- | --- | --- |
| Phase 1 | Redis 黑板 | 替换内存实现，支持多进程/多节点部署 |
| Phase 2 | Docker 沙箱 | 代码执行隔离，防止恶意代码 |
| Phase 3 | Agent 弹性伸缩 | 根据任务队列深度动态调整 Agent 数量 |
| Phase 4 | 向量知识检索 | 集体知识从关键词匹配升级为语义检索 |
| Phase 5 | Web UI | 任务树可视化 + Agent 执行时间线 + 知识看板 |
