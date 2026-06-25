"""Immutable audit-ledger event contracts."""

from uuid import UUID

from pydantic import Field, PositiveInt

from agentactum._model import DomainModel, DomainName, JsonObject, ShortText, Timestamp


class LedgerEvent(DomainModel):
    """One ordered, immutable audit fact."""

    event_id: UUID
    correlation_id: UUID
    sequence_number: PositiveInt
    event_type: DomainName
    occurred_at: Timestamp
    transaction_id: UUID | None = None
    intent_id: UUID | None = None
    actor_id: ShortText | None = None
    details: JsonObject = Field(default_factory=dict)
