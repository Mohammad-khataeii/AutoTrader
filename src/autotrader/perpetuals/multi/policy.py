"""Frozen experimental policy. Source changes require a new experiment identity."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

D = Decimal
EXPERIMENT = 'MULTI_USDT_MICRO_PAPER_V1'
COHORTS = (1, 3, 10)
INITIAL = D(1000)
FEE = D('.0006')
SLIP = D('.0005')
RISK = D('.005')
MAX_DRAWDOWN = D('.10')
MAX_POSITIONS = 3
MAX_TOTAL_MARGIN = D('.40')
MAX_TRADE_MARGIN = D('.25')
TARGET_TRADE_MARGIN = D('.12')
TARGET_ASSET_EQUITY = D('.5')
MAX_TOTAL_NOTIONAL = D(2000)
MAX_ASSET_NOTIONAL = D(1000)
# All crypto is conservatively one correlated group, including unclassified coins.
MAX_SAME_DIRECTION_EQUITY = D(1)
INTENT_TTL = 3000
MARK_MAX_AGE = 5000
POLICIES = ('MULTI_CONTINUATION_V1', 'MULTI_COMPRESSION_RETEST_V1',
            'MULTI_RANGE_V1', 'MULTI_FAILED_BREAK_REVERSAL_V1')
TERMS = {'experiment': EXPERIMENT, 'cohorts': COHORTS, 'initial': INITIAL,
         'fee': FEE, 'slip': SLIP, 'risk': RISK, 'max_drawdown': MAX_DRAWDOWN,
         'max_positions': MAX_POSITIONS, 'total_margin': MAX_TOTAL_MARGIN,
         'trade_margin': MAX_TRADE_MARGIN, 'target_trade_margin': TARGET_TRADE_MARGIN,
         'target_asset_equity': TARGET_ASSET_EQUITY, 'notional_cap': MAX_TOTAL_NOTIONAL,
         'asset_cap': MAX_ASSET_NOTIONAL, 'correlation': 'ALL_CRYPTO_ONE_GROUP',
         'same_direction_equity': MAX_SAME_DIRECTION_EQUITY, 'policies': POLICIES,
         'target_scope': ['.005', '.01'], 'qualification': 'EXPERIMENTAL_DETERMINISTIC',
         'execution': 'POST_DURABLE_INTENT_DEPTH_PROXY_WITH_RESIDUAL_SLIPPAGE_V1'}


def encode(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


FINGERPRINT = digest(TERMS)


def initial_state() -> dict[str, Any]:
    return {'experiment': EXPERIMENT, 'policy_hash': FINGERPRINT, 'entries_enabled': False,
            'lease': None, 'intents': {}, 'positions': {},
            'accounts': {str(n): {'cash': str(INITIAL), 'realized': '0', 'peak': str(INITIAL),
                'drawdown': '0', 'halted': False, 'fees': '0', 'funding': '0',
                'slippage':'0','closed': 0, 'liquidations': 0} for n in COHORTS}}
