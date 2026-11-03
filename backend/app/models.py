"""Import every model module so Base.metadata is complete (used by Alembic and tests)."""

from app.auth.models import RecoveryCode, RefreshToken, Role, RolePermission, User, UserRole
from app.core.models import Base
from app.dms.models import Attachment
from app.master.models import (
    Account,
    Asset,
    Client,
    CostCenter,
    CostElement,
    Currency,
    Department,
    Employee,
    FiscalPeriod,
    FxRate,
    Item,
    PriceItem,
    Vendor,
    Warehouse,
)
from app.notifications.models import Notification
from app.services.audit import AuditLog
from app.services.numbering import DocCounter
from app.setup.models import SystemSetting
from app.workflow.models import (
    ApprovalRequest,
    ApprovalStep,
    Delegation,
    DoaRule,
    DoaRuleChange,
    DoaRuleStep,
)

__all__ = [
    "Account",
    "ApprovalRequest",
    "ApprovalStep",
    "Asset",
    "Attachment",
    "AuditLog",
    "Base",
    "Client",
    "CostCenter",
    "CostElement",
    "Currency",
    "Delegation",
    "Department",
    "DoaRule",
    "DoaRuleChange",
    "DoaRuleStep",
    "DocCounter",
    "Employee",
    "FiscalPeriod",
    "FxRate",
    "Item",
    "Notification",
    "PriceItem",
    "RecoveryCode",
    "RefreshToken",
    "Role",
    "RolePermission",
    "SystemSetting",
    "User",
    "UserRole",
    "Vendor",
    "Warehouse",
]
