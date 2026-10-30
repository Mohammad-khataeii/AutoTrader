"""Stage-specific causal observations. Market paths never imply executable orders.

The immutable PostgreSQL signal is authoritative. This additive research schema
retains exclusions and normal rejections independently of true corruption, and
never rewrites V4.9.2 observations or financial postings.
"""
from __future__ import annotations

import json
import math
from datetime import timedelta
from typing import Any

from autotrader.learning.features import finite, stamp
from autotrader.research.data import canonical, digest

MARKET_SCHEMA = 'completed-market/4.9.3.1'
MARKET_TARGET = 'midpoint-path/4.9.3.1'
MARKET_NAMES = ('return_30m','relative_return_30m','atr_fraction','volume_ratio',
                'volume_missing','benchmark_return_30m','ema9_distance_atr',
                'asset_15m_bullish','asset_hour_bearish','higher_unknown',
                'benchmark_risk_off','hour_sin','hour_cos')


class Unavailable(ValueError):
    """Ordinary source coverage exclusion, distinct from malformed evidence."""


def market_features(event: dict[str, Any]) -> dict[str, Any]:
    e = event['evidence'];observed = stamp(event['observed_at'])
    if not e.get('as_of'):
        raise Unavailable('missing_completed_snapshot')
    candle = stamp(e['as_of']);cutoff = candle+timedelta(minutes=5)
    if cutoff > observed:
        raise ValueError('future_input_snapshot')
    if observed >= cutoff+timedelta(minutes=5):
        raise Unavailable('stale_decision_snapshot')
    snapshot = e.get('learning_context') or {}
    source_hash = snapshot.get('data_hash') or e.get('data_hash')
    if not source_hash:
        raise Unavailable('legacy_unbound_snapshot')
    r = snapshot.get('regime') or e.get('raoe_regime') or {}
    frames = r.get('timeframes') or {};peers = r.get('benchmarks') or {}
    if set(peers) != {'BTC-EUR','ETH-EUR'} or any(k not in frames for k in ('5','15','60')):
        raise Unavailable('missing_market_context')
    for minutes,frame in [*((int(k),frames[k]) for k in ('5','15','60','240') if k in frames), *((5,f) for f in peers.values())]:
        if minutes==240 and (frame.get('unknown_reason') or frame.get('trend')=='UNKNOWN'):continue
        if frame.get('unknown_reason') or not frame.get('last_closed_at'):
            raise Unavailable('incomplete_timeframe_context')
        if stamp(frame['last_closed_at'])+timedelta(minutes=minutes) > cutoff:
            raise ValueError('future_timeframe_context')
    primary = (e.get('primary_admission') or {}).get('inputs') or {}
    raw_close = snapshot.get('close') or primary.get('close')
    if raw_close is None:
        raise Unavailable('missing_completed_close_no_vwap_imputation')
    close, a = finite(raw_close),finite(r['atr'])
    if close <= 0 or a <= 0:
        raise ValueError('invalid_market_geometry')
    mean = sum(finite(peers[s]['return_30m']) for s in ('BTC-EUR','ETH-EUR'))/2
    relative = finite(r['relative_return_30m']);volume = snapshot.get('volume_ratio')
    if volume is not None and finite(volume)<0:
        raise ValueError('negative_volume')
    values = [mean+relative,relative,a/close,finite(volume) if volume is not None else 0.,
              float(volume is None),mean,(close-finite(frames['5']['ema9']))/a,
              float(frames['15']['trend']=='BULLISH'),float(frames['60']['trend']=='BEARISH'),
              float(bool((frames.get('240') or {}).get('unknown_reason')) or (frames.get('240') or {}).get('trend','UNKNOWN')=='UNKNOWN'),
              float(r.get('benchmark')=='RISK_OFF'),math.sin(observed.hour*math.pi/12),math.cos(observed.hour*math.pi/12)]
    return {'schema':MARKET_SCHEMA,'names':list(MARKET_NAMES),'values':[finite(v) for v in values],
            'reference_mid':close,'completed_cutoff':cutoff.isoformat(),'known_at':event['observed_at'],
            'source_data_hash':source_hash,'source_evidence_hash':digest(canonical(e)),
            'profile':e.get('execution_profile'),'strategy':event['strategy_id'],
            'regime':(snapshot.get('market_state') or {}).get('state') or r.get('benchmark','UNKNOWN'),
            'reference_kind':'COMPLETED_CANDLE_MID_NOT_EXECUTION_PRICE'}


def stage(e: dict[str, Any]) -> str:
    if e.get('technical_eligible') is not True:return 'TECHNICAL_REJECTED'
    m = (e.get('economics') or {}).get('measurements') or {}
    if not m:return 'TECHNICAL_VALID_UNPRICED'
    if e.get('economic_eligible') is not True:return 'ECONOMICS_REJECTED'
    if not e.get('entry_eligible'):return 'PRIMARY_ADMISSION_REJECTED'
    return 'PRICED_CANDIDATE'


def ingest(store: Any, event: dict[str, Any], now: str) -> None:
    """Enroll once; optional plan task requires a fully priced positive quantity."""
    if store.db.execute('SELECT 1 FROM funnel WHERE id=?',(event['id'],)).fetchone():return
    e=event['evidence'];state=stage(e);disposition='OBSERVED';reason=None;features=None
    if event.get('evidence_category')!='REVOLUT_X_PROSPECTIVE_PAPER':
        disposition,reason='SOURCE_EXCLUDED','nonprospective_source'
    else:
        try:features=market_features(event)
        except Unavailable as error:disposition,reason='COVERAGE_EXCLUDED',str(error)
        except (KeyError,ValueError,TypeError,IndexError,ZeroDivisionError) as error:
            disposition,reason='DATA_QUALITY_FAILED',type(error).__name__+':'+str(error)
    metadata={'reasons':e.get('reasons',[]),'technical':e.get('technical_eligible'),
              'economic':e.get('economic_eligible'),'baseline_eligible':event.get('baseline_eligible',False),
              'primary_admission':e.get('primary_admission'),'market_state':(e.get('learning_context') or {}).get('market_state'),
              'hypotheses':(e.get('learning_context') or {}).get('hypotheses')}
    m=(e.get('economics') or {}).get('measurements') or {}
    complete_plan=False
    if features and m.get('entry',{}).get('vwap') is not None:
        try:
            quantity=finite(m.get('fillable_quantity',0))
            if quantity>0:
                from autotrader.learning.features import build
                build(e,event['strategy_id'],event['observed_at'])
                if len(e['entry_plan']['targets'])!=3:raise ValueError('three_targets_required')
                # Access all label requirements before enrolling, not four hours later.
                for key in ('exit_fee_bps','slippage_bps'):finite(m['assumptions'][key])
                complete_plan=True
            elif e.get('economic_eligible') is True:raise ValueError('eligible_plan_without_quantity')
        except (KeyError,ValueError,TypeError,IndexError,ZeroDivisionError) as error:
            # Infeasible geometry is an ordinary economic rejection. Missing
            # higher-frame coverage cannot invalidate a valid market snapshot.
            message=str(error)
            metadata['plan_feature_exclusion']=type(error).__name__+':'+message
            if message in {'unavailable_context','missing_benchmark_features'}:
                pass
            elif e.get('economic_eligible') is True or message=='nonfinite_feature':
                disposition,reason='DATA_QUALITY_FAILED','invalid_priced_plan:'+type(error).__name__+':'+message
    elif e.get('economic_eligible') is True and not m.get('entry',{}).get('vwap'):
        disposition,reason='DATA_QUALITY_FAILED','economically_eligible_without_priced_plan'
    store.db.execute('INSERT INTO funnel VALUES (?,?,?,?,?,?,?,?,?)',
        (event['id'],event['observed_at'],state,disposition,reason,e.get('execution_profile'),digest(canonical(e)),int(complete_plan),canonical(metadata).decode()))
    if features:
        compact={k:event[k] for k in ('id','symbol','strategy_id','observed_at','baseline_eligible')}
        compact.update(features=features,rejection=event.get('rejection'),profile=e.get('execution_profile'))
        prediction=None;model_id=store.get('market_challenger')
        if model_id:
            from autotrader.learning.market_model import predict_market
            run=store.read_artifact(model_id)
            if stamp(run['trained_at'])<=stamp(event['observed_at'])<=stamp(now)<stamp(event['observed_at'])+timedelta(seconds=90):
                prediction={**predict_market(run['model'],features),'model_id':model_id,'predicted_at':now,
                            'category':'SHADOW_FORWARD_MARKET_PREDICTION','primary_execution_authorized':False}
        store.db.execute('INSERT INTO market_observations(id,observed_at,payload,prediction) VALUES (?,?,?,?)',
            (event['id'],event['observed_at'],canonical(compact).decode(),canonical(prediction).decode() if prediction else None))
    if complete_plan:
        from autotrader.learning.controller import ingest as priced_ingest
        priced_ingest(store,event,now)


def market_label(event: dict[str, Any], candles: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    start=stamp(event['observed_at']);end=start+timedelta(minutes=horizon)
    first=(int(start.timestamp())//300+1)*300;rows: dict[int,dict[str,Any]]={}
    for c in candles:
        t=stamp(c['timestamp']);n=int(t.timestamp())
        if n<first or n+300>end.timestamp():continue
        if n%300 or c['symbol']!=event['symbol'] or not c['source'].startswith('revolut-x'):
            raise ValueError('invalid_market_target_source')
        values=[finite(c[k]) for k in ('open','high','low','close')];o,h,l,close=values
        if not 0<l<=min(o,close)<=max(o,close)<=h:raise ValueError('invalid_future_bar')
        if n in rows and rows[n]!=c:raise ValueError('conflicting_target_versions')
        rows[n]=c
    expected=list(range(first,int(end.timestamp())//300*300,300))
    if not expected or sorted(rows)!=expected:raise ValueError('incomplete_future_window')
    reference=finite(event['features']['reference_mid']);ret=finite(rows[expected[-1]]['close'])/reference-1
    return {'schema':MARKET_TARGET,'end_at':end.isoformat(),'horizon_minutes':horizon,
            'mid_return':ret,'positive':int(ret>0),
            'mfe':max(finite(rows[t]['high']) for t in expected)/reference-1,
            'mae':min(finite(rows[t]['low']) for t in expected)/reference-1,
            'path_hash':digest(canonical([rows[t] for t in expected])),
            'evidence_category':'RECORDED_MIDPOINT_PATH_NON_EXECUTABLE',
            'executable_outcome_proven':False,'cost_adjusted':False,
            'limitations':['Completed decision close as reference; unobserved partial entry interval',
                           'No entry, future spread, depth, fees or managed exit is assumed']}


def mature(store: Any,event: dict[str,Any],candles: list[dict[str,Any]],now: str) -> None:
    if stamp(now)<stamp(event['observed_at'])+timedelta(hours=4):return
    try:
        targets={str(h):market_label(event,candles,h) for h in (60,240)}
        result={**event,'targets':targets,'target':targets['240']}
        store.db.execute("UPDATE market_observations SET status='LABELED',result=? WHERE id=? AND status='PENDING'",(canonical(result).decode(),event['id']))
    except (KeyError,ValueError,TypeError,ZeroDivisionError) as error:
        if stamp(now)>stamp(event['observed_at'])+timedelta(hours=48):
            store.db.execute("UPDATE market_observations SET status='WINDOW_UNAVAILABLE',result=? WHERE id=? AND status='PENDING'",(canonical({'reason':str(error)}).decode(),event['id']))
    store.db.execute("UPDATE market_observations SET next_attempt_at=? WHERE id=? AND status='PENDING'",((stamp(now)+timedelta(minutes=30)).isoformat(),event['id']))


def summary(store: Any) -> dict[str, Any]:
    stages=dict(store.db.execute('SELECT stage,count(*) FROM funnel GROUP BY stage'))
    dispositions=dict(store.db.execute('SELECT disposition,count(*) FROM funnel GROUP BY disposition'))
    reasons=dict(store.db.execute('SELECT reason,count(*) FROM funnel WHERE reason IS NOT NULL GROUP BY reason ORDER BY count(*) DESC LIMIT 15'))
    latest=[]
    for identity,observed,state,payload in store.db.execute('SELECT id,observed_at,stage,metadata FROM funnel ORDER BY observed_at DESC,id LIMIT 15'):
        latest.append({'id':identity,'observed_at':observed,'stage':state,**json.loads(payload)})
    return {'version':'staged-funnel/4.9.3.1','unique_signals':sum(stages.values()),'stages':stages,
            'dispositions':dispositions,'coverage_reasons':reasons,'latest':latest,
            'market_counts':dict(store.db.execute('SELECT status,count(*) FROM market_observations GROUP BY status')),
            'priced_plans':store.db.execute('SELECT count(*) FROM funnel WHERE priced_plan=1').fetchone()[0],
            'stage_scope':'Original signal stage; accepted orders/fills/closed positions are linked separately',
            'market_returns_are_executable':False}
