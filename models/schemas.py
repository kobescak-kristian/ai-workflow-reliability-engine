from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum
from datetime import datetime, timezone


class Category(str, Enum):
    HIGH_VALUE = "high_value"
    LOW_VALUE  = "low_value"
    UNKNOWN    = "unknown"


class FinalDecision(str, Enum):
    SEND_TO_SALES = "send_to_sales"
    ARCHIVE       = "archive"
    MANUAL_REVIEW = "manual_review"


class FallbackAction(str, Enum):
    NONE                   = "none"
    RETRY                  = "retry"
    DEFAULT_ASSIGNED       = "default_assigned"
    MANUAL_REVIEW_FLAGGED  = "manual_review_flagged"


class InputRecord(BaseModel):
    id: str
    raw_text: str
    metadata: Optional[dict] = None
    received_at: str = ""

    def model_post_init(self, __context):
        if not self.received_at:
            self.received_at = datetime.now(timezone.utc).isoformat()


class AIOutput(BaseModel):
    category: str
    confidence: float
    reason: str


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []


class PipelineResult(BaseModel):
    input: InputRecord
    ai_output: Optional[AIOutput]
    validation: ValidationResult
    fallback_action: FallbackAction
    final_decision: FinalDecision
    notes: Optional[str] = None
    processing_ms: Optional[float] = None
