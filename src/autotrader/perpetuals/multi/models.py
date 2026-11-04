"""No shared tables, accounts or foreign keys with spot or the legacy BTC lab."""
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MultiState(Base):
    __tablename__ = 'paper_multi_state'
    __table_args__ = (CheckConstraint('id = 1'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    generation: Mapped[int]
    payload: Mapped[str | None] = mapped_column(Text)


class MultiEvent(Base):
    __tablename__ = 'paper_multi_events'
    __table_args__ = (UniqueConstraint('event_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    cohort: Mapped[str | None] = mapped_column(String(3), index=True)
    cash_delta: Mapped[Decimal] = mapped_column(Numeric(38,24), default=0)
    payload: Mapped[str] = mapped_column(Text)


class MultiSignal(Base):
    __tablename__ = 'paper_multi_signals'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cutoff: Mapped[int] = mapped_column(BigInteger, index=True)
    due_at: Mapped[int] = mapped_column(BigInteger, index=True)
    payload: Mapped[str] = mapped_column(Text)


class MultiScan(Base):
    __tablename__ = 'paper_multi_scan'
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
