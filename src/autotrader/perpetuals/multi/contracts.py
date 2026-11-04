"""Contract-aware linear USDT margin math. No BTC maintenance assumptions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from autotrader.perpetuals.multi.policy import D, FEE, digest


@dataclass(frozen=True)
class Tier:
    limit: Decimal
    maintenance: Decimal
    deduction: Decimal
    max_leverage: Decimal


@dataclass(frozen=True)
class Contract:
    symbol: str
    base: str
    step: Decimal
    minimum: Decimal
    min_notional: Decimal
    max_market_qty: Decimal
    price_tick: Decimal
    min_leverage: Decimal
    max_leverage: Decimal
    leverage_step: Decimal
    funding_minutes: int
    tiers: tuple[Tier, ...]
    observed_at: int

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def restore(cls, data: dict[str, Any]) -> Contract:
        values = dict(data)
        for name in ('step', 'minimum', 'min_notional', 'max_market_qty', 'price_tick',
                     'min_leverage', 'max_leverage', 'leverage_step'):
            values[name] = D(str(values[name]))
        values['tiers'] = tuple(Tier(*(D(str(row[k])) for k in
                                      ('limit', 'maintenance', 'deduction', 'max_leverage'))) for row in values['tiers'])
        return cls(**values)

    @property
    def identity(self) -> str:
        data = self.payload(); data.pop('observed_at')
        return digest(data)

    def tier(self, notional: Decimal) -> Tier:
        if not notional.is_finite() or notional < 0:
            raise ValueError('invalid_risk_notional')
        for row in self.tiers:
            if notional <= row.limit:
                return row
        raise ValueError('risk_tier_capacity_exceeded')

    def validate_size(self, quantity: Decimal, price: Decimal, leverage: int) -> None:
        if (quantity <= 0 or price <= 0 or quantity % self.step != 0 or quantity < self.minimum
                or quantity > self.max_market_qty or quantity * price < self.min_notional):
            raise ValueError('contract_quantity_or_notional_rule')
        tier = self.tier(quantity * price)
        if (not self.min_leverage <= leverage <= min(self.max_leverage, tier.max_leverage)
                or (D(leverage) - self.min_leverage) % self.leverage_step):
            raise ValueError('contract_leverage_not_permitted')


def maintenance(contract: Contract, quantity: Decimal, mark: Decimal) -> Decimal:
    tier = contract.tier(quantity * mark)
    return max(D(0), quantity * mark * tier.maintenance - tier.deduction) + quantity * mark * FEE


def liquidation(contract: Contract, p: dict[str, Any]) -> Decimal:
    side, qty = int(p['side']), D(p['quantity'])
    collateral = D(p['margin']) + D(p.get('funding', '0'))
    lower = D(0)
    for tier in contract.tiers:
        root = (side * qty * D(p['entry']) - collateral - tier.deduction) / (qty * (side - tier.maintenance - FEE))
        if root <= 0 and side == 1:
            return D(0)
        if lower <= qty * root <= tier.limit:
            return root
        lower = tier.limit
    raise ValueError('liquidation_outside_published_risk_tiers')


def parse_tiers(rows: list[dict[str, Any]], symbol: str) -> tuple[Tier, ...]:
    result = []
    for row in rows:
        if row['symbol'] != symbol:
            raise ValueError('risk_contract_identity_mismatch')
        im, mm, maximum = (D(str(row[k])) for k in ('initialMargin', 'maintenanceMargin', 'maxLeverage'))
        # Published responses have used percent and fractional representations.
        # Resolve units using initial-margin/leverage identity, never a coin guess.
        units = [scale for scale in (D(1), D(100)) if abs(im / scale * maximum - 1) < D('.02')]
        if len(units) != 1:
            raise ValueError('unverifiable_risk_margin_units')
        rate = mm / units[0]
        deduction = D(str(row.get('mmDeduction') or '0'))
        limit = D(str(row['riskLimitValue']))
        if (not all(v.is_finite() for v in (rate, limit, deduction, maximum))
                or not 0 < rate < im / units[0] <= 1 or limit <= 0 or deduction < 0):
            raise ValueError('invalid_contract_risk_tier')
        result.append(Tier(limit, rate, deduction, maximum))
    result.sort(key=lambda tier: tier.limit)
    if not result or any(a.limit >= b.limit or a.maintenance > b.maintenance for a,b in zip(result, result[1:])):
        raise ValueError('incomplete_or_unordered_risk_tiers')
    return tuple(result)
