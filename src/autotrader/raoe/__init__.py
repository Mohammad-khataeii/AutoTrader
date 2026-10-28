"""Interpretable, unvalidated paper hypotheses; no exchange order authority."""

VERSION = "4.9.0-paper.1"
STRATEGY_VERSION = "4.9.0-raoe.1"
PRIMARY_IDENTITIES = ("RAOE_EARLY_RECOVERY", "RAOE_TREND_PULLBACK", "RAOE_BREAKOUT_RETEST")
IDENTITIES = (*PRIMARY_IDENTITIES,"RAOE_BREAKOUT_CONTINUATION")
PARAMETERS = {
    "minimum_net_reward_risk": "1.2", "minimum_reward_to_cost": "2",
    "stop_atr_buffer": "0.25", "maximum_extension_atr": "2",
    "holding_bars": "72", "entry_method": "CONFIRMED_REACTION_IOC",
    "volume_policy": "MID_PRICE_VOLUME_IS_NOT_TRADED_DEMAND",
    "structure_model": "4.9.0-significance.1", "minimum_structural_timeframe_minutes": "15",
    "swing_prominence_atr": "1.25", "continuation_maximum_extension_atr": "5",
    "continuation_range_bars": "24", "continuation_near_depth_budget_multiple": "2",
}
QUALITY_GATES = {"causal_data", "setup_confirmed", "structural_plan", "net_economics", "noise_floor", "benchmark_known"}
POLICY = {"version": "4.9.0-quality.1", "estimated_edge": "UNKNOWN",
    "approval": "EXPERIMENTAL_PAPER_ONLY", "parameters": PARAMETERS,
    "stops": "structural invalidation plus volatility buffer; never tightened to qualify",
    "targets": "observed overhead or measured completed range, capped by higher structure",
    "execution": "fresh finite-depth taker IOC after completed reaction; no passive queue claims"}


def parameters_for(identity: str) -> dict[str,str]:
    return {**PARAMETERS,'holding_bars':'48','entry_method':'CONFIRMED_CONTINUATION_IOC'} if identity=='RAOE_BREAKOUT_CONTINUATION' else dict(PARAMETERS)


def exit_policy(identity: str) -> dict[str,object]:
    continuation=identity=='RAOE_BREAKOUT_CONTINUATION'
    return {'version':'4.9.0-continuation-exit.1' if continuation else '4.9.0-structure-exit.1',
            'holding_seconds':14400 if continuation else 21600,'target_fractions':['.3','.4','.3'],
            'failure_confirmation':'two completed 15m closes' if continuation else 'two completed 5m closes and entry-specific structure',
            'protective_stops':'fresh observed bid; always ahead of discretionary exits',
            'target_semantics':'structural bid scenarios converted once to net unit floors'}
