"""Master data models. Departments are created in 01.1 because data scope needs them."""

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class Department(EntityMixin, Base):
    __tablename__ = "departments"

    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
