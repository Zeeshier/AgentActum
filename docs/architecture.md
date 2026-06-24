# AgentActum Architecture

## Status and scope

This document proposes the architecture for version 0.1. It defines boundaries
and behavior without implementing production code. The runtime is a synchronous,
in-process Python 3.12+ library and remains usable without an LLM.

## Architectural goals

- Put one enforceable boundary between an action requester and trusted tool
  implementations.
- Keep contracts, policies, approvals, idempotency, transactions, execution,
  compensation, ledger, and integrations separate.
- Make every security-relevant state transition explicit and auditable.
- Provide deterministic behavior under concurrent threads in one process.
- Preserve truthful failure semantics when external state is uncertain.
- Allow later persistence or framework adapters without embedding them in core
  business logic now.

## Context

```text
Untrusted or partially trusted                 Trusted application boundary

Agent/framework/application
        |
        | ActionRequest
        v
+------------------------- AgentActum --------------------------+
| contracts -> policy -> approval/idempotency -> transaction   |
|                                         -> execution/verify   |
|                                         -> compensation      |
| every transition ----------------------> audit ledger         |
+---------------------------------------------------------------+
        |
        | validated invocation during commit only
        v
Registered Python tool implementation -> external system (optional)
```

The host application, registered contracts, policies, approver-identity adapter,
and tool implementations are trusted. Action requests and tool data are not.

## Proposed package boundaries

The eventual src-layout is expected to follow these logical boundaries. Names
are provisional until implementation, but dependency direction is normative.

```text
src/agentactum/
  models.py          shared immutable value objects and enums
  contracts.py       tool contract declaration and registry
  policies.py        policy protocol, decisions, composition
  approvals.py       approval request/grant lifecycle
  idempotency.py     atomic claim and outcome records
  transactions.py   transaction state machine and shape validation
  execution.py       executor invocation and output verification
  compensation.py    reverse-order compensation coordination
  ledger.py          audit event model and append/read protocol
  runtime.py         use-case orchestration across the above services
  errors.py          structured domain errors
  integrations/      future adapters; empty or absent in 0.1
```

No module in the core imports LangGraph, CrewAI, AutoGen, an LLM SDK, or a real
external-service client.

### Dependency rule

Shared value objects are dependency leaves. The runtime composes services; the
services do not call back into the runtime. Policies do not depend on execution.
Tool contracts describe callbacks but do not perform registration-time effects.
Ledger recording observes domain transitions but does not decide them.

```text
models/errors
   ^
   +-- contracts, policies, approvals, idempotency, ledger
   ^
   +-- transactions, execution, compensation
   ^
   +-- runtime
   ^
   +-- integrations (future)
```

## Components and responsibilities

### Models

Pydantic models validate external-facing data such as action requests,
structured policy decisions, approval material, results, and audit records.
Internal state may use frozen dataclasses where validation at a trust boundary
is unnecessary. Public models should be immutable where practical.

Security-relevant identifiers use opaque UUIDs. Timestamps are timezone-aware
UTC. Enums are closed and unknown values fail validation.

### Contract registry

The registry maps an exact `(tool_name, contract_version)` to one `ToolContract`.
It rejects duplicates and supplies no permissive fallback. A contract contains:

- exact identity and human-readable description;
- Pydantic input and output model types;
- risk floor and effect kind;
- synchronous executor callback;
- optional read-only verifier callback;
- required compensator callback for reversible effects;
- audit-field classification or redaction metadata.

Registration is expected during application startup. Contract mutation after
registration is prohibited; changing behavior requires a new version.

### Policy engine

A policy implements a small synchronous protocol:

```text
evaluate(normalized_intent, trusted_context) -> PolicyDecision
```

The engine validates every decision and combines multiple policies with strict
precedence: deny, then require approval, then allow. It enforces the contract
risk floor after composition. Any exception or invalid result becomes a denial
and an audit event.

Policies are pure with respect to AgentActum: they do not execute tools, issue
grants, append directly to the ledger, or mutate a transaction.

### Approval service

The in-memory approval service owns pending requests and single-use grants. It:

- creates a pending approval bound to fingerprint and policy decision;
- accepts a trusted approver identifier and expiry when the host grants it;
- records rejection and expiration;
- atomically consumes a matching grant during admission;
- rejects replay, mismatch, expiration, or use in another runtime instance.

The service does not authenticate an approver. That trust boundary belongs to
the embedding application and must be named clearly in the API.

### Idempotency store

The in-memory store atomically maps a namespaced idempotency key to:

- normalized-intent fingerprint;
- action and transaction identifiers;
- lifecycle status;
- pending approval identity, if any;
- terminal action outcome, if any.

A lock protects compare-and-claim and state transitions. Same-key/same-intent
duplicates observe the existing record. Same-key/different-intent requests
receive a conflict. Terminal failure and indeterminate records are retained for
the runtime lifetime and are not automatically released.

### Transaction coordinator

The coordinator owns an explicit state machine and a list of admitted actions.
It validates the entire transaction shape before commit:

- all actions have passed validation, policy, approval, and idempotency checks;
- reversible actions have compensators;
- no more than one irreversible action exists;
- any irreversible action is ordered last;
- transaction and action states permit the requested transition.

Staging stores immutable invocation plans only. It invokes no executor,
verifier, or compensator.

### Execution service

During commit, the execution service invokes a staged executor, validates its
declared output, and invokes the optional verifier. It catches ordinary
exceptions at the trust boundary and returns structured execution facts.

It does not retry. It cannot assume that an exception means no side effect. An
exception from an effectful executor therefore generally yields an
`indeterminate` action unless the contract can provide trustworthy evidence
that no effect occurred.

### Compensation coordinator

When commit fails after reversible actions completed, the coordinator attempts
their compensators in reverse execution order. It records each attempt and
continues best-effort after a compensation failure so the full recovery picture
is known. It never changes a historical “executed” fact or describes attempted
compensation as atomic rollback.

### Audit ledger

The v0.1 ledger is an in-memory, thread-safe append-only sequence. Only the
ledger implementation allocates monotonic sequence numbers. Consumers can
append typed events through the public protocol and read snapshots; there is no
public update/delete operation.

The ledger is operational evidence, not a decision engine. Failure to append a
required pre-effect event prevents execution. Failure to append after a
possibly completed effect makes the action indeterminate and must surface to
the caller.

### Runtime facade

The runtime is the sole high-level entry point for action admission and commit.
It coordinates the components but contains no framework-specific behavior. It
offers conceptual operations such as:

- register a contract;
- request or stage an action;
- approve or reject a pending request;
- create, commit, or abort a transaction;
- retrieve an outcome or audit snapshot.

Exact method names are intentionally deferred until implementation tests can
exercise the ergonomics.

## Normalized intent and fingerprinting

The normalized-intent fingerprint is a security boundary. Version 0.1 should:

1. validate arguments into the contract's Pydantic input model;
2. serialize the validated data in canonical JSON form with deterministic key
   ordering and documented handling for supported scalar types;
3. include a fingerprint schema version, tool name, contract version, normalized
   arguments, and explicitly enumerated security-relevant context;
4. hash the bytes with SHA-256 from the standard library.

Arbitrary `repr()`, unordered mappings, object addresses, timestamps generated
during processing, and non-security trace metadata must not influence the
fingerprint. Secrets should be hashed into the fingerprint when semantically
required but redacted from audit event details.

## Action admission sequence

```text
1. Append action_received (redacted).
2. Resolve exact tool contract; unknown means deny.
3. Validate and normalize arguments; invalid means fail closed.
4. Compute normalized-intent fingerprint.
5. Evaluate and validate policies; error means deny.
6. Enforce the risk floor and mandatory high-risk approval rule.
7. Atomically inspect/claim the idempotency key before creating any pending
   approval or staging an allowed action.
   - different fingerprint: conflict
   - existing same fingerprint: return existing state/outcome
8. If approval is required, create one pending request and return pending.
9. On resume, atomically validate and consume the exact grant.
10. Create an immutable invocation plan and stage it without effects.
```

Policy denial occurs before a claim, allowing a later request to be evaluated
against a deliberately changed policy. The idempotency claim still precedes
creation of a pending approval, so concurrent duplicates cannot create
separately approvable copies. A validation failure before a trustworthy
fingerprint exists is audited but does not claim the key.

## Transaction state machine

```text
OPEN -> STAGED -> COMMITTING -> COMMITTED
  |        |          |
  +------> ABORTED    +-> COMPENSATING -> COMPENSATED
                         |                  |
                         +-----------------> FAILED
                         +-----------------> INDETERMINATE
```

- `OPEN`: accepts admitted invocation plans.
- `STAGED`: closed to additions; whole shape validated; no effect has run.
- `COMMITTING`: effects may be in progress; cancellation cannot imply abort.
- `COMMITTED`: all outputs validated and postconditions verified.
- `ABORTED`: no effect was released.
- `COMPENSATING`: recovery is being attempted for completed reversible effects.
- `COMPENSATED`: all required compensations reported success; history still
  shows that effects occurred.
- `FAILED`: the runtime knows the intended effects are not in force, or failure
  occurred before an effect.
- `INDETERMINATE`: the runtime cannot establish the external state.

Terminal transitions are one-way. Calling commit twice returns the recorded
outcome and does not rerun executors.

## Commit algorithm

1. Acquire the transaction transition lock and atomically move `STAGED` to
   `COMMITTING`; reject any other source state.
2. Append `commit_started`. If that fails, invoke nothing and fail closed.
3. Execute read-only/precondition actions, then reversible actions in declared
   order, then the optional irreversible action last.
4. For each action, record attempt, executor result or exception, output
   validation, and verifier result.
5. On success, atomically record terminal outcomes and append `commit_succeeded`.
6. On failure before the irreversible action, compensate completed reversible
   actions in reverse order.
7. On failure during or after an irreversible action, report `indeterminate`
   unless trustworthy verification establishes a more precise state; compensate
   earlier reversible effects where doing so remains appropriate.
8. Preserve idempotency records for every admitted action.

Locks protect internal transitions but are not held while arbitrary tool code
runs. The transaction remains visibly `COMMITTING`, and duplicate commit calls
observe rather than duplicate that work. The implementation must define safe
coordination (for example a condition variable) without deadlocking callbacks.

## Failure model

The runtime distinguishes these cases:

- **Rejected before effect:** denied, invalid, approval missing, idempotency
  conflict, or unsafe transaction shape. No tool executor ran.
- **Known execution failure without effect:** possible only when trustworthy
  contract semantics establish absence of an effect.
- **Failure after reversible effect:** compensation is attempted and separately
  reported.
- **Executor transport/timeout-style error:** external effect may have happened;
  outcome is indeterminate.
- **Output validation or verification failure:** execution already occurred;
  compensate if reversible, otherwise indeterminate.
- **Audit failure before release:** fail closed without effect.
- **Audit failure after release:** surface indeterminate because evidence is
  incomplete even if the executor returned success.

`BaseException` subclasses used for interpreter shutdown are not converted into
ordinary success or failure. Recovery after process termination is outside 0.1.

## Concurrency model

The API is synchronous, but multiple host threads may call one runtime. The
registry, approval service, idempotency store, transaction state, and ledger
must protect shared mutable state. Atomicity is required for:

- contract registration uniqueness;
- idempotency compare-and-claim;
- approval grant creation and consumption;
- transaction state transitions and single commit ownership;
- ledger sequence allocation and append.

No guarantee spans multiple runtime instances or processes. Users must not
interpret the Python GIL as the synchronization design.

## Extension boundaries after 0.1

Store protocols may later gain persistent implementations, and integrations may
translate framework tool calls into `ActionRequest` values. Such work must keep
domain models and state machines independent of a vendor SDK. Async support
will require an explicit cancellation and locking design rather than wrapping
synchronous methods mechanically.

## How this architecture relates to adjacent systems

- **Orchestration:** sits above the runtime and decides what to request next;
  AgentActum only governs a requested action.
- **Guardrails:** can feed policy signals, while AgentActum enforces effect
  release and lifecycle constraints.
- **Observability:** can consume AgentActum events, while the ledger remains a
  security-relevant append-only record on the enforcement path.
- **Durable workflows:** can host a future persistent AgentActum execution, but
  v0.1 neither checkpoints nor resumes workflows.

## Architectural non-goals

Version 0.1 has no network boundary, database, worker process, queue, UI,
framework adapter, real service integration, policy DSL, plugin discovery,
untrusted-code sandbox, or crash recovery. It does not claim distributed
transactions, exactly-once external effects, or tamper-proof storage.
