# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-04-19

### Added
- Three-layer session memory: KV facts (auto-extracted) + rolling summary + context window
- Multi-backend persistence: SQLite (default) / MySQL / PostgreSQL — switch via `SESSION_DB_URL`
- SQLAlchemy Engine with built-in connection pooling (QueuePool + pool_pre_ping + auto-recycle)
- Session turns persistence (`session_turns` table) with UPSERT semantics
- Incremental rolling summary (sliding window, configurable batch size)
- KV fact extraction from conversations via LLM
- Built-in web dashboard (single-page SPA, no build step)
- Session history restore from database on page load
- Storage pool configuration: `SESSION_POOL_SIZE`, `SESSION_POOL_MAX_OVERFLOW`, `SESSION_POOL_RECYCLE`
- Optional dependency groups: `[mysql]`, `[pgsql]`, `[all-db]`
- Comprehensive `.env.example` covering all configuration parameters

### Changed
- Storage layer unified from three separate classes to single `SQLAlchemySessionStore`
- `create_store()` factory now accepts connection pool parameters
- All database operations use parameterized queries (`:param` style via SQLAlchemy `text()`)

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
