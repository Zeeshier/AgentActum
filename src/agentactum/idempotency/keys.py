"""Deterministic idempotency key creation."""

import hashlib
import json
from collections.abc import Iterable

from pydantic import JsonValue

from agentactum._model import JsonObject

KEY_PREFIX = "agentactum:v1"


class IdempotencyKeyError(ValueError):
    """Base class for idempotency key creation failures."""


class MissingIdempotencyFieldError(IdempotencyKeyError):
    """Raised when key material names an argument field that is absent."""

    def __init__(self, field: str) -> None:
        """Create a missing-field error."""
        self.field = field
        super().__init__(f"idempotency field is missing from arguments: {field}")


def create_key(
    *,
    tool_name: str,
    arguments: JsonObject,
    fields: Iterable[str],
) -> str:
    """Create a deterministic key from explicit action identity fields.

    Only fields named in `fields` participate in the key. This makes the
    idempotency boundary deliberate: tracing metadata or non-semantic arguments
    cannot accidentally change the key, while security-relevant values must be
    listed explicitly.
    """
    selected_fields = tuple(fields)
    _validate_key_material(tool_name=tool_name, fields=selected_fields)

    selected_arguments: dict[str, JsonValue] = {}
    for field in selected_fields:
        if field not in arguments:
            raise MissingIdempotencyFieldError(field)
        selected_arguments[field] = arguments[field]

    material = {
        "fields": selected_fields,
        "tool_name": tool_name,
        "values": selected_arguments,
        "version": 1,
    }
    canonical = json.dumps(
        material,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{KEY_PREFIX}:{tool_name}:{digest}"


def _validate_key_material(*, tool_name: str, fields: tuple[str, ...]) -> None:
    if not tool_name.strip():
        raise IdempotencyKeyError("tool_name must not be blank")
    if not fields:
        raise IdempotencyKeyError("fields must not be empty")
    if len(fields) != len(set(fields)):
        raise IdempotencyKeyError("fields must not contain duplicates")
    if any(not field.strip() for field in fields):
        raise IdempotencyKeyError("fields must not contain blank names")
