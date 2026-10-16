from autotrader.shadow.versions import LEGACY_SOURCE, legacy_module
from test_v42_lifecycle import (
    test_actual_experimental_worker_partial_targets_sigkill_restart_and_official_api as actual_lifecycle,
)


async def test_four_original_accounts_survive_upgrade_and_legacy_partial_exit_worker_restart(lab,tmp_path,monkeypatch):
    original = legacy_module('persistence.repository').PersistentTradingRepository(lab.official.session_factory)
    original.test_database_url = lab.official.test_database_url
    old_lab = legacy_module('shadow.lab').ShadowLab(original,lab.settings)
    try:
        manifests={}
        for i in range(3):
            record=await old_lab.create('old-b2-'+str(i),'Frozen B2 '+str(i),'B2_CONFIRMED_COMPRESSION')
            manifests[record['experiment_id']]=record['manifest']
            if i:
                await old_lab.control(record['experiment_id'],'stop')
        await actual_lifecycle(old_lab,tmp_path,monkeypatch)
        records=await lab.records()
        assert len(records)==4
        assert all(r['manifest']['source_fingerprint']==LEGACY_SOURCE for r in records)
        assert all(r['manifest']==manifests[r['experiment_id']] for r in records if r['experiment_id'] in manifests)
        assert len([r for r in records if r['state']=='STOPPED'])==2
        for record in records:
            detail=await lab.detail(record['experiment_id'])
            assert detail['runtime_compatibility']=={'compatible':True,'runner':'verified-v42','reason':None}
            assert detail['reconciliation']==[]
    finally:
        await old_lab.close()
