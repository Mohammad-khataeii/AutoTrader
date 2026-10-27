"""Previously examined real observations are regression data, never a holdout."""
import json
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from autotrader.domain import Candle
from autotrader.raoe.regime import aggregate, assess

DATA=json.loads((Path(__file__).parents[1]/'docs/evidence/v4_8/audit-regression-fixture.json').read_text())


def test_recorded_net_payoffs_do_not_subtract_embedded_costs_twice():
    assert DATA['cases']
    for case in DATA['cases']:
        m=case['measurements'];p=m['assumptions'];q=D(m['fillable_quantity'])
        basis=D(m['cost_basis_eur'])/q
        factor=(1-D(p['exit_fee_bps'])/10000)*(1-D(p['slippage_bps'])/10000)*(1-D(m['exit_now']['depth_impact_bps'])/10000)
        reward=q*(D(m['targets'][0])*factor-basis)
        risk=q*(basis-D(m['stop'])*factor)
        assert abs(reward-D(m['conditional_target_net_eur'][0]))<D('1e-10')
        assert abs(risk-D(m['expected_net_stop_loss_eur']))<D('1e-10')
        assert abs(reward/risk-D(m['net_reward_risk']))<D('1e-10')


def test_recorded_diagnostic_assets_have_causal_completed_aggregations():
    for symbol,rows in DATA['candles'].items():
        if not rows:continue
        bars=[Candle(symbol,datetime.fromisoformat(r['timestamp']),*[D(r[k]) for k in ['open','high','low','close','volume']],'5m',r['source']) for r in rows]
        as_of=bars[-1].timestamp+timedelta(minutes=5)
        for minutes in [15,60,240]:
            assert all(c.timestamp+timedelta(minutes=minutes)<=as_of for c in aggregate(bars,minutes,as_of))
        before=assess(bars,as_of)
        future=Candle(symbol,as_of,D(999),D(1000),D(998),D(999),D(1),'5m','revolut-x:engineering-future')
        assert assess([*bars,future],as_of)==before
