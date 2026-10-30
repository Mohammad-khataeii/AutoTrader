"""Separate midpoint direction task, never a substitute for executable-plan EV.

Parameters are predeclared. Train/normalization, calibration, walk-forward and a
sealed final holdout are chronological, purged and globally nonoverlapping.
"""
from __future__ import annotations

import json
from datetime import timedelta
from statistics import mean
from typing import Any

from autotrader.learning.evaluation import independent
from autotrader.learning.features import stamp
from autotrader.learning.lifecycle import MARKET_SCHEMA, MARKET_TARGET
from autotrader.learning.model import CONFIG, fit, predict
from autotrader.research.data import canonical, digest


def predict_market(model: dict[str, Any],features: dict[str, Any]) -> dict[str, Any]:
    p=predict(model,features)
    return {'probability_mid_up':p['probability_net_positive'],
            'conditional_expected_mid_return':p['conditional_expected_net_return'],
            'feature_drift_fraction':p['feature_drift_fraction'],'confidence':p['confidence'],
            'task':'MARKET_MIDPOINT_DIRECTION','executable_trade_quality':None,
            'primary_execution_authorized':False}


def independent_rows(store: Any) -> list[dict[str,Any]]:
    rows: list[dict[str,Any]]=[];cursor='1970-01-01T00:00:00+00:00'
    while len(rows)<50000:
        r=store.db.execute("SELECT result FROM market_observations WHERE status='LABELED' AND observed_at>=? ORDER BY observed_at,id LIMIT 1",(cursor,)).fetchone()
        if not r:break
        row=json.loads(r[0]);rows.append(row);end=row['target']['end_at']
        if stamp(end)<=stamp(row['observed_at']):raise ValueError('nonpositive_learning_window')
        cursor=end
    return rows


def evaluate(rows: list[dict[str,Any]],sealed: list[list[str]],previous_end: str | None=None) -> dict[str,Any]:
    available=[r for r in rows if not any(stamp(r['observed_at'])<=stamp(hi) and stamp(r['target']['end_at'])>=stamp(lo) for lo,hi in sealed)]
    episodes=independent(available)
    base={'task':'MARKET_MIDPOINT_DIRECTION','feature_schema':MARKET_SCHEMA,'target_schema':MARKET_TARGET,
          'dataset_hash':digest(canonical(rows)),'config':CONFIG,'independent_episodes':len(episodes),
          'evidence_category':'RECORDED_MIDPOINT_PATH_NON_EXECUTABLE',
          'primary_promotion':False,'cost_stress':'NOT_APPLICABLE_WITHOUT_EXECUTABLE_PLAN',
          'baseline':'Training-period positive prevalence; separate from approved trading policy'}
    if len(episodes)<CONFIG['min_episodes'] or stamp(episodes[-1]['observed_at'])-stamp(episodes[0]['observed_at'])<timedelta(days=CONFIG['min_days']):
        return {**base,'status':'INSUFFICIENT_EVIDENCE','required_episodes':CONFIG['min_episodes'],'required_days':CONFIG['min_days']}
    if previous_end and sum(stamp(r['observed_at'])>stamp(previous_end) for r in episodes)<CONFIG['min_new_episodes']:
        return {**base,'status':'COLLECTING_NEW_INDEPENDENT_EVIDENCE'}
    n=len(episodes);train,cal,walk,hold=episodes[:int(n*.5)],episodes[int(n*.5):int(n*.65)],episodes[int(n*.65):int(n*.8)],episodes[int(n*.8):]
    if previous_end:hold=[r for r in hold if stamp(r['observed_at'])>stamp(previous_end)]
    def purge(left: list[dict[str,Any]],right: list[dict[str,Any]]) -> list[dict[str,Any]]:
        return [r for r in left if stamp(r['target']['end_at'])+timedelta(hours=4)<stamp(right[0]['observed_at'])] if right else []
    train,cal,walk=purge(train,cal),purge(cal,walk),purge(walk,hold)
    if min(map(len,(train,cal,walk,hold)))<CONFIG['min_partition']:
        return {**base,'status':'INSUFFICIENT_PURGED_PARTITIONS'}
    # Only the numerical estimator adapter uses the generic mean-return input.
    # Artifacts/reports/forward predictions retain midpoint-specific semantics.
    def adapt(sample: list[dict[str,Any]]) -> list[dict[str,Any]]:
        return [{**r,'target':{**r['target'],'net_return':r['target']['mid_return']}} for r in sample]
    try:model=fit(adapt(train),adapt(cal))
    except ValueError as error:return {**base,'status':'QUARANTINED','reasons':[str(error)]}
    model['task']='MARKET_MIDPOINT_DIRECTION'
    prevalence=mean(r['target']['positive'] for r in train)
    def score(sample: list[dict[str,Any]]) -> dict[str,Any]:
        ps=[predict_market(model,r['features']) for r in sample];bins=[]
        for lo in (0.,.2,.4,.6,.8):
            pairs=[(r,p['probability_mid_up']) for r,p in zip(sample,ps) if lo<=p['probability_mid_up']<lo+.2 or lo==.8 and p['probability_mid_up']==1]
            if pairs:bins.append({'n':len(pairs),'predicted':mean(p for _,p in pairs),'observed':mean(r['target']['positive'] for r,_ in pairs)})
        return {'episodes':len(sample),'brier':mean((p['probability_mid_up']-r['target']['positive'])**2 for r,p in zip(sample,ps)),
                'baseline_brier':mean((prevalence-r['target']['positive'])**2 for r in sample),
                'calibration_error':sum(b['n']*abs(b['predicted']-b['observed']) for b in bins)/len(sample),
                'calibration_bins':bins,'drift':mean(p['feature_drift_fraction'] for p in ps)}
    comparisons=[{'partition':name,**score(sample)} for name,sample in [('walk_forward_1',walk[:len(walk)//2]),('walk_forward_2',walk[len(walk)//2:]),('untouched_holdout',hold)]]
    reasons=[]
    for c in comparisons:
        if c['brier']>=c['baseline_brier']:reasons.append('no_directional_calibration_advantage')
        if c['calibration_error']>.15:reasons.append('calibration_failed')
        if c['drift']>.2:reasons.append('feature_drift')
    training=score(train)
    if comparisons[-1]['brier']-training['brier']>.1:reasons.append('overfitting_gap')
    regimes={k:score([r for r in hold if r['features']['regime']==k]) for k in sorted({r['features']['regime'] for r in hold})}
    if len(regimes)<2 or any(v['episodes']<12 or v['brier']>=v['baseline_brier'] for v in regimes.values()):reasons.append('regime_robustness_insufficient')
    if len(rows)>=50000:reasons.append('dataset_capacity_requires_review')
    return {**base,'status':'QUALIFIED_SHADOW' if not reasons else 'QUARANTINED','reasons':sorted(set(reasons)),
            'model':model,'comparisons':comparisons,'regimes':regimes,'training':training,
            'holdout_start':hold[0]['observed_at'],'holdout_end':hold[-1]['target']['end_at'],
            'partition_ids':{name:[r['id'] for r in sample] for name,sample in [('train',train),('calibration',cal),('walk',walk),('holdout',hold)]}}


def tick(store: Any,now: str) -> dict[str,Any]:
    rows=independent_rows(store);previous=store.get('market_last_training',{})
    if previous and ((stamp(now)-stamp(previous['at'])).total_seconds()<21600 or len(rows)-previous.get('episodes',0)<CONFIG['min_new_episodes']):
        current: dict[str,Any]=store.get('market_training',{'status':'COLLECTING_NEW_INDEPENDENT_EVIDENCE'})
        return current
    report=evaluate(rows,store.get('market_sealed_holdouts',[]),previous.get('holdout_end'));report['trained_at']=now
    if report.get('holdout_start'):
        identity=store.artifact(report)
        store.set('market_sealed_holdouts',[*store.get('market_sealed_holdouts',[]),[report['holdout_start'],report['holdout_end']]])
        store.set('market_last_training',{'at':now,'episodes':len(rows),'holdout_end':report['holdout_end']})
        if report['status']=='QUALIFIED_SHADOW':store.set('market_challenger',identity)
        report={k:v for k,v in report.items() if k not in {'model','partition_ids'}};report['model_id']=identity
    store.set('market_training',report)
    return report


def status(store: Any,now: str) -> dict[str,Any]:
    identity=store.get('market_challenger');forward=[];drift=[]
    if identity:
        for prediction,result in store.db.execute('SELECT prediction,result FROM market_observations WHERE prediction IS NOT NULL ORDER BY observed_at,id'):
            p=json.loads(prediction)
            if p['model_id']!=identity:continue
            drift.append(p['feature_drift_fraction'])
            if result:
                r=json.loads(result)
                if 'target' in r:forward.append({**r,'prediction':p})
        forward=independent(forward)
    brier=mean((r['prediction']['probability_mid_up']-r['target']['positive'])**2 for r in forward) if forward else None
    drift_mean=mean(drift[-100:]) if drift else None
    if identity and (len(forward)>=24 and (brier is not None and brier>=.25) or len(drift)>=24 and drift_mean is not None and drift_mean>.2):
        store.set('market_quarantine',{'model_id':identity,'at':now,'reason':'forward_calibration_or_feature_drift'})
        store.set('market_challenger',None);identity=None
    return {'counts':dict(store.db.execute('SELECT status,count(*) FROM market_observations GROUP BY status')),
            'independent_episodes':len(independent_rows(store)),'latest_training':store.get('market_training'),
            'active_challenger':identity,'quarantined_challenger':store.get('market_quarantine'),
            'forward_episodes':len(forward),'forward_brier':brier,'feature_drift':drift_mean,
            'evidence_category':'RECORDED_MIDPOINT_PATH_NON_EXECUTABLE','primary_execution_authorized':False}
