"""Versioned EUR7000 experimental authority. Never authorizes exchange mutations."""
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from autotrader.opportunity.engine import SUCCESSOR_REGISTRY, SuccessorParameters
from autotrader.research.data import canonical, digest
from autotrader.risk import RiskLimits
from autotrader.shadow.versions import execution_fingerprint

D = Decimal
ACCOUNT = "PERSONAL_PLAN_PAPER_7000"
REGISTRY_KEY = "personal_paper_v47"
INITIAL = D(7000)
VERSION = "4.8.0-paper.1"
LIMITS = RiskLimits(max_allocated_capital=INITIAL, max_total_open_exposure=D(4200),
    min_uncommitted_reserve=D(2800), max_position_size=D(700), max_simultaneous_positions=6,
    max_planned_loss_per_trade=D(35), daily_loss_threshold=D(140),
    weekly_loss_threshold=D(350), max_new_entries_per_day=24, planned_loss_cost_bps=D(40))
AGGREGATE_STOP_RISK = D(140)
CORRELATED_CAPITAL = D(2100)
STRATEGY_CAPITAL = D(2100)
MAX_DRAWDOWN = D('.10')
STRATEGIES = {s.strategy_id: {"strategy_version": s.version, "parameters": SuccessorParameters().payload()}
              for s in SUCCESSOR_REGISTRY}
from autotrader.personal_paper.selection import POLICY as BASELINE_POLICY
from autotrader.raoe import IDENTITIES, PARAMETERS, STRATEGY_VERSION
from autotrader.raoe import POLICY as RAOE_POLICY

STRATEGIES.update({s: {"strategy_version": STRATEGY_VERSION, "parameters": PARAMETERS} for s in IDENTITIES})
EXECUTION_POLICY = {"version": "4.8.0-shared.1", "baseline": BASELINE_POLICY, "raoe": RAOE_POLICY, "live_authorized": False}


def fingerprint() -> str:
    files = {p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}
    raoe = {p.name: digest(p.read_bytes()) for p in sorted((Path(__file__).parents[1]/'raoe').glob('*.py'))}
    return digest(canonical({'execution': execution_fingerprint(), 'paper': files, 'raoe': raoe}))


def risk_payload() -> dict[str, str]:
    return {k: str(v) for k, v in asdict(LIMITS).items()}
