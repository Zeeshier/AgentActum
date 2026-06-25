"""Approval request domain contracts."""

from typing import Self
from uuid import UUID

from pydantic import model_validator

from agentactum._model import (
    DomainModel,
    IntentFingerprint,
    LongText,
    Timestamp,
)
from agentactum.enums import RiskLevel


class ApprovalRequest(DomainModel):
    """Pending approval bound to an exact intent and policy decision."""

    approval_request_id: UUID
    intent_id: UUID
    transaction_id: UUID
    policy_decision_id: UUID
    intent_fingerprint: IntentFingerprint
    risk_level: RiskLevel
    reason: LongText
    requested_at: Timestamp
    expires_at: Timestamp

    @model_validator(mode="after")
    def validate_expiry(self) -> Self:
        """Require an approval window with positive duration."""
        if self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be after requested_at")
        return self
