"""Build successor features once; simulations share identical causal observations."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from autotrader.domain import Candle, MarketFeatures
from autotrader.opportunity.features import enrich
from autotrader.opportunity.patterns import replay


def prepare_panel(frames: dict[datetime, list[Candle]], features: dict[datetime, dict[str, MarketFeatures]]) -> None:
    histories: dict[str, list[Candle]] = defaultdict(list)
    cache: dict[str, tuple[int, dict[str, Any]]] = {}
    variants = ((Decimal('.02'), Decimal('1.3'), 8), (Decimal('.015'), Decimal('1.5'), 6), (Decimal('.03'), Decimal('1.2'), 12))
    for timestamp, frame in sorted(frames.items()):
        available = timestamp + timedelta(minutes=5)
        for candle in frame:
            history = histories[candle.symbol]
            history.append(candle)
            if len(history) > 720:
                history.pop(0)
            f = features.get(available, {}).get(candle.symbol)
            if f is None or not f.metadata.get('history_contiguous', True):
                continue
            bucket = int(available.timestamp()) // 900
            prior = cache.get(candle.symbol)
            f = enrich(f, history, available, cached_context=prior[1] if prior and prior[0] == bucket else None)
            cache[candle.symbol] = bucket, f.metadata['successor_context']
            patterns = {}
            candidate_context = f.metadata['successor_context']['15m']['ready'] and f.atr and f.ema_21 and (candle.close-f.ema_21)/f.atr <= 2
            for width, volume, age in (variants if candidate_context else ()):
                for hold in (0,2):
                    if hold==0 and candle.close <= candle.open:
                        continue
                    state = replay(history[-120:], compression_width=width, volume_ratio=volume, retest_bars=age, hold_bars=hold)
                    if state.stage == 'CONFIRMED':
                        key = ':'.join((str(width),str(volume),str(age)))
                        patterns[key+':'+str(hold)] = state.payload()
                        if hold==0:
                            patterns[key] = state.payload()
            f.metadata['successor_patterns'] = patterns
            features[available][candle.symbol] = f
