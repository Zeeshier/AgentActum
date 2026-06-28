# AgentActum Development Roadmap

## Purpose

This roadmap records the completed 0.1 milestone sequence and the work
deliberately deferred after the first release. It is not authorization to build
a hosted product, real external integrations, or production cloud
infrastructure.

## Version 0.1 release definition

Version 0.1 is a Python 3.12+ in-process library that lets an application
register synchronous fake or application-provided tools and route single tool
actions through contracts, deterministic policy checks, approval checks,
idempotency, execution validation, compensation primitives, effect staging, and
append-only audit events.

It intentionally does not survive restart and does not coordinate state across
processes. The only framework-specific work in 0.1 is the optional LangGraph
adapter, which remains outside the core import path.

## Completed 0.1 milestones

### Milestone 1 - Project foundation

Delivered a Python 3.12+ src-layout package with pytest, pytest-cov, Ruff,
mypy, pre-commit, Apache-2.0 metadata, CI, README, and package smoke test.

### Milestone 2 - Core domain contracts

Delivered the closed enums and Pydantic domain models for contracts, action
intents, policy decisions, approval requests, transactions, ledger events,
execution results, and compensation results.

### Milestone 3 - Tool registry

Delivered an in-memory registry with explicit contract/handler separation,
duplicate-registration rejection, unknown-tool typed errors, and no global
singleton state.

### Milestone 4 - Policy engine

Delivered deterministic typed Python policies for allow/deny, required
permissions, risk-based approval, numeric approval thresholds, unknown-tool
denial, and fail-closed evaluation.

### Milestone 5 - Idempotency

Delivered deterministic idempotency-key generation, an `IdempotencyBackend`
protocol, and an in-memory backend that prevents the same key from producing a
second side effect through one runtime instance.

### Milestone 6 - Single-action execution

Delivered the single-action runtime pipeline: resolve tool, validate contract,
evaluate policy, check approval, reserve idempotency, check preconditions,
execute, check postconditions, write ledger events, and return a structured
result.

### Milestone 7 - Transaction state machine

Delivered explicit legal transaction transitions and typed rejection of illegal
state changes. The state machine governs state only and does not execute tools.

### Milestone 8 - Compensation

Delivered reverse-order compensation coordination, successful compensation,
compensation failure, partial compensation, irreversible-action handling, and
ledger event creation.

### Milestone 9 - Effect outbox

Delivered an in-memory outbox for staging operations that should only be
released after a commit decision.

### Milestone 10 - Generic agent integration

Delivered the framework-independent `AgentActum` facade and
`@actum.protect(contract=...)` callable decorator.

### Milestone 11 - LangGraph adapter

Delivered an optional `agentactum.langgraph` adapter, `agentactum[langgraph]`
extra, lazy `ToolNode` construction, and tests proving the core package does
not export or require LangGraph.

### Milestone 12 - Documentation and first release

Delivered release-facing README updates, changelog, release checklist, version
`0.1.0`, and documentation reconciliation for the implemented 0.1 scope.

## Version 0.1 acceptance checklist

- [x] Known, valid action succeeds with validated output and audit events.
- [x] Unknown tools and invalid inputs fail without executor invocation.
- [x] Policy denial and policy failure fail closed.
- [x] High-risk and critical-risk actions require approval by policy.
- [x] Same-key duplicates replay; changed intent conflicts.
- [x] Concurrent same-key requests cause at most one invocation in one runtime
      instance.
- [x] Transaction state transitions are explicit and illegal transitions fail.
- [x] Compensation runs in reverse order and records partial/failure states.
- [x] Stageable effects can be held in an in-memory outbox until release.
- [x] Ledger events are append-only through the public API.
- [x] Core imports without any LLM or agent-framework package.
- [x] Optional LangGraph support remains outside the core import path.
- [x] Required project checks pass on supported Python.

## Deferred roadmap candidates

These are candidates, not commitments:

### Persistence and recovery

Add store protocols and durable implementations for idempotency, ledger,
outbox, approvals, and transaction state. This requires crash reconciliation,
schema migrations, and cross-process concurrency rules.

### Richer approval lifecycle

Add a real approval service boundary, authenticated approver identity adapter,
expiry handling, rejection lifecycle, and grant consumption APIs. Version 0.1
only provides approval models and checker hooks.

### Multi-action transaction execution

Extend beyond the state machine and compensation coordinator into full
multi-action admission, staging, commit, verification, compensation, and
outbox release orchestration.

### Async and cancellation

Add async interfaces only after specifying cancellation behavior during
external calls, task ownership, async locking, and compatibility with
synchronous contracts.

### Additional framework adapters

Add adapters such as CrewAI, AutoGen, or others only as thin translation layers.
No framework type should enter core domain models or runtime logic.

### External integrations

Add integrations one at a time with fake contract tests, explicit idempotency
and reconciliation behavior, credential boundaries, and honest reversibility
classification. No real integration belongs in core.

### Stronger audit and policy infrastructure

Potential work includes durable/exportable ledgers, cryptographic integrity,
remote policy evaluation, policy configuration files, and retention controls.
Each adds a new trust boundary and requires a separate threat model.

## Explicit non-goals

- Dashboard, hosted service, SaaS platform, or microservice deployment.
- Production cloud infrastructure or operational control plane.
- Real payment, email, database, cloud, browser, or infrastructure
  integrations in core.
- Agent orchestration, model hosting, prompting, or automatic skill evolution.
- Distributed ACID, universal exactly-once effects, or guaranteed rollback.
- Silent policy weakening, automatic retry of uncertainty, or safety-record
  eviction to improve convenience.

## Release risks to repeat in release notes

- Public names may accidentally promise stronger durability than delivered.
- In-memory idempotency prevents duplicate release only within one live runtime
  instance.
- Callback exceptions can conceal partial external effects.
- Audit payloads can leak secrets if contract authors put secrets into
  non-redacted fields.
- In-memory records grow without eviction and disappear on restart.
- Successful compensation is not erasure of the original effect.
