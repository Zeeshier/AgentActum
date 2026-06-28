# Changelog

All notable changes to AgentActum are documented here.

## 0.1.0 - 2026-06-28

First public alpha release.

### Added

- Python 3.12+ src-layout package with Apache-2.0 licensing.
- Core domain enums and Pydantic models for tool contracts, action intents,
  policy decisions, approvals, transactions, ledger events, execution results,
  and compensation results.
- In-memory tool registry with duplicate-registration rejection and typed
  unknown-tool errors.
- Deterministic policy engine with allow/deny rules, permission checks,
  risk-based approval requirements, numeric approval thresholds, unknown-tool
  denial, and fail-closed error handling.
- In-memory idempotency backend and deterministic key generation.
- Single-action execution runtime with validation, policy evaluation, approval
  checks, idempotency reservation, preconditions, postconditions, ledger
  events, and structured results.
- Explicit transaction state machine.
- Reverse-order compensation coordinator with partial/failure reporting.
- In-memory effect outbox for staging release-after-commit operations.
- Framework-independent `AgentActum` facade for protecting ordinary Python
  callables.
- Optional `agentactum[langgraph]` extra and lazy LangGraph adapter.
- CI, pytest, pytest-cov, Ruff, mypy, and pre-commit configuration.

### Security and safety notes

- Unknown tools, validation failures, policy failures, missing approvals, and
  idempotency conflicts fail closed.
- The in-memory ledger, idempotency backend, and outbox are process-local and
  do not survive restart.
- Compensation is best-effort semantic recovery. It is not rollback and does
  not erase the fact that an external effect may have occurred.
- The optional LangGraph adapter is isolated from the core import path and does
  not add LangGraph as a required dependency.

### Non-goals

- No hosted service, dashboard, network API, microservice, worker process, or
  durable workflow runtime.
- No real payment, email, database, browser, cloud, or infrastructure
  integrations.
- No authentication system, approval UI, policy DSL, LLM policy evaluator, or
  agent orchestration runtime.
