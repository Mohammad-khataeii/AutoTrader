"""Versioned EUR7000 experimental authority. Never authorizes exchange mutations."""
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from autotrader.opportunity.engine import SUCCESSOR_REGISTRY, SuccessorParameters
from autotrader.research.data import canonical, digest
from autotrader.risk import RiskLimits
from autotrader.shadow.versions import execution_fingerprint

D = Decimal
ACCOUNT = "PERSONAL_PLAN_PAPER_7000"
REGISTRY_KEY = "personal_paper_v47"
INITIAL = D(7000)
VERSION = "4.9.2-paper.1"
LIMITS = RiskLimits(max_allocated_capital=INITIAL, max_total_open_exposure=D(4200),
    min_uncommitted_reserve=D(2800), max_position_size=D(700), max_simultaneous_positions=6,
    max_planned_loss_per_trade=D(35), daily_loss_threshold=D(140),
    weekly_loss_threshold=D(350), max_new_entries_per_day=24, planned_loss_cost_bps=D(40))
AGGREGATE_STOP_RISK = D(140)
CORRELATED_CAPITAL = D(2100)
STRATEGY_CAPITAL = D(2100)
MAX_DRAWDOWN = D('.10')
STRATEGIES: dict[str,dict[str,Any]] = {s.strategy_id: {"strategy_version": s.version, "parameters": SuccessorParameters().payload()}
              for s in SUCCESSOR_REGISTRY}
from autotrader.execution.policies import policy_for
from autotrader.personal_paper.admission import POLICY as PRIMARY_ADMISSION
from autotrader.personal_paper.selection import POLICY as BASELINE_POLICY
from autotrader.raoe import POLICY as RAOE_POLICY
from autotrader.raoe import PRIMARY_IDENTITIES, STRATEGY_VERSION, exit_policy, parameters_for

STRATEGIES.update({s: {"strategy_version": STRATEGY_VERSION, "parameters": parameters_for(s),
                      "exit_policy":exit_policy(s)} for s in PRIMARY_IDENTITIES})
for identity,spec in STRATEGIES.items():
    spec['exit_policy']=policy_for(identity)
EXECUTION_POLICY = {"version": "4.9.1-shared.1", "primary_admission": PRIMARY_ADMISSION, "baseline": BASELINE_POLICY, "raoe": RAOE_POLICY, "live_authorized": False,
                    "approved_ml_model": None, "ml_authority": "ISOLATED_SHADOW_RESEARCH_ONLY",
                    "continuation":"Historical and isolated forward shadow research only; absent from primary authority"}


def fingerprint() -> str:
    files = {p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}
    raoe = {p.name: digest(p.read_bytes()) for p in sorted((Path(__file__).parents[1]/'raoe').glob('*.py'))}
    return digest(canonical({'execution': execution_fingerprint(), 'paper': files, 'raoe': raoe}))


def risk_payload() -> dict[str, str]:
    return {k: str(v) for k, v in asdict(LIMITS).items()}
