# Contributing to Swarm Agent

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/manman-zjp/swarm-Agent.git
cd swarm-Agent

# Install dependencies (including dev tools)
poetry install -E mcp
poetry install --with dev

# Copy environment config
cp .env.example .env
# Edit .env with your LLM API credentials
```

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Check code style
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

## Running Tests

```bash
pytest
```

## Making Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run linting: `ruff check .`
5. Run tests: `pytest`
6. Commit with a clear message: `git commit -m "feat: add xxx"`
7. Push to your fork: `git push origin feature/your-feature`
8. Open a Pull Request

## Commit Message Convention

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Usage |
|---|---|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation changes |
| `refactor:` | Code refactoring (no feature/fix) |
| `test:` | Adding or updating tests |
| `chore:` | Build, CI, tooling changes |
| `perf:` | Performance improvement |

## Adding a New Skill

1. Create a new file in `swarm/skills/builtin/` (or a separate package)
2. Subclass `BaseSkill` and implement `name`, `description`, `get_tools()`, `execute()`
3. Register in `main.py`: `skill_registry.register(YourSkill())`
4. See [README - Extending Skills](README.md#extending-skills) for a full example

## Reporting Issues

- Use [GitHub Issues](https://github.com/manman-zjp/swarm-Agent/issues)
- Include: Python version, OS, steps to reproduce, error logs

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
