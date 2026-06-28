# AgentActum Product Specification

## Status

This document defines the release scope for AgentActum 0.1.0, the first public
alpha of the in-process Python library.

## Product statement

AgentActum is a framework-independent Python runtime for controlling
side-effecting tool actions requested by AI agents or conventional
applications. It sits on the action boundary:

```text
agent or application -> AgentActum runtime -> registered Python tool
```

AgentActum does not plan, route, prompt, or orchestrate agents. It decides
whether and how a specific requested tool action may be attempted.

## Product principles

1. **Fail closed.** Unknown tools, invalid data, policy errors, missing
   approvals, and idempotency conflicts do not become permission to act.
2. **Make effects explicit.** Every executable tool has a contract describing
   its inputs, outputs, risk floor, and effect type.
3. **Keep decisions deterministic.** Version 0.1 uses typed Python policies,
   not LLM-generated policy decisions.
4. **Do not promise impossible atomicity.** AgentActum uses idempotency,
   staging, verification, and compensation, but it is not distributed ACID and
   cannot guarantee universal rollback.
5. **Keep the core independent.** The core package works without an LLM or an
   agent framework. Framework support is adapter-based.

## Core domain terminology

### Tool

A named Python capability whose implementation can be invoked by the runtime.
A tool is unknown until explicitly registered.

### Tool contract

The trusted declaration for one tool: stable name, version, description, input
schema, output schema, risk level, effect type, and idempotency requirement.

### Action intent

An immutable request to invoke one registered tool contract with JSON-compatible
arguments, requester metadata, timestamp, optional context, and optional
idempotency key.

### Effect type

The declared side-effect class of a tool:

- `READ_ONLY`
- `IDEMPOTENT`
- `REVERSIBLE`
- `COMPENSATABLE`
- `STAGEABLE`
- `IRREVERSIBLE`

Reversible and compensatable effects do not mean the original action never
happened. Compensation is recorded recovery, not historical erasure.

### Risk level

The minimum control level for an action:

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

Policies may require stronger controls than the contract floor.

### Policy decision

A deterministic decision returned by trusted policy code:

- `ALLOW`
- `DENY`
- `REQUIRE_APPROVAL`
- `ALLOW_WITH_CONSTRAINTS`

Policy failures fail closed.

### Approval request

A structured request for approval. Version 0.1 includes models and approval
checker hooks; it does not authenticate humans or provide an approval UI.

### Idempotency key

A deterministic key that binds one logical action to selected arguments. Within
one live runtime instance, the same key must not cause the same side effect
twice.

### Transaction

An explicit state machine for governing transaction state. In 0.1 it does not
execute tools itself.

### Compensation

A best-effort recovery action attempted in reverse execution order after later
actions fail. Compensation can fail and is reported separately.

### Outbox

An in-memory staging area for effects that should be released only after a
transaction commits, such as confirmation notifications.

### Ledger

An append-only in-memory sequence of audit events exposed through public append
and read operations. It is not durable or tamper-proof in 0.1.

## Version 0.1 scope

Version 0.1 includes:

- Python 3.12+ src-layout package;
- Pydantic domain models and closed enums;
- in-memory tool registry;
- deterministic typed policy engine;
- in-memory idempotency backend and key generation;
- single-action execution runtime;
- explicit transaction state machine;
- reverse-order compensation coordinator;
- in-memory effect outbox;
- in-memory audit ledger;
- `AgentActum` facade for protecting ordinary Python callables;
- optional LangGraph adapter through `agentactum[langgraph]`;
- pytest, pytest-cov, Ruff, mypy, pre-commit, and CI configuration.

## Functional requirements

### Contracts and registration

- Duplicate tool registration is rejected.
- Contract and handler are stored separately.
- Unknown tools raise typed errors or are denied by runtime evaluation.
- Contract metadata comes from trusted registration, not caller input.

### Policy and risk

- Policies are deterministic Python objects.
- Tool allow/deny, required permissions, risk-based approval, and numeric
  approval thresholds are supported.
- Unknown tools and policy exceptions fail closed.
- Policy evaluation does not execute tools.

### Idempotency

- The in-memory backend atomically reserves a key for one logical action.
- Same-key duplicates do not execute the same side effect twice within one
  runtime instance.
- Same-key use with different intent conflicts.
- Idempotency records do not survive process restart.

### Execution

- Single-action execution resolves the tool, validates input, evaluates policy,
  checks approval, reserves idempotency, checks preconditions, executes,
  checks postconditions, appends ledger events, and returns an
  `ExecutionResult`.
- Validation, policy, approval, idempotency, precondition, execution, and
  postcondition failures return structured failures.

### Transactions

- Legal transaction transitions are explicit.
- Illegal transitions such as `PROPOSED -> COMMITTED`,
  `FAILED -> EXECUTING`, and `REJECTED -> APPROVED` are rejected.
- The transaction state machine does not execute tools.

### Compensation

- Completed actions are compensated in reverse execution order.
- Compensation failure and partial compensation are represented explicitly.
- Irreversible actions are not falsely described as rolled back.

### Outbox

- Stageable operations can be held in memory and released after commit.
- Unknown outbox operations raise typed errors.
- Outbox state is process-local and non-durable.

### Integrations

- `AgentActum` provides a framework-independent decorator for Python callables.
- The optional LangGraph adapter wraps protected callables and lazily creates a
  `langgraph.prebuilt.ToolNode`.
- The core package imports without LangGraph installed.

## Acceptance criteria for 0.1.0

- [x] Package imports successfully.
- [x] Editable installation works.
- [x] Public package version is `0.1.0`.
- [x] Core exports are tested.
- [x] Unknown tools are rejected.
- [x] Duplicate registrations are rejected.
- [x] Policy failures fail closed.
- [x] Idempotency prevents duplicate same-key side effects in one runtime.
- [x] Single-action execution has tests for each failure point.
- [x] Transaction state transitions reject illegal moves.
- [x] Compensation covers success, failure, partial compensation, reverse
      order, irreversible actions, and ledger events.
- [x] Outbox stages and releases in memory.
- [x] Generic facade protects Python callables.
- [x] LangGraph adapter is optional and lazy.
- [x] Tests use fake or in-memory tools only.
- [x] `pytest`, `ruff check .`, `ruff format --check .`, and `mypy src` pass.
- [x] Wheel build succeeds.

## Explicit non-goals for 0.1

- Hosted service, dashboard, SaaS control plane, or network API.
- Microservices, workers, queues, schedulers, or background jobs.
- Persistence, crash recovery, distributed coordination, or cross-process
  locking.
- Real payment, email, database, browser, cloud, or infrastructure
  integrations.
- CrewAI, AutoGen, or additional framework adapters beyond optional LangGraph.
- Agent planning, routing, memory, prompting, or model invocation.
- Authentication, identity proofing, approval UI, or role administration.
- Policy DSL, remote policy engine, or LLM-based policy decisions.
- Sandboxing untrusted Python tool implementations.
- Secret management, encryption key management, or compliance certification.
- Distributed ACID, exactly-once delivery to external systems, or guaranteed
  rollback.

## Differentiation

### Orchestration frameworks

Orchestrators decide which agent, node, or tool runs next. AgentActum governs a
requested action at the moment an effect may be released.

### Guardrail frameworks

Guardrails often filter model input or output. AgentActum enforces lifecycle
constraints around tool side effects: contract validation, policy, approval,
idempotency, verification, compensation, and audit.

### Observability frameworks

Observability records telemetry around activity. AgentActum is on the
enforcement path: denied or unapproved actions do not execute. Its ledger is an
audit primitive, not a full telemetry backend.

### Workflow-durability frameworks

Durable workflow engines persist and resume workflows. AgentActum 0.1 is
process-local and in-memory. It can later be hosted inside durable systems, but
does not pretend to survive restart today.

## Dangerous assumptions to avoid

- "Transaction" does not mean distributed ACID.
- "Idempotency" does not mean cross-process exactly-once delivery.
- "Compensation" does not mean rollback.
- "Ledger" does not mean durable, signed, or tamper-proof storage.
- "Approval" does not mean authentication.
- "Adapter" does not mean the framework is a core dependency.
