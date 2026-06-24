# AgentActum

AgentActum is a framework-independent transactional safety runtime for
AI-agent tool actions. It is intended to sit between an agent and external
tools and enforce contracts, policies, approvals, idempotency, transaction
boundaries, verification, compensation, and audit recording.

The project is currently an early scaffold. No domain runtime behavior is
implemented yet.

## Requirements

- Python 3.12 or newer
- `pip`

## Installation

Install the package from a local checkout:

```shell
python -m pip install .
```

For editable development, including all test and quality tools:

```shell
python -m pip install --editable ".[dev]"
```

Pydantic is the only production dependency. It is declared because AgentActum's
external data contracts will require validated models; those models are not
implemented in this scaffold. Test, coverage, lint, type-checking, and Git-hook
tools are isolated in the `dev` extra.

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

## Scope

AgentActum is an in-process Python library. It is not an agent orchestrator,
hosted service, dashboard, durable workflow engine, or external integration
suite. See the documents in [`docs/`](docs/) for the product specification,
architecture, security invariants, and development roadmap.

## License

AgentActum is licensed under the [Apache License 2.0](LICENSE).
