# AgentActum Product Specification

## Status

This document defines the intended scope of AgentActum version 0.1. It is a
design specification, not a description of implemented behavior.

## Product statement

AgentActum is a framework-independent, in-process Python runtime that controls
side-effecting tool actions requested by AI agents or conventional software. It
turns an untrusted request to invoke a tool into a validated, policy-governed,
auditable action with explicit failure semantics.

AgentActum sits on the action boundary:

```text
agent or application -> AgentActum runtime -> registered tool implementation
```

It does not decide what an agent should do next. It decides whether and how a
specific requested effect may be attempted.

## Product principles

1. **Fail closed.** Unknown tools, invalid data, policy errors, missing
   approvals, and ambiguous execution outcomes do not become permission to act.
2. **Make effects explicit.** Every executable tool has a contract describing
   its input, output, risk floor, effect kind, verification, and compensation
   capabilities.
3. **Bind decisions to intent.** Policy decisions, approvals, idempotency
   records, execution results, and audit events refer to a stable fingerprint
   of the same normalized action request.
4. **Do not promise impossible atomicity.** A Python library cannot make
   unrelated external systems transactional. AgentActum distinguishes staged,
   committed, compensated, failed, and indeterminate outcomes.
5. **Keep the core independent.** The runtime works without an LLM or an agent
   framework. Integrations are adapters outside the core domain logic.
6. **Prefer the smallest safe semantics.** Version 0.1 deliberately accepts
   fewer transaction shapes rather than silently accepting unsafe ones.

## Intended users

- Library authors adding a controlled execution boundary to an agent system.
- Application developers using custom Python agents or ordinary application
  code that invokes risky tools.
- Security and platform engineers who need enforceable action policies and an
  inspectable event history.

## Core domain terminology

### Tool

A named capability whose implementation can be invoked by the runtime. A tool
is unknown until explicitly registered.

### Tool contract

The validated declaration for a tool: its stable name and version, input and
output schemas, declared risk floor, effect kind, executor, and optional
verifier and compensator. The contract is authoritative runtime configuration,
not text supplied by an agent.

### Action request

An immutable request to invoke one registered tool with arguments, an
idempotency key, and caller-supplied context. Context may inform policy but does
not grant authority by itself.

### Normalized intent

The canonical, validated representation of an action request. Its fingerprint
binds the tool contract identity, normalized arguments, and security-relevant
context. Non-semantic metadata such as tracing labels is excluded by an
explicit rule, never accidentally.

### Risk level

An ordered classification (`low`, `medium`, or `high`) representing the minimum
control required for an action. A policy may raise the contract's risk floor
but may not lower it.

### Effect kind

The declared reversibility of a tool:

- `read_only`: no externally observable state change.
- `reversible`: changes state and has a required compensator.
- `irreversible`: changes state and has no reliable compensator.

“Reversible” means that compensation can be attempted; it does not mean that
the original action never happened or that every consequence can be erased.

### Policy

Trusted application code that evaluates normalized intent and returns a
structured decision. Policies do not execute tools or mutate runtime state.

### Policy decision

An immutable result of policy evaluation: `allow`, `deny`, or
`require_approval`, with effective risk, reason codes, and policy identity.
When policies are combined, precedence is `deny` over `require_approval` over
`allow`.

### Approval request

A pending request for a trusted approver to authorize one exact normalized
intent under one exact policy decision. It is not executable authority.

### Approval grant

A time-bounded, single-use authorization bound to an approval request,
normalized-intent fingerprint, policy decision, approver identity, and runtime
instance. A free-form boolean such as `approved=True` is not an approval grant.

### Idempotency key

A caller-provided key in a defined namespace that identifies one logical
action. The runtime binds it to the normalized-intent fingerprint. Reusing the
key for different intent is a conflict.

### Action outcome

The durable-for-the-process record of what happened to an action, including
pending, succeeded, denied, failed, compensated, or indeterminate status. An
execution error and a known absence of an effect are different outcomes.

### Transaction

An in-process unit that admits and stages one or more actions, then explicitly
commits them. Staging performs no external side effect. A transaction is not a
distributed ACID transaction.

### Commit

The point at which the runtime is permitted to invoke staged effectful tool
implementations. All validation, policy evaluation, required approvals, and
transaction-shape checks must succeed before commit begins.

### Compensation

A best-effort, explicitly recorded action that attempts to semantically undo a
completed reversible effect. Compensation can fail and never rewrites history.

### Postcondition verifier

Trusted code that checks whether the declared result of an execution is
consistent with its expected postcondition. Verification failure does not
prove that no effect occurred.

### Audit event and ledger

An audit event is an immutable fact emitted during processing. The ledger is an
append-only ordered collection exposed through read and append operations; the
public API has no update or delete operation.

### Indeterminate outcome

An outcome for which AgentActum cannot establish whether an external effect
occurred or remains in force. It requires reconciliation and must never be
automatically treated as safe to retry.

## Version 0.1 scope

Version 0.1 is a synchronous, in-process Python 3.12+ library with:

- explicit registration of versioned tool contracts;
- Pydantic validation of action inputs and declared outputs;
- `low`, `medium`, and `high` risk floors;
- deterministic policy evaluation with fail-closed composition;
- mandatory approval for every effective high-risk action;
- in-process approval requests, grants, rejection, and expiration;
- atomic, thread-safe in-memory idempotency claims and outcome replay;
- explicit in-process transactions with effect-free staging;
- ordered commit, postcondition verification, and reverse-order compensation;
- an append-only, thread-safe in-memory audit ledger;
- structured outcomes and domain-specific errors;
- fake/in-memory tools in tests and examples only.

A single-action request may use an implicit transaction. Multi-action
transactions use the same admission and commit rules.

### Transaction restrictions in 0.1

- Staging must not invoke the tool executor, verifier, or compensator.
- Every reversible tool must declare a compensator.
- A transaction may contain at most one irreversible action.
- If present, the irreversible action must execute last.
- Read-only actions used as preconditions should run before effectful actions.
- A transaction with an outcome that may include an unverified external effect
  becomes `indeterminate`; it is not reported as rolled back.

These restrictions reduce, but cannot eliminate, partial external outcomes.

## Conceptual action lifecycle

```text
received
  -> contract lookup and validation
  -> normalized-intent fingerprint
  -> policy evaluation
  -> denied
     or idempotency claim
       -> approval pending -> approved/rejected/expired
       or admitted
  -> staged
  -> commit started
  -> executed -> output validated -> verified -> succeeded
     or failure -> compensate completed reversible effects
                -> failed / compensated / indeterminate
```

The exact public API will be settled during implementation, but the domain
transitions and invariants in this specification are normative.

## Functional requirements

### Contracts and registration

- Registration rejects duplicate tool name/version pairs.
- Contract input is validated before policy evaluation or staging.
- Contract output is validated before success can be reported.
- Unknown or ambiguous tool versions are denied.
- Risk and effect metadata come from trusted registration, not agent input.

### Policy and risk

- Policy evaluation receives immutable normalized intent.
- A policy exception, timeout mechanism failure, or malformed decision denies
  the action.
- Effective risk can only equal or exceed the contract risk floor.
- Effective high risk always produces `require_approval` or `deny`.
- Reasons are machine-readable and suitable for audit without exposing secrets.

### Approval

- An approval grant is valid only for its exact pending request and fingerprint.
- Rejection and expiry are terminal for that pending action.
- Grants are single-use and cannot authorize another action.
- Approver identity is supplied by a trusted host integration. Version 0.1 does
  not authenticate humans or provide an approval user interface.

### Idempotency

- A key is atomically claimed for one fingerprint before an action can become
  approval-pending or staged.
- Concurrent duplicate requests cannot invoke the executor more than once.
- A completed duplicate returns the recorded outcome.
- A duplicate still in progress returns the same pending identity or a
  structured in-progress outcome; it does not execute again.
- Reuse with a different fingerprint returns an idempotency conflict.
- Failed and indeterminate records remain claimed. Automatic retry requires a
  future explicit retry protocol and is out of scope for 0.1.

### Execution, verification, and compensation

- Effectful executors run only during commit.
- Successful output must pass contract validation and any configured verifier.
- On a later commit failure, completed reversible effects are compensated in
  reverse execution order.
- Every compensation attempt and result is recorded.
- A verifier or compensator exception is contained and converted into a safe,
  structured failure outcome.
- AgentActum never labels a transaction “rolled back” merely because
  compensation was attempted.

### Audit

- Events cover receipt, validation failure, policy result, approval lifecycle,
  idempotency conflict/replay, staging, commit, execution, verification,
  compensation, and terminal outcome as applicable.
- Events have stable identifiers, timestamps, sequence numbers, correlation
  identifiers, event types, and redacted structured details.
- Reading the ledger returns immutable event values or defensive copies.
- Secret values and raw credentials are excluded by default.

## Acceptance criteria for version 0.1

Version 0.1 is acceptable only when automated tests demonstrate all of the
following:

1. A registered read-only fake tool with valid input can execute and return a
   validated, audited result.
2. Unknown tools and invalid inputs do not invoke any executor and produce
   denial/failure audit events.
3. Policy denial and policy exceptions do not invoke any executor.
4. A high-risk fake tool cannot execute without a valid, unexpired grant bound
   to the exact request; altered arguments invalidate authorization.
5. Reusing an idempotency key with the same intent replays the outcome without
   a second side effect; reuse with different intent fails with a conflict.
6. Two concurrent callers using the same key cannot cause two executions.
7. Staging an action produces no external side effect.
8. An irreversible action is never invoked before commit and unsafe transaction
   shapes are rejected before any effect.
9. Failure after reversible actions triggers reverse-order compensation and
   records each attempt without claiming guaranteed rollback.
10. Execution, output-validation, verification, and compensation exceptions are
    contained and result in the specified failed or indeterminate state.
11. The public ledger API cannot edit or delete events, and returned event data
    cannot mutate stored history.
12. The core test suite uses only fake or in-memory tools and no real service
    credentials.
13. Public APIs are typed and documented, and `pytest`, `ruff check .`,
    `ruff format --check .`, and `mypy src` all pass on supported Python.
14. The package can be imported and used without an LLM SDK or agent-framework
    dependency.

## Explicit non-goals for version 0.1

- Hosted service, dashboard, SaaS control plane, or network API.
- Microservices, distributed coordination, or cross-process locking.
- Persistence or recovery across process restart.
- Distributed ACID transactions or exactly-once delivery to external systems.
- Guaranteed rollback of external side effects.
- Real payment, email, database, cloud, browser, or infrastructure integrations.
- LangGraph, CrewAI, AutoGen, or other framework adapters.
- Agent planning, routing, memory, prompting, or model invocation.
- Authentication, identity proofing, role administration, or an approval UI.
- A policy language, remote policy engine, or policy authoring UI.
- Sandboxing untrusted Python tool implementations.
- Secret management, encryption key management, or compliance certification.
- Async execution, background workers, queues, scheduling, retries, or timeouts
  that require process isolation.
- Automatic skill evolution or tool-contract inference.
- Stable serialization or storage compatibility guarantees before a persistence
  design exists.

## Adjacent categories and differentiation

### Orchestration frameworks

Orchestrators decide which agent, node, or tool runs next and manage prompts,
state graphs, and delegation. AgentActum does not plan or route. An orchestrator
calls AgentActum at the moment it wants a tool effect controlled.

### Guardrail frameworks

Guardrails commonly filter model inputs/outputs or classify content. AgentActum
may consume a policy classification, but its defining job is enforcing action
lifecycle invariants around real side effects: approval binding, idempotency,
commit gating, verification, and compensation.

### Observability frameworks

Observability systems record traces, metrics, and logs after or around activity.
AgentActum emits audit facts, but it is on the enforcement path: a denied or
unapproved action does not execute. Its ledger is an accountability primitive,
not a full telemetry backend.

### Workflow-durability frameworks

Durable workflow engines persist execution state, resume after crashes, and
coordinate retries or workers. Version 0.1 does none of those things. It defines
safe in-process action semantics that could later be hosted inside a durable
workflow, without pretending that its memory survives a restart.

## Ambiguities and dangerous assumptions

The following product claims require care and are resolved conservatively for
0.1:

- **“Transaction” can imply ACID.** Here it means admission, effect-free
  staging, ordered release, verification, and best-effort compensation within a
  process. External atomicity is explicitly not promised.
- **“Exactly once” is usually unprovable.** In-memory idempotency prevents
  duplicate calls through one live runtime instance. A crash or an external
  timeout can leave an indeterminate effect.
- **“Compensation” is not erasure.** An email cannot be unsent and a refund does
  not erase a charge. Contracts must classify such actions honestly.
- **Verification can itself have side effects or stale reads.** Verifiers are
  trusted contract code and should be read-only; 0.1 cannot sandbox them.
- **Risk is contextual.** A static contract value is a floor, while trusted
  policies may raise risk using arguments and host-provided identity/context.
- **Approval is not authentication.** The host must establish approver identity;
  AgentActum only binds and consumes the resulting grant.
- **An audit ledger is not automatically tamper-proof.** The 0.1 API is
  append-only, but in-memory data offers no protection against a malicious host
  process or restart loss.
- **Tool code is trusted.** A malicious executor can bypass the runtime, lie
  about effects, mutate globals, or exfiltrate secrets. Process sandboxing is a
  separate concern.
- **The host can bypass the runtime.** AgentActum cannot intercept arbitrary
  Python calls. The embedding application must expose tool capability only
  through the runtime when enforcement is required.
- **Threads create races even in one process.** Claims, grant consumption,
  transaction transitions, and ledger sequencing must be atomic.
- **Canonicalization is security-sensitive.** Fingerprints must be computed
  from validated canonical data and contract identity, with a documented
  serialization rule.

## Decisions deferred beyond 0.1

- Persistent store interfaces and crash-recovery protocol.
- Async API and cancellation semantics.
- Cross-process idempotency and approval services.
- Safe retries and reconciliation for indeterminate outcomes.
- Stronger ledger integrity, signing, export, and retention.
- Nested transactions and richer irreversible-action scheduling.
- Adapter APIs for specific agent frameworks.
