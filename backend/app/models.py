"""Import every model module so Base.metadata is complete (used by Alembic and tests)."""

from app.auth.models import RefreshToken, Role, RolePermission, User, UserRole
from app.core.models import Base
from app.master.models import Department
from app.services.audit import AuditLog
from app.services.numbering import DocCounter
from app.workflow.models import (
    ApprovalRequest,
    ApprovalStep,
    Delegation,
    DoaRule,
    DoaRuleChange,
    DoaRuleStep,
)

__all__ = [
    "ApprovalRequest",
    "ApprovalStep",
    "AuditLog",
    "Base",
    "Delegation",
    "Department",
    "DoaRule",
    "DoaRuleChange",
    "DoaRuleStep",
    "DocCounter",
    "RefreshToken",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
]
