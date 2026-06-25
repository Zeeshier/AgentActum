"""Shared model configuration and constrained domain scalar types."""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue, StringConstraints

type DomainName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    ),
]
type ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
type LongText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
]
type IntentFingerprint = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
type JsonObject = dict[str, JsonValue]
type Timestamp = AwareDatetime


class DomainModel(BaseModel):
    """Strict, immutable base for externally visible domain values."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )
