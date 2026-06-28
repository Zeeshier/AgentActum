# AgentActum

<p align="center">
  <img src="docs/assets/agentactum-icon.png" alt="AgentActum icon" width="128">
</p>

AgentActum is a framework-independent transactional safety runtime for
AI-agent tool actions. It sits between an agent or application and trusted
Python tool functions, then applies contracts, deterministic policies,
idempotency, approval checks, validation, audit recording, compensation, and
effect staging/outbox primitives.

Version 0.1 is intentionally small: it is an in-process Python library, not a
hosted service, dashboard, worker system, durable workflow engine, or universal
rollback layer.

## What is included in 0.1

- Core domain enums and Pydantic models for contracts, intents, decisions,
  approvals, transactions, ledger events, execution results, and compensation
  results.
- In-memory tool registry with duplicate-registration rejection and typed
  unknown-tool errors.
- Deterministic policy engine with allow/deny rules, required permissions,
  risk-based approval, numeric approval thresholds, unknown-tool denial, and
  fail-closed behavior.
- In-memory idempotency backend and deterministic key generation.
- Single-action execution pipeline with contract validation, policy checks,
  approval checks, idempotency reservation, preconditions, postconditions, and
  ledger events.
- Explicit transaction state machine.
- Reverse-order compensation coordinator.
- In-memory effect outbox for staging release-after-commit operations.
- `AgentActum` facade for protecting ordinary Python callables.
- Optional LangGraph adapter available through the `langgraph` extra.

## Non-goals

AgentActum 0.1 does not provide:

- a dashboard, hosted service, SaaS control plane, network API, or microservice;
- persistence, crash recovery, distributed locking, queues, workers, retries,
  scheduling, or cross-process coordination;
- real payment, email, database, browser, cloud, or infrastructure
  integrations;
- authentication, approval UI, role administration, or identity proofing;
- an LLM policy engine, policy DSL, agent planner, model host, prompt manager,
  or orchestration runtime;
- guaranteed rollback, distributed ACID transactions, or exactly-once delivery
  to external systems.

In-memory stores are process-local. They do not survive restart and must not be
described as durable or tamper-proof.

## Requirements

- Python 3.12 or newer
- `pip`

## Installation

Install from a local checkout:

```shell
python -m pip install .
```

For editable development, including all test and quality tools:

```shell
python -m pip install --editable ".[dev]"
```

For the optional LangGraph adapter:

```shell
python -m pip install "agentactum[langgraph]"
```

When installing from a local checkout with development tools and LangGraph:

```shell
python -m pip install --editable ".[dev,langgraph]"
```

## Minimal example

```python
from uuid import uuid4

from agentactum import AgentActum, EffectType, RiskLevel, ToolContract, ToolSchema

refund_contract = ToolContract(
    contract_id=uuid4(),
    name="refund_payment",
    version="1.0.0",
    description="Refund a payment in a fake local system.",
    effect_type=EffectType.IDEMPOTENT,
    risk_level=RiskLevel.LOW,
    input_schema=ToolSchema(
        name="refund_input",
        document={
            "type": "object",
            "properties": {
                "payment_id": {"type": "string"},
                "amount": {"type": "number", "minimum": 1},
            },
            "required": ["payment_id", "amount"],
        },
    ),
    output_schema=ToolSchema(
        name="refund_output",
        document={
            "type": "object",
            "properties": {
                "refund_id": {"type": "string"},
                "amount": {"type": "number", "minimum": 1},
            },
            "required": ["refund_id", "amount"],
        },
    ),
)

actum = AgentActum()


@actum.protect(contract=refund_contract)
def refund_payment(payment_id: str, amount: float) -> dict[str, str | float]:
    return {"refund_id": f"REF-{payment_id}", "amount": amount}


result = refund_payment("PAY-100", 250.0)
assert result.succeeded
assert result.output == {"refund_id": "REF-PAY-100", "amount": 250.0}
```

Protected functions return an `ExecutionResult`. If validation, policy,
approval, idempotency, execution, or postcondition checks fail, the result is a
structured failure instead of a silent tool invocation.

## LangGraph adapter

The LangGraph adapter is optional and imported separately so the core package
does not depend on LangGraph:

```python
from agentactum import AgentActum
from agentactum.langgraph import LangGraphAdapter

actum = AgentActum()
adapter = LangGraphAdapter(actum)


@adapter.protect_tool(contract=refund_contract, return_mode="output")
def refund_payment(payment_id: str, amount: float) -> dict[str, str | float]:
    return {"refund_id": f"REF-{payment_id}", "amount": amount}

# Only this method lazily imports langgraph.prebuilt.ToolNode.
tool_node = adapter.tool_node([refund_payment])
```

Install it with:

```shell
python -m pip install "agentactum[langgraph]"
```

## Development

Run the complete test suite:

```shell
pytest
```

Run linting and formatting checks:

```shell
ruff check .
ruff format --check .
```

Run static type checking:

```shell
mypy src
```

Run all configured pre-commit checks:

```shell
pre-commit run --all-files
```

Install the Git hook locally with:

```shell
pre-commit install
```

## Release checks

Before cutting a release, run:

```shell
pytest
ruff check .
ruff format --check .
mypy src
pre-commit run --all-files
python -m pip wheel . --no-deps --wheel-dir dist
```

The wheel command should be run in a clean release workspace or with `dist/`
removed afterward; build artifacts are intentionally ignored by Git.

## Documentation

- [Product specification](docs/product-spec.md)
- [Architecture](docs/architecture.md)
- [Security invariants](docs/security-invariants.md)
- [Development roadmap](docs/development-roadmap.md)
- [Release checklist](docs/release-checklist.md)
- [Changelog](CHANGELOG.md)

## License

AgentActum is licensed under the [Apache License 2.0](LICENSE).
