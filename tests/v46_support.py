"""Favorable deterministic fixtures prove software liveness only, never market returns."""
import copy
from decimal import Decimal as D

from test_v42_lifecycle import experimental_frame


def successor_frame(strategy):
    frame = experimental_frame('SYNTHETIC-V46-' + strategy, D('130.5') if strategy.startswith('B3') else D('129.1'))
    if strategy.startswith('A3'):
        for market in frame['markets'].values():
            for c in market['candles'][:-2]:
                close = D(c['close']);c.update(high=str(close+D('1.5')),low=str(close-D('1.5')))
    elif strategy.startswith('B3'):
        for market in frame['markets'].values():
            for c in market['candles']:
                close = D(c['close']);c.update(high=str(close+D('.8')),low=str(close-D('.8')))
            # Prior higher-horizon movement supports the target; the latest
            # twenty-bar compression remains tight and causally observable.
            for candle in market['candles'][-45:-25]:
                close = D(candle['close']);candle.update(high=str(close+D(4)),low=str(close-D(4)))
            market['candles'][-4].update(open='129',close='130.5',high='130.6',low='128.8',volume='3000')
            market['candles'][-3].update(open='130.6',close='130.4',high='130.7',low='130.2',volume='1000')
            market['candles'][-2].update(open='130.5',close='130.3',high='130.6',low='129',volume='1000')
            market['candles'][-1].update(open='130.3',close='130.5',high='130.8',low='129',volume='1600')
    elif strategy.startswith('E3'):
        frame['pairs'].append({**frame['pairs'][0],'symbol':'SOL-EUR','base_asset':'SOL'})
        frame['markets']['SOL-EUR'] = copy.deepcopy(frame['markets']['BTC-EUR'])
        for i,c in enumerate(frame['markets']['SOL-EUR']['candles']):
            close = D(100)+D(i)*D('.04')+D(max(0,i-699))*D('.23')
            c.update(open=str(close-D('.1')),high=str(close+D('1.5')),low=str(close-D('1.5')),close=str(close),volume='2000' if i==719 else '1000')
        frame['markets']['SOL-EUR']['book'].update(bids=[['133.36','1000']],asks=[['133.37','1000']])
    else:
        raise ValueError('unknown_synthetic_successor')
    return frame
