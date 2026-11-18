import base64
import pytest
from app import store
from app.errors import DomainError
from app.modules.m7_archive.export_out import bundle,checksum
from app.workflow import load,run

TICKET={'id':'WX-1001','device':'CLK-01','offset_minutes':-17,
    'window_start':'2026-10-01T21:30:00+08:00','window_end':'2026-10-02T06:30:00+08:00',
    'reason':'维修单确认设备快17分钟','appeals':['E001','E002']}

@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'switch.db'));return tmp_path

def corrected(run_id, policy='ticket'):
    state=run(load('clock.csv'),{'clock_tickets':[TICKET],'correction_policy':policy})
    state['run_id']=run_id;state['archive']['sha256']=checksum(state);return state

def seed(db):
    state=run(load('clock.csv'),{});store.save(state['run_id'],state);return state

def test_switch_replaces_body_and_bumps_version(db):
    state=seed(db);new=store.switch(state['run_id'],1,corrected(state['run_id']))
    assert new['review_version']==2 and new['decision']=='待复核'
    assert new['business']['total']==corrected(state['run_id'])['business']['total']
    assert new['times']['00001']['used_at']=='2026-10-01T14:00:00+00:00'
    assert store.get(state['run_id'])['archive']['sha256']==checksum(store.get(state['run_id']))

def test_switch_keeps_old_version_available(db):
    state=seed(db);old=store.get(state['run_id'])
    store.switch(state['run_id'],1,corrected(state['run_id']))
    history=store.versions(state['run_id'])
    assert [h['version'] for h in history]==[2,1]
    assert history[1]['current'] is False
    assert old['business']['total']=='3756.06'

def test_stale_version_keeps_old_body(db):
    state=seed(db)
    store.switch(state['run_id'],1,corrected(state['run_id']))
    with pytest.raises(DomainError) as e:store.switch(state['run_id'],1,corrected(state['run_id']))
    assert e.value.code=='STALE'
    current=store.get(state['run_id'])
    assert current['review_version']==2 and current['times']['00001']['used_at']=='2026-10-01T14:00:00+00:00'

def test_replay_same_ticket_is_noop_not_second_rollback(db):
    state=seed(db);store.switch(state['run_id'],1,corrected(state['run_id']))
    with pytest.raises(DomainError) as e:store.switch(state['run_id'],2,corrected(state['run_id']))
    assert e.value.code=='NOOP'
    current=store.get(state['run_id'])
    assert current['review_version']==2
    assert current['times']['00001']['used_at']=='2026-10-01T14:00:00+00:00'

def test_failed_precondition_leaves_old_batch_intact(db):
    state=seed(db);before=store.get(state['run_id'])
    broken=corrected(state['run_id']);broken['calculations'][0]['amount']='0.00'
    with pytest.raises(DomainError) as e:store.switch(state['run_id'],1,broken)
    assert e.value.code=='ARCHIVE'
    after=store.get(state['run_id'])
    assert after['review_version']==before['review_version']==1
    assert after['business']==before['business'] and after['times']==before['times']

def test_switch_requires_affected_shifts(db):
    state=seed(db)
    ticket=dict(TICKET,window_start='2026-10-05T00:00:00+08:00',window_end='2026-10-05T08:00:00+08:00')
    empty=run(load('clock.csv'),{'clock_tickets':[ticket]});empty['run_id']=state['run_id']
    empty['archive']['sha256']=checksum(empty)
    with pytest.raises(DomainError) as e:store.switch(state['run_id'],1,empty)
    assert e.value.code=='SWITCH' and store.get(state['run_id'])['review_version']==1

def test_review_blocked_on_stale_version_after_switch(db):
    state=seed(db);store.switch(state['run_id'],1,corrected(state['run_id']))
    with pytest.raises(DomainError) as e:store.review(state['run_id'],1,'通过')
    assert e.value.status==409 and e.value.code=='STALE'
    assert store.review(state['run_id'],2,'通过')['review_version']==3

def test_failed_transaction_rolls_back(db,monkeypatch):
    state=seed(db);before=store.get(state['run_id'])
    target=corrected(state['run_id'])
    class Boom(Exception):pass
    real_connection=store.connection
    class FailingConnection:
        def __init__(self,inner):self.inner=inner;self.armed=False
        def __enter__(self):return self
        def __exit__(self,*exc):
            self.inner.__exit__(*exc);return False
        def execute(self,sql,*args):
            if sql.startswith('UPDATE runs SET body'):
                self.armed=True;return self.inner.execute(sql,*args)
            if self.armed and sql=='COMMIT':raise Boom('disk full')
            return self.inner.execute(sql,*args)
        def rollback(self):self.inner.rollback()
        def __getattr__(self,name):return getattr(self.inner,name)
    monkeypatch.setattr(store,'connection',lambda: FailingConnection(real_connection()))
    with pytest.raises(Boom):store.switch(state['run_id'],1,target)
    monkeypatch.setattr(store,'connection',real_connection)
    after=store.get(state['run_id'])
    assert after['review_version']==before['review_version']==1
    assert after['business']==before['business'] and after['times']==before['times']

def test_two_tickets_apply_sequentially_without_stacking(db):
    import csv,io
    header=['id','employee','shift_day','version','punch','device','at','shift_start','shift_end','break_start','break_end','hourly_rate','paid','note']
    rows=[['1','E1','2026-10-01','1','IN','CLK-01','2026-10-01T22:17:00+08:00','22:00','06:00','02:00','03:00','20','220','a'],
        ['2','E1','2026-10-01','1','OUT','CLK-01','2026-10-02T06:17:00+08:00','22:00','06:00','02:00','03:00','20','0','a'],
        ['3','E2','2026-10-02','1','IN','CLK-09','2026-10-02T22:05:00+08:00','22:00','06:00','02:00','03:00','20','220','b'],
        ['4','E2','2026-10-02','1','OUT','CLK-09','2026-10-03T06:05:00+08:00','22:00','06:00','02:00','03:00','20','0','b']]
    buffer=io.StringIO(newline='');writer=csv.writer(buffer,lineterminator='\n');writer.writerow(header);writer.writerows(rows)
    source=buffer.getvalue().encode()
    base=run(source,{});store.save(base['run_id'],base)
    one={'id':'WX-1','device':'CLK-01','offset_minutes':-17,'window_start':'2026-10-01T21:30:00+08:00','window_end':'2026-10-02T06:30:00+08:00','reason':'r1','appeals':[]}
    two={'id':'WX-2','device':'CLK-09','offset_minutes':-5,'window_start':'2026-10-02T21:30:00+08:00','window_end':'2026-10-03T06:30:00+08:00','reason':'r2','appeals':[]}
    def build(tickets):
        state=run(source,{'clock_tickets':tickets});state['run_id']=base['run_id']
        state['archive']['sha256']=checksum(state);return state
    store.switch(base['run_id'],1,build([one]))
    # The caller supplies the full ticket set, as the corrections endpoint does.
    final=store.switch(base['run_id'],2,build([one,two]))
    assert final['times']['1']['used_at']=='2026-10-01T14:00:00+00:00'
    assert final['times']['3']['used_at']=='2026-10-02T14:00:00+00:00'
    assert final['correction_meta']['applied_ticket_ids']==['WX-1','WX-2']
    assert final['times']['1']['ticket']=='WX-1' and final['times']['3']['ticket']=='WX-2'
