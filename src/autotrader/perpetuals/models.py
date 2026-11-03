"""The simulator owns a separate schema revision and never touches spot tables."""
from sqlalchemy import CheckConstraint, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PaperPerpState(Base):
    __tablename__ = "paper_perp_state"
    __table_args__ = (CheckConstraint("id = 1", name="paper_perp_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    generation: Mapped[int]
    payload: Mapped[str | None] = mapped_column(Text)


class PaperPerpEvent(Base):
    __tablename__ = "paper_perp_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
