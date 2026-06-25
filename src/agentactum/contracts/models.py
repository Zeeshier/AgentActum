"""Declarative tool contracts and requested action intents."""

from uuid import UUID

from pydantic import Field, field_validator

from agentactum._model import (
    DomainModel,
    DomainName,
    JsonObject,
    LongText,
    ShortText,
    Timestamp,
)
from agentactum.enums import EffectType, RiskLevel


class ToolSchema(DomainModel):
    """Named JSON Schema document used at a tool boundary."""

    name: DomainName
    document: JsonObject

    @field_validator("document")
    @classmethod
    def require_explicit_schema(cls, value: JsonObject) -> JsonObject:
        """Reject an unconstrained empty schema document."""
        if not value:
            raise ValueError("schema document must not be empty")
        return value


class ToolContract(DomainModel):
    """Versioned, declarative description of one registered tool boundary."""

    contract_id: UUID
    name: DomainName
    version: ShortText
    description: LongText
    effect_type: EffectType
    risk_level: RiskLevel
    input_schema: ToolSchema
    output_schema: ToolSchema
    idempotency_key_required: bool = True


class ActionIntent(DomainModel):
    """Immutable request to invoke one exact tool-contract version."""

    intent_id: UUID
    contract_id: UUID
    tool_name: DomainName
    contract_version: ShortText
    requester_id: ShortText
    arguments: JsonObject
    created_at: Timestamp
    idempotency_key: ShortText | None = None
    context: JsonObject = Field(default_factory=dict)
