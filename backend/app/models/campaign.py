from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, Timestamps, UUIDPk, str_enum
from app.models.enums import CampaignStatus


class Campaign(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    target_audience: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[CampaignStatus] = mapped_column(
        str_enum(CampaignStatus), default=CampaignStatus.ACTIVE, nullable=False
    )
    # NULL means "use the global default from settings".
    max_followups: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followup_delay_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
