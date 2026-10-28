"""Interpretable, unvalidated paper hypotheses; no exchange order authority."""

VERSION = "4.8.0-paper.1"
STRATEGY_VERSION = "4.8.0-raoe.1"
IDENTITIES = ("RAOE_EARLY_RECOVERY", "RAOE_TREND_PULLBACK", "RAOE_BREAKOUT_RETEST")
PARAMETERS = {
    "minimum_net_reward_risk": "1.2", "minimum_reward_to_cost": "2",
    "stop_atr_buffer": "0.25", "maximum_extension_atr": "2",
    "holding_bars": "72", "entry_method": "CONFIRMED_REACTION_IOC",
    "volume_policy": "MID_PRICE_VOLUME_IS_NOT_TRADED_DEMAND",
}
QUALITY_GATES = {"causal_data", "setup_confirmed", "structural_plan", "net_economics", "noise_floor", "benchmark_known"}
POLICY = {"version": "4.8.0-quality.1", "estimated_edge": "UNKNOWN",
    "approval": "EXPERIMENTAL_PAPER_ONLY", "parameters": PARAMETERS,
    "stops": "structural invalidation plus volatility buffer; never tightened to qualify",
    "targets": "observed overhead or measured completed range, capped by higher structure",
    "execution": "fresh finite-depth taker IOC after completed reaction; no passive queue claims"}
