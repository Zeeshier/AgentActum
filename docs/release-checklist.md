# AgentActum 0.1 Release Checklist

## Purpose

This checklist defines the manual steps for the first AgentActum release. It is
not a publishing script and does not grant authority to upload artifacts.

## Release identity

- Package: `agentactum`
- Version: `0.1.0`
- Python: `>=3.12`
- License: Apache-2.0
- Runtime dependency: Pydantic 2.x
- Optional extra: `agentactum[langgraph]`

## Pre-release verification

Run these commands from a clean checkout with development dependencies
installed:

```shell
pytest
ruff check .
ruff format --check .
mypy src
pre-commit run --all-files
python -m pip wheel . --no-deps --wheel-dir dist
```

Expected state:

- all tests pass;
- coverage remains at the configured threshold;
- lint, formatting, and type checks pass;
- the package imports without LangGraph installed;
- `from agentactum.langgraph import LangGraphAdapter` imports without importing
  LangGraph itself;
- wheel metadata reports version `0.1.0`.

## Documentation review

Before tagging, review:

- `README.md` for installation, usage, optional LangGraph, limitations, and
  release commands;
- `CHANGELOG.md` for the 0.1.0 entry;
- `docs/product-spec.md` for current scope and non-goals;
- `docs/architecture.md` for adapter and core-boundary language;
- `docs/security-invariants.md` for honest in-memory and compensation claims;
- `docs/development-roadmap.md` for milestone status and deferred work.

## Safety review

Confirm the release notes do not imply:

- durable storage or crash recovery;
- distributed exactly-once effects;
- universal rollback;
- real external integrations;
- authentication or approval UI;
- LLM-based policy decisions;
- LangGraph as a core dependency.

## Tagging and publication

Recommended manual sequence:

```shell
git status --short
git tag v0.1.0
git push origin v0.1.0
```

Only publish package artifacts after the repository state, tag, and artifact
contents have been reviewed. Do not publish from a dirty worktree.

## Post-release smoke test

In a fresh virtual environment:

```shell
python -m pip install agentactum
python -c "import agentactum; print(agentactum.__version__)"
python -m pip install "agentactum[langgraph]"
python -c "from agentactum.langgraph import LangGraphAdapter; print(LangGraphAdapter.__name__)"
```

Expected version output:

```text
0.1.0
```
