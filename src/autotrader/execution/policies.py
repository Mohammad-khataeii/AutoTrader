"""Exit versions are explicit experimental authority, not inferred from names."""
from __future__ import annotations

from typing import Any

from autotrader.raoe import IDENTITIES, exit_policy

SUCCESSORS={'A3_COST_AWARE_CONTINUATION','B3_STATEFUL_BREAKOUT','E3_ADAPTIVE_RELATIVE_STRENGTH'}


def policy_for(identity: str) -> dict[str,Any] | None:
    if identity in IDENTITIES:return exit_policy(identity)
    if identity in SUCCESSORS:
        return {'version':'4.9.0-matched-successor-exit.1','holding_seconds':10800,
                'target_fractions':['.3','.4','.3'],
                'failure_confirmation':'Existing successor position-specific causal exit rules',
                'comparison':'Three-hour matched baseline; old frozen 24-hour shadow history is unchanged'}
    return None
