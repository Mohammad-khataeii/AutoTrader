"""Playbook selection composes causal regime, structure and existing IOC pricing."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from autotrader.domain import (
    Candle,
    DataQuality,
    MarketFeatures,
    OrderBook,
    StrategySignal,
    TradingPair,
)
from autotrader.market_data.service import MarketDataService
from autotrader.opportunity.economics import CostAssumptions, CostAwareOpportunityEngine
from autotrader.opportunity.sizing import quote_for_plan
from autotrader.raoe import IDENTITIES, PARAMETERS, POLICY, STRATEGY_VERSION
from autotrader.raoe.plans import construct
from autotrader.raoe.playbooks import setup
from autotrader.raoe.regime import aggregate, assess
from autotrader.research.data import canonical, digest

D = Decimal


class RAOEEngine:
    def __init__(self, fee_bps: Decimal = D(10), slippage_bps: Decimal = D(8)):
        self.costs = CostAwareOpportunityEngine(CostAssumptions(fee_bps,fee_bps,slippage_bps))

    def evaluate(self, identity: str, f: MarketFeatures, pair: TradingPair, book: OrderBook,
                 btc: Any = None, eth: Any = None, candles: list[Candle] | None = None, *,
                 quote_budget: Decimal = D(75), sizing_scope: str = 'RESEARCH_ASSUMPTION',
                 sizing_context: dict[str, Any] | None = None,
                 benchmarks: dict[str, list[Candle]] | None = None,
                 assessment: dict[str, Any] | None = None) -> StrategySignal:
        if identity not in IDENTITIES: raise ValueError('unknown_raoe_identity')
        regime = assessment or assess(candles or [],book.timestamp,benchmarks)
        bars = aggregate(candles or [],5,book.timestamp)
        invalid, metrics = MarketDataService(None).validate_order_book(book)  # type: ignore[arg-type]
        invalid.extend(MarketDataService(None).validate_pair(pair))  # type: ignore[arg-type]
        if pair.base_asset in {'USDC','USDT','DAI','EURC','EURCV','EUROC','PYUSD','TUSD','FDUSD'}:
            invalid.append('pegged_asset_directional_exclusion')
        if f.timestamp != (bars[-1].timestamp if bars else None): invalid.append('feature_candle_mismatch')
        pattern = setup(identity,bars,regime)
        plan = construct(identity,bars,pair,book,regime,pattern)
        ready = regime['ready'] and not invalid and f.data_quality is DataQuality.GOOD and not f.metadata.get('completed_context_delayed')
        technical = bool(ready and pattern['confirmed'])
        structural = bool(technical and plan['valid'])
        sizing = {'quote_budget_eur': str(quote_budget), 'scope': sizing_scope}
        if structural and sizing_context:
            quote_budget,sizing = quote_for_plan(pair,book,D(plan['stop']),preferred=quote_budget,
                fee_bps=self.costs.assumptions.entry_fee_bps,slippage_bps=self.costs.assumptions.slippage_bps,**sizing_context)
            sizing['scope'] = sizing_scope
        economics = self.costs.evaluate(pair,book,quote_budget=quote_budget,stop=D(plan['stop']),
            targets=tuple(D(v) for v in plan['targets']),atr=D(regime['atr']),
            plausible_target=D(plan['ceiling']),holding_bars=int(PARAMETERS['holding_bars']),
            exit_fractions=(D('.3'),D('.4'),D('.3'))) if structural else None
        m = economics.measurements if economics else {}
        cost = D(m.get('estimated_total_round_trip_cost_eur','0'))
        gain = D((m.get('conditional_target_net_eur') or ['0'])[0])
        headroom = gain/cost if cost>0 else D(0)
        noise = bool(plan.get('valid'))
        bounded = not sizing_context or D(m.get('expected_net_stop_loss_eur','0'))<=sizing_context['limits'].max_planned_loss_per_trade
        economic = bool(economics and economics.feasible and headroom>=D(PARAMETERS['minimum_reward_to_cost']) and bounded)
        eligible = technical and structural and economic
        gates = {'causal_data': ready, 'setup_confirmed': technical, 'structural_plan': structural,
            'net_economics': economic, 'noise_floor': noise, 'benchmark_known': regime['benchmark'] in {'SUPPORTIVE','MIXED'}}
        reasons = [*invalid,*regime['errors']]
        if ready and not technical: reasons.append(pattern['reason'])
        if technical and not structural: reasons.append(plan['reason'])
        if structural and economics:
            reasons.extend(economics.reasons)
            if headroom<D(PARAMETERS['minimum_reward_to_cost']): reasons.append('target_cost_headroom')
            if not bounded: reasons.append('modeled_stop_loss_exceeds_account_budget')
        def stage(name: str, reached: bool, passed: bool | None) -> dict[str, Any]:
            return {'stage': name, 'reached': reached, 'passed': passed if reached else None,
                'state': 'NOT_REACHED' if not reached else 'UNKNOWN' if passed is None else 'PASSED' if passed else 'FAILED'}
        pipeline = [stage('SUPPORTED_MARKET',True,pair.quote_asset=='EUR'),stage('DISCOVERY_CANDIDATE',True,True),
            stage('FULL_DATA',True,ready),stage('STRATEGY_SETUP',ready,technical),
            stage('EXECUTION_PLAN',technical,structural),stage('ECONOMIC_QUALIFICATION',structural,economic),
            stage('PORTFOLIO_RISK',False,None),stage('PAPER_BROKER_ORDER',False,None),
            stage('VIRTUAL_FILL',False,None),stage('POSITION_CLOSED',False,None)]
        e = {'strategy_version': STRATEGY_VERSION, 'parameters': PARAMETERS, 'entry_eligible': eligible,
            'qualified': eligible,'technical_eligible': technical,'economic_eligible': economic,
            'veto': False,'unvalidated': True,'estimated_edge': 'UNKNOWN',
            'expected_value': {'status': 'ESTIMATED_EDGE=UNKNOWN','probability': None},
            'regime': ','.join(regime['labels']), 'raoe_regime': regime,
            'regime_assessment': {**regime,'trend': regime['timeframes']['5']['trend'],
                'liquidity': 'HEALTHY' if not invalid and metrics.liquidity_quote>=150 else 'LIQUIDITY_STRESS'},
            'entry_plan': plan, 'pattern_state': pattern, 'holding_bars': int(PARAMETERS['holding_bars']),
            'holding_seconds': int(PARAMETERS['holding_bars'])*300,'timeframe': '5m',
            'sizing': sizing, 'economics': economics.payload() if economics else None,
            'quality_policy': {'version': POLICY['version'],'gates': gates,'target_net_to_roundtrip_cost': str(headroom)},
            'pipeline': pipeline,'reasons': list(dict.fromkeys(reasons)), 'as_of': f.timestamp.isoformat(),
            'qualification_state': 'PAPER_ELIGIBLE_EDGE_UNKNOWN' if eligible else 'WATCHING' if ready else 'STALE_OR_MISSING',
            'data_hash': digest(canonical([[c.timestamp.isoformat(),str(c.close),str(c.high),str(c.low)] for c in bars]))}
        return StrategySignal('sig_'+digest((identity+pair.symbol+f.timestamp.isoformat()).encode())[:40],
            identity,pair.symbol,f.timestamp,D(sum(gates.values()))/len(gates),f.data_quality,e,
            [pattern['reason']],['structural_invalidation'],f.spread_bps or D(0),
            'Unvalidated paper hypothesis; '+(','.join(reasons) or 'qualified conditional payoff; predictive edge unknown'))
