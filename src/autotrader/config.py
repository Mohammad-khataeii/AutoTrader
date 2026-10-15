from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIProvider(StrEnum):
    MOCK = "mock"
    OPENAI = "openai"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_name: str = "Revolut X AutoTrader"
    environment: str = "local"
    dashboard_username: str = "admin"
    dashboard_password: SecretStr = Field(default=SecretStr("change-me"))

    database_url: str = "sqlite+aiosqlite:///./autotrader.db"
    redis_url: str = "redis://redis:6379/0"

    revolut_x_base_url: str = "https://revx.revolut.com/api"
    revolut_x_region: str = "EEA"
    market_data_timeout_seconds: Decimal = Decimal("8")
    market_data_max_staleness_seconds: int = 90
    scanner_max_pairs: int = 8
    worker_scan_interval_seconds: int = 60
    worker_max_entries_per_cycle: int = 3
    market_data_replay_file: str | None = None

    paper_trading_enabled: bool = True
    live_trading_enabled: bool = False
    initial_cash_eur: Decimal = Decimal("500")
    max_allocated_capital_eur: Decimal = Decimal("500")
    max_total_open_exposure_eur: Decimal = Decimal("350")
    min_uncommitted_reserve_eur: Decimal = Decimal("150")
    max_position_size_eur: Decimal = Decimal("100")
    max_simultaneous_positions: int = 3
    max_planned_loss_per_trade_eur: Decimal = Decimal("5")
    daily_loss_threshold_eur: Decimal = Decimal("15")
    weekly_loss_threshold_eur: Decimal = Decimal("35")
    max_new_entries_per_day: int = 6
    default_fee_bps: Decimal = Decimal("10")
    default_slippage_bps: Decimal = Decimal("8")

    ai_provider: AIProvider = AIProvider.MOCK
    ai_model: str = "configured-model-id"
    openai_api_key: SecretStr | None = None
    ai_monthly_budget_usd: Decimal = Decimal("10")
    ai_timeout_seconds: Decimal = Decimal("12")

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    @field_validator("live_trading_enabled")
    @classmethod
    def reject_live_trading(cls, value: bool) -> bool:
        if value:
            raise ValueError("Live trading is intentionally disabled for V1.0.")
        return value

    @model_validator(mode="after")
    def reject_insecure_production_credentials(self) -> Settings:
        weak_values = {"", "change-me", "REPLACE_WITH_STRONG_PASSWORD"}
        if self.environment.lower() not in {"local", "test"} and self.dashboard_password.get_secret_value() in weak_values:
            raise ValueError("A strong DASHBOARD_PASSWORD is required outside local/test environments.")
        if self.market_data_replay_file and self.environment != "test":
            raise ValueError("File replay is restricted to ENVIRONMENT=test.")
        return self

    @field_validator(
        "initial_cash_eur",
        "max_allocated_capital_eur",
        "max_total_open_exposure_eur",
        "min_uncommitted_reserve_eur",
        "max_position_size_eur",
        "max_planned_loss_per_trade_eur",
        "daily_loss_threshold_eur",
        "weekly_loss_threshold_eur",
        "ai_monthly_budget_usd",
    )
    @classmethod
    def money_must_be_non_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("Money values must be non-negative.")
        return value


def get_settings() -> Settings:
    return Settings()
