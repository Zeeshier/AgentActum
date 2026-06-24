# AgentActum Development Roadmap

## Purpose

This roadmap sequences the smallest useful version 0.1 of AgentActum. It is not
authorization to implement later phases or any hosted product. Each milestone
must preserve the product specification and security invariants.

## Version 0.1 release definition

Version 0.1 is complete when a Python 3.12+ application can register synchronous
fake or application-provided tools and route action requests through an
in-process runtime that enforces contracts, policy, approval, idempotency,
effect-free staging, commit gating, verification, compensation, and append-only
audit recording.

It intentionally does not survive restart and does not integrate with real
external services or agent frameworks.

## Milestone 0 — Project foundation

Deliverables:

- `pyproject.toml` with Python 3.12+, src layout, Pydantic runtime dependency,
  and development configuration for pytest, Ruff, and mypy;
- package skeleton with documented public API policy;
- test layout and CI for all required checks;
- a short dependency rationale. Pydantic is justified because repository rules
  require it for validated external data; no other production dependency is
  expected initially.

Exit criteria:

- empty package imports without an LLM or framework SDK;
- `pytest`, `ruff check .`, `ruff format --check .`, and `mypy src` pass;
- supported Python version and Apache-2.0 license metadata are correct.

## Milestone 1 — Domain models and contracts

Deliverables:

- frozen/immutable action, intent, outcome, risk, and effect value models;
- versioned `ToolContract` and deny-by-default registry;
- input/output validation and canonical-intent fingerprinting;
- structured error codes;
- unit tests for unknown tools, schema failures, duplicate registration,
  canonicalization, secret-field handling, and contract immutability.

Exit criteria:

- invariants `INV-CON-*` and `INV-INT-*` are covered directly;
- malformed input cannot reach a fake executor;
- equal semantic intent produces the same fingerprint and relevant changes
  produce a different fingerprint.

## Milestone 2 — Policy and audit spine

Deliverables:

- synchronous policy protocol and validated decision model;
- deterministic policy composition and risk-floor enforcement;
- thread-safe in-memory append-only ledger with immutable reads;
- redacted audit event taxonomy for all transitions available so far;
- failure injection for ledger and policy errors.

Exit criteria:

- policy exceptions and malformed decisions fail closed;
- deny/approval/allow precedence and mandatory high-risk approval are tested;
- ledger ordering, immutability, failure behavior, and redaction satisfy
  `INV-AUD-*`.

## Milestone 3 — Approval and idempotency

Deliverables:

- pending approval, rejection, expiry, grant, and atomic consumption lifecycle;
- trusted-host boundary for approver identity clearly documented;
- thread-safe in-memory idempotency store with fingerprint conflict detection,
  in-progress observation, and terminal replay;
- deterministic race tests.

Exit criteria:

- altered intent, expired grants, and replayed grants cannot authorize staging;
- same-key concurrent callers cannot create separately executable actions;
- failures and indeterminate records remain claimed;
- `INV-APP-*`, `INV-IDEM-*`, and relevant `INV-CONC-*` tests pass.

## Milestone 4 — Transactions and execution

Deliverables:

- explicit transaction state machine and immutable invocation plans;
- effect-free staging and whole-transaction shape validation;
- single commit ownership under concurrent calls;
- executor invocation, output validation, and postcondition verification;
- structured failed versus indeterminate outcomes;
- single-action convenience path built on the same transaction semantics.

Exit criteria:

- no fake effect occurs during staging;
- invalid shapes cause no effect;
- irreversible actions are limited to one and execute last;
- double or concurrent commit cannot duplicate an effect;
- `INV-TXN-*` and applicable `INV-EXE-*` tests pass.

## Milestone 5 — Compensation and end-to-end hardening

Deliverables:

- reverse-order compensation coordinator;
- compensation failure isolation and complete audit history;
- end-to-end tests covering every acceptance criterion;
- callback reentrancy, race, audit-failure, malformed-output, and secret-leak
  tests;
- API documentation and minimal examples using fake/in-memory tools only;
- explicit limitations and process-lifetime memory-growth warning.

Exit criteria:

- every invariant in `docs/security-invariants.md` maps to passing tests;
- all acceptance criteria in `docs/product-spec.md` pass;
- required formatting, linting, typing, and complete test suite pass;
- final diff and public API are reviewed for accidental framework coupling,
  permissive fallbacks, misleading atomicity claims, and undocumented
  dependencies.

## Cross-cutting development rules

For each behavior change:

1. Inspect the existing implementation and tests.
2. State the design and affected files.
3. Implement the smallest complete change.
4. Add positive, negative, failure-injection, and concurrency tests as relevant.
5. Run targeted tests during development.
6. Run `pytest`, `ruff check .`, `ruff format --check .`, and `mypy src` before
   declaring the task complete.
7. Review the final diff against the product spec and invariant identifiers.

Public and internal interfaces are typed. Public APIs have docstrings. Async is
not added until it provides concrete value and has defined cancellation
semantics. New production dependencies require a written rationale.

## Version 0.1 acceptance checklist

- [ ] Known, valid read-only action succeeds with validated output and audit.
- [ ] Unknown tools and invalid inputs fail without executor invocation.
- [ ] Policy denial and policy failure fail closed.
- [ ] High-risk actions require an exact, current, single-use approval grant.
- [ ] Intent mutation invalidates approval.
- [ ] Same-key duplicates replay; changed intent conflicts.
- [ ] Concurrent same-key requests cause at most one invocation.
- [ ] Staging is externally effect-free.
- [ ] Unsafe transaction shapes fail before effects.
- [ ] Irreversible execution is commit-gated and ordered last.
- [ ] Reversible effects compensate in reverse order after later failure.
- [ ] Compensation and verification failures preserve truthful uncertainty.
- [ ] Ledger is append-only through its API, ordered, immutable on read, and
      redacted.
- [ ] All required project checks pass on supported Python.
- [ ] Core imports without any LLM or agent-framework package.

## Deferred roadmap candidates

These are candidates, not commitments, and are outside version 0.1:

### Persistence and recovery

Define store protocols, durable state transitions, crash reconciliation,
schema migration, and cross-process concurrency. Persistence must be designed
as a protocol, not achieved by serializing arbitrary in-memory objects.

### Async and cancellation

Add async interfaces only after specifying cancellation during external calls,
task ownership, async locking, and compatibility with synchronous contracts.

### Framework adapters

Build thin adapters for selected orchestration frameworks without moving their
types into core. Each adapter translates framework calls into the same core
action request and outcome semantics.

### External integrations

Add integrations one at a time with fake contract tests, explicit idempotency
and reconciliation behavior, credential boundaries, and honest reversibility
classification. No real integration belongs in 0.1.

### Stronger audit and policy infrastructure

Potential work includes durable/exportable ledgers, cryptographic integrity,
remote policy evaluation, approval services, and retention. Each adds a new
trust boundary and requires a separate threat model.

## Explicit non-goals for this roadmap

- Dashboard, hosted service, SaaS platform, or microservice deployment.
- Production cloud infrastructure or operational control plane.
- Real payment, email, database, cloud, or browser integrations in 0.1.
- CrewAI, AutoGen, LangGraph, or other adapters in 0.1.
- Agent orchestration, model hosting, prompting, or automatic skill evolution.
- Distributed ACID, universal exactly-once effects, or guaranteed rollback.
- Silent policy weakening, automatic retry of uncertainty, or safety-record
  eviction to improve convenience.

## Release risks to review

- Public names may accidentally promise stronger durability than delivered.
- Canonicalization errors can break approval and idempotency binding.
- Callback exceptions can conceal partial external effects.
- Locking mistakes can duplicate effects or deadlock reentrant callbacks.
- Audit payloads can leak secrets even when execution behavior is correct.
- In-memory records grow without eviction and disappear on restart.
- Users may mistake successful compensation for erasure of the original effect.

The 0.1 release notes must repeat these limitations prominently.
