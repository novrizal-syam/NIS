from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.contract.models import Contract
from app.crm.models import QuotationLine
from app.project.models import Project, ProjectBudgetLine
from app.services import audit, numbering
from app.services.audit import AuditAction
from app.setup import service as settings_store

CONTINGENCY = "CONTINGENCY"
CONTINGENCY_SETTING = "project.contingency_pct"
DEFAULT_CONTINGENCY = 5


async def contingency_pct(session: AsyncSession) -> Decimal:
    value = await settings_store.get(session, CONTINGENCY_SETTING, DEFAULT_CONTINGENCY)
    return Decimal(str(value))


def budget_from_lines(
    lines: list[QuotationLine], pct: Decimal
) -> tuple[dict[str, Decimal], Decimal]:
    """Budget per cost element = quoted cost (the discount lowers revenue, not cost);
    Contingency = pct % of the total cost, rounded to whole rupiah."""
    per: dict[str, Decimal] = defaultdict(Decimal)
    for x in lines:
        per[x.cost_element_code or "SUBCONTRACT"] += x.line_cost
    cost = sum(per.values(), Decimal(0))
    contingency = (cost * pct / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return dict(sorted(per.items())), contingency


async def create_draft(
    session: AsyncSession,
    actor: Principal,
    contract: Contract,
    lines: list[QuotationLine],
) -> Project:
    pct = await contingency_pct(session)
    per, contingency = budget_from_lines(lines, pct)
    project = Project(
        number=await numbering.next(session, "PRJ"),
        name=contract.title,
        contract_id=contract.id,
        client_code=contract.client_code,
        company_name=contract.company_name,
        status="draft",
        revenue=contract.value,
        budget_total=sum(per.values(), Decimal(0)) + contingency,
        contingency_pct=pct,
        start_date=contract.start_date,
        end_date=contract.end_date,
        owner_id=contract.owner_id,
        created_by=actor.id,
        is_demo=contract.is_demo,
    )
    session.add(project)
    await session.flush()
    for code, amount in per.items():
        session.add(
            ProjectBudgetLine(
                project_id=project.id,
                version=0,
                cost_element_code=code,
                amount=amount,
                source="quotation",
            )
        )
    session.add(
        ProjectBudgetLine(
            project_id=project.id,
            version=0,
            cost_element_code=CONTINGENCY,
            amount=contingency,
            source="contingency",
        )
    )
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="project",
        entity_id=project.id,
        actor_id=actor.id,
        after={
            "number": project.number,
            "contract": contract.number,
            "revenue": project.revenue,
            "budget": {**per, CONTINGENCY: contingency},
        },
    )
    return project


async def budget_of(session: AsyncSession, project_id: Any) -> list[ProjectBudgetLine]:
    rows = await session.execute(
        select(ProjectBudgetLine)
        .where(ProjectBudgetLine.project_id == project_id, ProjectBudgetLine.version == 0)
        .order_by(ProjectBudgetLine.cost_element_code)
    )
    return list(rows.scalars())
