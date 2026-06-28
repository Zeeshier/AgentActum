# AgentActum Security Invariants

## Purpose

This document defines properties that version 0.1 must preserve even when
requests are malformed, policies or tools raise exceptions, callers race, or an
external outcome is uncertain. A test that conflicts with an invariant must not
be made to pass by weakening the invariant.

## Threat model and trust boundaries

### In scope

- An agent or caller may invent tool names, arguments, risk claims, identities,
  idempotency keys, approval identifiers, or transaction identifiers.
- Two or more threads may submit duplicates or race approval and commit calls.
- Policy, executor, verifier, and compensator callbacks may fail unexpectedly.
- Tool output may be malformed or inconsistent with the declared postcondition.
- An external call may time out or fail after applying its side effect.
- Audit details may contain values that should not be disclosed.

### Trusted in version 0.1

- The embedding Python process and application administrator.
- Registered contract definitions and callback code, except for accidental
  failures that the runtime contains.
- Policy configuration.
- The host integration that supplies authenticated approver identity.
- Python and required runtime dependencies.

### Out of scope

- A malicious host process that reads or mutates memory directly.
- Sandboxing hostile Python callbacks.
- Process crashes, machine loss, rollback of system clocks, or restart recovery.
- Attacks on real external services, because 0.1 ships no such integrations.
  The optional LangGraph adapter is a framework adapter, not an external
  service integration.
- Cryptographic tamper evidence or durable audit retention.
- Preventing the trusted host application from calling a tool implementation
  directly instead of routing it through AgentActum.

## Normative invariants

The identifiers below should be referenced by implementation tests and security
reviews.

### Contract and validation

**INV-CON-01 — Known contract only.** An executor may be invoked only through an
exact, currently registered tool name and contract version. Unknown or
ambiguous tools are denied.

**INV-CON-02 — Trusted metadata.** Risk floor, effect kind, schemas, verifier,
and compensator are taken only from the registered contract. Request data cannot
override them.

**INV-CON-03 — Input before policy or effect.** Arguments must validate against
the contract input schema before they are admitted, approved, staged, or passed
to an executor.

**INV-CON-04 — Output before success.** An action cannot be reported successful
until its output validates against the declared output schema and its configured
postcondition passes.

**INV-CON-05 — Immutable contract identity.** A registered contract cannot be
silently replaced. Behavior changes require a distinct contract version.

### Policy and risk

**INV-POL-01 — Fail closed.** A missing policy decision, policy exception,
invalid decision, or policy-composition failure results in denial without tool
execution.

**INV-POL-02 — Deny precedence.** When decisions are composed, any denial wins;
otherwise approval requirement wins over allow.

**INV-POL-03 — Risk cannot be lowered.** Effective risk must never be below the
registered contract risk floor.

**INV-POL-04 — High risk requires approval.** No effective high-risk action may
be staged for commit without a valid approval grant. A policy cannot bypass this
rule by returning allow.

**INV-POL-05 — Policy has no execution authority.** Evaluation cannot directly
release a staged effect through an AgentActum service API.

### Intent and approval binding

**INV-INT-01 — Canonical binding.** Policy results, approvals, idempotency
records, invocation plans, outcomes, and audit correlation bind to the same
normalized-intent fingerprint.

**INV-INT-02 — Complete semantic identity.** The fingerprint includes the tool
name, contract version, validated arguments, schema version, and all enumerated
security-relevant context.

**INV-APP-01 — Exact grant.** A grant authorizes only its exact approval request,
intent fingerprint, policy decision, runtime instance, and validity window.

**INV-APP-02 — Single use.** Grant consumption is atomic. A consumed, rejected,
expired, mismatched, or unknown grant cannot authorize execution.

**INV-APP-03 — No caller self-approval.** Caller-supplied `approved` flags,
approver names, or grant-shaped data do not create authority. Only the trusted
approval service can issue a grant from host-authenticated input.

**INV-APP-04 — Mutation invalidates approval.** Any security-relevant change to
an approved request requires a new policy evaluation and approval.

### Idempotency

**INV-IDEM-01 — Atomic claim.** A namespaced idempotency key is atomically bound
to one intent fingerprint before approval-pending or staging.

**INV-IDEM-02 — No duplicate release.** Within one runtime instance, concurrent
same-key/same-intent requests cause at most one executor invocation for the
logical action.

**INV-IDEM-03 — Conflict on changed intent.** Same-key/different-fingerprint use
is rejected and audited; it never aliases to an existing outcome.

**INV-IDEM-04 — Terminal replay.** Same-key/same-intent after completion returns
the recorded outcome without re-execution.

**INV-IDEM-05 — Uncertain records remain claimed.** Failed, compensated, and
indeterminate outcomes are not automatically cleared or retried.

**INV-IDEM-06 — Scope is honest.** In-memory idempotency is never described as
surviving process restart or coordinating separate runtime instances.

### Transaction and effect release

**INV-TXN-01 — Staging is effect-free.** Staging invokes no executor, verifier,
or compensator and performs no contract-defined external side effect.

**INV-TXN-02 — Complete admission before commit.** All staged actions must pass
contract validation, policy, approval, idempotency, and transaction-shape checks
before commit begins.

**INV-TXN-03 — Single commit owner.** A transaction can transition from staged
to committing once. Repeated or concurrent commit requests cannot duplicate
execution.

**INV-TXN-04 — Irreversible effects are gated.** An irreversible executor is
never invoked before commit, a transaction contains at most one, and it executes
after read-only and reversible actions.

**INV-TXN-05 — Invalid shape has no effect.** An unsafe transaction shape is
rejected before any staged executor runs.

**INV-TXN-06 — Terminal states do not reopen.** Committed, aborted, compensated,
failed, and indeterminate transactions cannot return to an executable state.

**INV-TXN-07 — No false rollback claim.** The runtime never equates abort with
compensation and never labels compensated external history as if it never
happened.

### Execution, verification, and compensation

**INV-EXE-01 — Invocation plan integrity.** Execution uses the immutable,
approved invocation plan, not caller data resubmitted at commit time.

**INV-EXE-02 — Exception containment.** Ordinary exceptions from executor,
verifier, or compensator callbacks cross the boundary only as structured failure
facts; they cannot be interpreted as permission or success.

**INV-EXE-03 — Uncertainty is preserved.** If the runtime cannot establish
whether an effect occurred or remains, the outcome is indeterminate rather than
success, clean failure, or safe retry.

**INV-EXE-04 — Reverse recovery order.** After a later action fails, completed
reversible effects are considered for compensation in reverse execution order.

**INV-EXE-05 — Compensation is recorded separately.** The original execution
fact and every compensation attempt/result remain visible. Compensation failure
does not erase or overwrite prior history.

**INV-EXE-06 — Verifiers are non-authorizing.** A verifier may confirm or reject
a postcondition but cannot grant approval, change policy, or cause another tool
to execute through the runtime.

### Audit ledger

**INV-AUD-01 — Append-only public API.** Public ledger operations provide append
and read, with no update, replacement, truncation, or deletion operation.

**INV-AUD-02 — Immutable reads.** A caller cannot mutate stored history by
modifying an event value returned from a ledger read.

**INV-AUD-03 — Total in-process order.** Event sequence allocation and append are
atomic, producing a unique monotonic sequence within one ledger instance.

**INV-AUD-04 — Pre-effect audit gate.** Failure to record a required decision or
commit-start event prevents effect release.

**INV-AUD-05 — Post-effect audit failure is unsafe.** If a required event cannot
be recorded after an effect may have happened, the runtime surfaces an
indeterminate outcome and does not fabricate a complete history.

**INV-AUD-06 — Secret minimization.** Audit details exclude raw credentials,
approval secrets, and fields marked secret by the contract. Error text is
sanitized before recording.

**INV-AUD-07 — Honest integrity claim.** The in-memory append-only interface is
not described as cryptographically tamper-proof, durable, or resistant to a
malicious host.

### Concurrency and lifecycle

**INV-CONC-01 — Atomic shared transitions.** Contract registration,
idempotency claims, grant consumption, transaction ownership, terminal outcome
publication, and ledger sequencing are synchronized across threads.

**INV-CONC-02 — No lock delegated to tools.** Internal state locks are not held
while arbitrary executor, verifier, or compensator callbacks run.

**INV-CONC-03 — Runtime-instance boundary.** Runtime-bound identifiers and
grants cannot silently migrate to a different in-memory runtime instance.

## Mandatory fail-closed matrix

| Condition | Executor allowed? | Required result |
| --- | --- | --- |
| Unknown tool/version | No | Denied and audited |
| Invalid input | No | Validation failure and audited |
| Policy error/invalid result | No | Denied and audited |
| Effective high risk without exact grant | No | Approval pending/denied |
| Expired or replayed grant | No | Denied and audited |
| Idempotency fingerprint conflict | No | Conflict and audited |
| Duplicate already complete | No new call | Replay recorded outcome |
| Invalid transaction shape | No | Reject transaction |
| Ledger failure before commit release | No | Fail closed |
| Executor error with uncertain effect | No retry | Indeterminate |
| Output/verifier failure after reversible effect | No success | Compensate, then report truthfully |
| Failure involving irreversible effect | No retry | Usually indeterminate; reconcile externally |

## Security-sensitive design notes

### Approval time and clocks

Expiry uses timezone-aware UTC for records and a monotonic clock for elapsed
validity where the process permits it. Wall-clock changes must not extend a
grant silently. Restart behavior is outside scope because grants do not survive
restart.

### Error handling

Errors exposed to callers should use stable codes and safe summaries. Raw
callback exceptions may contain secrets and should not be copied wholesale into
audit events. Debug exception chaining may be available to trusted host code but
must not change authorization behavior.

### Callback reentrancy

Callbacks are trusted but may accidentally call the same runtime. The runtime
must avoid deadlock and must not allow reentrancy to mutate a committing
transaction. A conservative implementation may reject reentrant mutation with
a structured state error.

### Resource exhaustion

An in-memory ledger and idempotency store grow for the process lifetime. Version
0.1 should document this limitation and may expose read-only size metrics, but
must not silently evict safety records. Bounded retention requires a persistence
and lifecycle design beyond 0.1.

## Verification obligations

Each invariant requires at least one direct test; race-sensitive invariants need
deterministic concurrency tests. Tests must include malicious or malformed
requests, exception-throwing fake callbacks, verifier disagreement,
compensation failure, grant replay, argument mutation after approval,
same-key races, double commit, immutable ledger reads, and secret redaction.

All tests use fake/in-memory tools and credentials. Required project checks are
`pytest`, `ruff check .`, `ruff format --check .`, and `mypy src`.

## Security non-goals for version 0.1

Version 0.1 does not authenticate users, isolate Python code, protect memory
from the host, persist state, sign ledger events, encrypt data, rotate keys,
provide network security, meet a compliance standard, or guarantee atomicity in
an external system. These are not implied by the words “approval,” “ledger,” or
“transaction.”
