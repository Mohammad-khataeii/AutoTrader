"""Audit exports must stream rows and never aggregate trading history in PostgreSQL."""
import gzip
import io
import json
from pathlib import Path

import pytest


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('scripts').resolve()))
    import v491_diagnostic_remote
    return v491_diagnostic_remote


def test_row_stream_yields_before_reading_next_and_closes_abandoned_query(collector,monkeypatch):
    events=[];commands=[]
    class Rows:
        def __iter__(self):
            events.append('first');yield b'{"price":0.000004123456789123}\n'
            events.append('second');yield b'{"price":2}\n'
        def close(self):events.append('stdout_closed')
    class Process:
        stdout=Rows();stderr=io.BytesIO();done=False
        def poll(self):return 0 if self.done else None
        def terminate(self):self.done=True;events.append('terminated')
        def wait(self,timeout=None):self.done=True;return 0
    monkeypatch.setattr(collector.subprocess,'Popen',lambda command,**kw:(commands.append(command) or Process()))
    g=collector.stream_query('local-owned-test','autotrader_paper_'+'a'*32,'SELECT row_to_json(t) FROM audit_probe t')
    assert next(g)['price']=='0.000004123456789123'
    assert events==['first']
    g.close();assert 'second' not in events and 'terminated' in events and 'stdout_closed' in events
    sql=commands[0][-1];assert 'REPEATABLE READ READ ONLY' in sql and "work_mem='2MB'" in sql and 'json_agg' not in sql


def test_wrong_project_database_cannot_be_queried(collector):
    with pytest.raises(AssertionError):next(collector.stream_query('irrelevant','autotrader','SELECT 1'))


def test_new_stream_export_scope_byte_omissions_and_cutoff(collector,monkeypatch):
    commands=[]
    registry={'primary':{'database_name':'autotrader_paper_'+'a'*32},'shadows':[]}
    monkeypatch.setattr(collector.subprocess,'check_output',lambda *a,**kw:b'abcdef123\n')
    def query(pg,name,sql):
        commands.append(sql)
        if len(commands)==1:yield registry;return
        yield {'section':'states','row':{'key':'paper_scan','payload_json':'{"payload_omitted":true,"bytes":400000}'}}
    monkeypatch.setattr(collector,'stream_query',query)
    output=io.BytesIO();collector.collect(12,output)
    rows=[json.loads(l) for l in gzip.decompress(output.getvalue()).splitlines()]
    assert rows[0]['project']=='autotrader-aruba-test' and rows[0]['read_only'] and rows[-1]['status']=='PASS'
    assert len(rows[-1]['counts'])==2 and rows[1]['row']['payload_json']['payload_omitted']
    for sql in commands[1:]:
        assert 'json_agg(t) FROM (SELECT created_at' not in sql
        assert 'octet_length(payload_json)<=262144' in sql and 'CASE WHEN' in sql
        assert rows[0]['since'] in sql and rows[0]['until'] in sql


def test_old_aggregate_disabled_before_any_database_read(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('scripts').resolve()))
    import v49_diagnostic_remote as old
    monkeypatch.setattr(old,'run',lambda *a:pytest.fail('unsafe collector reached SQL'))
    with pytest.raises(RuntimeError,match='aggregate export disabled'):old.collect(12)


def test_partial_export_is_not_a_pass_and_redaction_is_preserved(collector,tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path('scripts').resolve()))
    from v491_diagnostics import summarize
    p=tmp_path/'partial.gz';p.write_bytes(gzip.compress(b'{"type":"header","project":"autotrader-aruba-test","read_only":true}\n'))
    with pytest.raises(ValueError,match='incomplete'):summarize(p)
    assert collector.sanitize({'password':'secret','url':'postgresql://user:secret@host/db'})=={'password':'[REDACTED]','url':'postgresql://[REDACTED]@host/db'}
