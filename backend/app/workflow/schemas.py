import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.types import IDR
from app.workflow.conditions import describe


class DocTypeOut(BaseModel):
    code: str
    label: str
    module: str


class InboxItem(BaseModel):
    request_id: uuid.UUID
    doc_type: str
    doc_type_label: str
    doc_number: str
    title: str
    amount: IDR | None
    currency: str
    requester_name: str
    submitted_at: datetime
    step_label: str
    due_at: datetime | None
    overdue: bool
    escalated: bool


class InboxPage(BaseModel):
    items: list[InboxItem]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]


class StepOut(BaseModel):
    seq: int
    approver_role: str
    approver_role_name: str
    label: str
    status: str
    acted_by_name: str | None
    on_behalf_of_name: str | None
    acted_at: datetime | None
    comment: str | None
    due_at: datetime | None


class ChangeLine(BaseModel):
    label: str
    before: str | None
    after: str


class RequestDetail(BaseModel):
    id: uuid.UUID
    doc_type: str
    doc_type_label: str
    doc_id: str
    doc_number: str
    title: str
    amount: IDR | None
    currency: str
    status: str
    requester_name: str
    submitted_at: datetime
    decided_at: datetime | None
    rule_name: str
    steps: list[StepOut]
    can_act: bool
    can_cancel: bool
    # For DOA rule changes: what the approver is agreeing to.
    changes: list[ChangeLine] = []
    change_reason: str | None = None


class DecisionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)


class RejectIn(BaseModel):
    comment: str = Field(max_length=1000)


class BulkIn(BaseModel):
    doc_type: str
    request_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    comment: str | None = Field(default=None, max_length=1000)


class BulkItemOut(BaseModel):
    request_id: uuid.UUID
    ok: bool
    code: str | None
    message: str | None


class DelegationIn(BaseModel):
    delegate_id: uuid.UUID
    role_code: str | None = None
    start_date: date
    end_date: date
    reason: str = Field(min_length=3, max_length=300)


class DelegationOut(BaseModel):
    id: uuid.UUID
    delegator_name: str
    delegate_name: str
    role_code: str | None
    start_date: date
    end_date: date
    reason: str
    active: bool
    can_revoke: bool


class RuleStepIn(BaseModel):
    seq: int = Field(ge=1, le=20)
    approver_role: str
    label: str = Field(default="", max_length=120)
    approver_scope: str = Field(default="all", pattern="^(all|project)$")


class RuleIn(BaseModel):
    doc_type: str
    name: str = Field(min_length=3, max_length=200)
    priority: int = Field(default=100, ge=0, le=10000)
    condition: dict[str, Any] = Field(default_factory=dict)
    escalation_hours: int = Field(default=48, ge=1, le=720)
    escalate_to_role: str | None = None
    is_active: bool = True
    note: str = Field(default="", max_length=500)
    steps: list[RuleStepIn] = Field(min_length=1, max_length=10)


class RuleChangeIn(BaseModel):
    rule_id: uuid.UUID | None = None
    rule: RuleIn
    reason: str = Field(min_length=5, max_length=500)


class RuleOut(BaseModel):
    id: uuid.UUID
    doc_type: str
    doc_type_label: str
    name: str
    priority: int
    condition: dict[str, Any]
    condition_text: str = ""
    escalation_hours: int
    escalate_to_role: str | None
    is_active: bool
    note: str
    steps: list[RuleStepIn]
    pending_change: bool

    @model_validator(mode="after")
    def _text(self) -> "RuleOut":
        self.condition_text = describe(self.condition)
        return self


class RuleChangeOut(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID | None
    doc_type: str
    name: str
    reason: str
    status: str
    request_id: uuid.UUID | None
    created_at: datetime

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return v
