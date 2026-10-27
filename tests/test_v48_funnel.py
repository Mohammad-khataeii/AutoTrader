"""Read-model stages describe durable lifecycle evidence, not assumed failures."""
from types import SimpleNamespace

from autotrader.api.v48 import execution_stages


def pipeline():
    return [{'stage':str(i),'state':'NOT_REACHED','passed':None,'reached':False} for i in range(10)]


def test_pending_order_and_open_position_are_unknown_until_their_outcome_exists():
    original=pipeline()
    pending=SimpleNamespace(order_id='order',position_id='position',status='PENDING')
    result=execution_stages(original,[pending],set(),set())
    assert result[7]['state']=='PASSED' and result[8]['state']=='UNKNOWN'
    assert result[9]['state']=='NOT_REACHED' and original==pipeline()
    pending.status='FILLED'
    result=execution_stages(original,[pending],{'order'},set())
    assert result[8]['state']=='PASSED' and result[9]['state']=='UNKNOWN'
    assert execution_stages(original,[pending],{'order'},{'position'})[9]['state']=='PASSED'


def test_broker_rejection_does_not_count_unreached_fills_as_a_failed_execution():
    rejected=SimpleNamespace(order_id='order',position_id='position',status='REJECTED')
    result=execution_stages(pipeline(),[rejected],set(),set())
    assert [s['state'] for s in result[7:]]==['FAILED','NOT_REACHED','NOT_REACHED']
