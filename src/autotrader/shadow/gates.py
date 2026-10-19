"""Read-only attribution of executed decisions. Unknown evidence never becomes a pass."""
from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any


def first_blocker(row: dict[str, Any]) -> str:
    """Stage attribution, not a claim that one independent condition is sufficient."""
    if row.get('technical_eligible') is True and row.get('economic_eligible') is False:
        return 'economics:' + str(next(iter(row.get('independently_failed', [])), 'unverified_cost_outcome'))
    if row.get('decision_accepted'):
        if row.get('trace_execution_state') == 'EXCEPTION':
            return 'execution:system_exception'
        if row.get('trace_execution_state') == 'OUTCOME_UNAVAILABLE':
            return 'execution:outcome_unavailable'
        allocation = row.get('allocation', {})
        if allocation.get('reached') and not allocation.get('accepted'):
            return 'allocation'
        execution = row.get('execution', {})
        if execution.get('reached') and execution.get('stage') == 'entry':
            return 'none' if row.get('final_state') == 'ACCEPTED' else 'execution:' + str(execution.get('refusal_gate', 'unobserved_outcome'))
        return 'pending_execution'
    if row.get('reason') == 'No valid entry price.':
        return 'entry_price'
    # Signal eligibility includes both entry predicates and allowed regimes.
    # A concurrent D2 veto is causal only after an otherwise eligible signal.
    if row.get('signal_entry_eligible') is False:
        if row.get('diagnostic_parity') is False:
            return 'strategy_unresolved_diagnostic_mismatch'
        failed = row.get('independently_failed', [])
        if failed:
            return 'strategy:' + str(failed[0])
        if row.get('regime_veto'):
            return 'strategy:market_regime'
        return 'strategy:unresolved'
    if row.get('signal_entry_eligible') is not True:
        return 'unknown'
    if row.get('data_quality') != 'GOOD':
        return 'data_quality'
    if row.get('momentum_veto'):
        return 'momentum_veto'
    if row.get('risk', {}).get('reached'):
        return 'risk'
    return 'decision:unresolved'


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    intersections: Counter[str] = Counter()
    components: Counter[str] = Counter()
    conditions: dict[str, Counter[str]] = {}
    component_symbols: dict[str, set[str]] = {}
    eligible_veto: Counter[str] = Counter()
    counts = Counter(evaluations=len(rows))
    for row in rows:
        for name, value in row.get("entry_conditions", {}).items():
            conditions.setdefault(name, Counter()).update(["pass" if value is True else "fail" if value is False else "unknown"])
        failed = list(row.get('independently_failed', []))
        if row.get('regime_veto'):
            failed.append('market_regime')
        if row.get('momentum_veto'):
            failed.append('momentum_veto')
        if row.get('data_quality') and row['data_quality'] != 'GOOD':
            failed.append('data_quality')
        failures.update(set(failed))
        intersections.update(' & '.join(pair) for pair in combinations(sorted(set(failed)), 2))
        blockers.update([first_blocker(row)])
        for name, value in row.get('momentum_components', {}).items():
            if value is True:
                components.update([name])
                component_symbols.setdefault(name, set()).add(row['symbol'])
                if row.get('signal_entry_eligible') is True:
                    eligible_veto.update([name])
        counts['eligible_signals'] += row.get('signal_entry_eligible') is True
        counts['accepted_buy_decisions'] += row.get('decision_accepted') is True and row.get('action', 'BUY') == 'BUY'
        counts['allocation_attempts'] += row.get('allocation', {}).get('reached') is True
        counts['allocation_refusals'] += row.get('allocation', {}).get('accepted') is False
        execution = row.get('execution', {})
        trace_state = row.get('trace_execution_state')
        reached = bool(trace_state in {'SUCCEEDED', 'REJECTED', 'EXCEPTION', 'OUTCOME_UNAVAILABLE'} or (execution.get('reached') is True and execution.get('stage') == 'entry'))
        counts['execution_exceptions'] += trace_state == 'EXCEPTION'
        counts['execution_outcomes_unavailable'] += trace_state == 'OUTCOME_UNAVAILABLE'
        counts['execution_attempts'] += reached
        counts['accepted_paper_orders'] += reached and row.get('final_state') == 'ACCEPTED'
        counts['execution_refusals'] += reached and row.get('final_state') == 'REJECTED'
    n = len(rows)
    return {
        'counts': dict(counts),
        'condition_observations': {k: {state: c[state] for state in ('pass', 'fail', 'unknown')} for k,c in conditions.items()},
        'independent_failures': {k: {'count': v, 'percent_of_evaluations': round(100*v/n, 3) if n else None}
                                 for k, v in failures.most_common()},
        'causal_first_blockers': dict(blockers.most_common()),
        'pairwise_intersections': dict(intersections.most_common()),
        'momentum_components': {k: {'count': v, 'symbols': sorted(component_symbols[k]),
                                     'otherwise_eligible': eligible_veto[k]}
                                for k, v in components.items()},
        'diagnostic_mismatches': sum(r.get('diagnostic_parity') is False for r in rows),
        'unannotated_or_legacy_schema': sum(r.get('schema') != 'shadow-decision-explanation/2' for r in rows),
        'limitation': 'Counts cover this bounded decision window only. Pre-strategy skips, fills and positions are separate records; absent telemetry is unknown, never zero. Independent failures overlap.',
    }
