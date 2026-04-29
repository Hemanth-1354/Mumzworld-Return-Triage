from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class ReturnRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000, description="Customer return reason")
    order_id: Optional[str] = Field(None, description="Optional order ID for tracking")


class TriageResult(BaseModel):
    resolution: Literal["refund", "exchange", "store_credit", "escalate"]
    category: Literal[
        "defective", "wrong_item", "changed_mind",
        "damaged_shipping", "late_delivery", "other"
    ]
    reasoning: str = Field(..., description="1-2 sentence explanation of the triage decision")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence [0, 1]")
    reply_en: str = Field(..., description="Suggested customer-facing reply in English")
    reply_ar: str = Field(..., description="Suggested customer-facing reply in Arabic")
    language_detected: Literal["en", "ar", "other"]
    order_id: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def round_confidence(cls, v: float) -> float:
        return round(float(v), 2)

    @field_validator("reply_ar")
    @classmethod
    def arabic_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Arabic reply (reply_ar) cannot be empty")
        return v.strip()

    @field_validator("reply_en")
    @classmethod
    def english_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("English reply (reply_en) cannot be empty")
        return v.strip()

    @field_validator("reasoning")
    @classmethod
    def reasoning_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Reasoning cannot be empty")
        return v.strip()
