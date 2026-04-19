# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2025-04-19

### Added
- Blackboard-based decentralized task coordination
- Homogeneous agent pool with competitive task claiming
- Unified ReAct execution with conditional reflection
- Skill system: `BaseSkill` abstract class + `SkillRegistry` routing
- Built-in skills: `code_execution` (Python/Shell), `task_ops` (decomposition)
- MCP protocol support: auto-discover and register external tools
- Collective knowledge: skills, patterns, lessons with JSON persistence
- Multi-turn session support with context carry-over
- Full observability: task events JSONL + agent reasoning traces
- REST API: `/chat`, `/health`, `/board/*`, `/skills`
- Centralized configuration via environment variables (`swarm/config.py`)
- Async buffered trace logging (non-blocking event loop)
- Blackboard indexing for children and session lookups
- Keyword-filtered lesson injection (reduced token waste)
- Smart reflection threshold (skip for simple tool calls)
