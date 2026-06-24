# AgentActum Repository Instructions

## Product

AgentActum is a framework-independent Python runtime for controlling
side-effecting actions performed by AI agents.

It sits between an agent and its tools and provides:

- tool contracts
- policy enforcement
- risk classification
- approvals
- idempotency
- transactions
- effect staging
- compensation
- postcondition verification
- immutable audit events

AgentActum is not an agent orchestration framework. It integrates with
frameworks such as LangGraph, CrewAI, AutoGen, and custom Python agents.

## Current Development Scope

Build only the core Python library.

Do not build the hosted dashboard, SaaS platform, CrewAI adapter,
AutoGen adapter, automatic skill evolution, or production cloud
infrastructure unless explicitly requested.

## Python Requirements

- Use Python 3.12 or newer.
- Use a src-layout package.
- Use type annotations for public and internal interfaces.
- Use Pydantic models for validated external data.
- Use standard library abstractions where practical.
- Avoid unnecessary production dependencies.
- Do not add a dependency without explaining why it is needed.
- Use async interfaces only where they provide real value.
- Public APIs must have docstrings.

## Architecture Rules

Keep these concerns separate:

- contracts
- policies
- transactions
- approvals
- idempotency
- execution
- compensation
- ledger
- integrations

Business logic must not depend directly on LangGraph or another agent
framework.

Framework integrations must use adapters.

The core package must remain usable without an LLM.

## Safety Rules

- Unknown tools are denied by default.
- High-risk actions must not execute without the required approval.
- A duplicated idempotency key must not cause a duplicated side effect.
- Irreversible actions must not be released before transaction commit.
- Policy failures must fail closed.
- Validation failures must fail closed.
- Audit events must be append-only through the public API.
- Never use real payment, email, database, or cloud credentials in tests.
- Tests must use fake or in-memory tools.
- Do not silently weaken a policy to make a test pass.

## Testing Requirements

For every behavior change:

1. Add or update tests.
2. Run formatting and linting.
3. Run type checking.
4. Run the complete test suite.
5. Review the final diff for regressions.

Required commands:

- `pytest`
- `ruff check .`
- `ruff format --check .`
- `mypy src`

A task is not complete when any required check fails.

## Development Process

For non-trivial work:

1. Inspect existing code.
2. Explain the proposed design.
3. Identify affected files.
4. Implement the smallest complete change.
5. Add tests.
6. Run all relevant checks.
7. Summarize changes, limitations, and remaining risks.

Do not implement unrelated features.

Do not rewrite working modules unless the task requires it.

## Git Expectations

Keep commits focused on one coherent change.

Use commit prefixes:

- `feat:`
- `fix:`
- `test:`
- `docs:`
- `refactor:`
- `chore:`

Do not commit secrets, `.env` files, virtual environments, build
artifacts, databases, or coverage outputs.