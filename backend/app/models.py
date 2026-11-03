"""Import every model module so Base.metadata is complete (used by Alembic and tests)."""

from app.auth.models import (
    RecoveryCode,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserInvite,
    UserRole,
)
from app.auth.password_reset import PasswordReset, PasswordResetRequest
from app.core.models import Base
from app.crm.models import BidDecision, Lead, Opportunity
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
from app.services.email_log import EmailLog
from app.services.numbering import DocCounter
from app.setup.models import SystemSetting
from app.sod.models import SodException, SodRule
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
    "BidDecision",
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
    "EmailLog",
    "Employee",
    "FiscalPeriod",
    "FxRate",
    "Item",
    "Lead",
    "Notification",
    "Opportunity",
    "PasswordReset",
    "PasswordResetRequest",
    "PriceItem",
    "RecoveryCode",
    "RefreshToken",
    "Role",
    "RolePermission",
    "SodException",
    "SodRule",
    "SystemSetting",
    "User",
    "UserInvite",
    "UserRole",
    "Vendor",
    "Warehouse",
]
