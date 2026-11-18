from app.config import MODULES

def test_all_module_apis(client):
    for mod,_ in MODULES:assert client.get('/api/'+mod).status_code==200
def test_all_module_pages(client):
    for mod,_ in MODULES:assert client.get('/'+mod).status_code==200
def test_run_and_export(client):
    r=client.post('/api/runs',json={'sample':'dirty.csv'});assert r.status_code==200
    s=r.get_json();e=client.get('/api/archive/'+s['run_id']+'/export.csv');assert e.status_code==200 and '运行清单' in e.data.decode('utf-8-sig')
def test_idempotent_api(client):
    a=client.post('/api/runs',json={}).get_json();b=client.post('/api/runs',json={}).get_json()
    assert a['run_id']==b['run_id'] and len(client.get('/api/runs').get_json())==1
def test_bad_sample(client):
    r=client.post('/api/runs',json={'sample':'../x'});assert r.status_code==422 and r.get_json()['code']=='SAMPLE'
def test_missing_batch(client):
    assert client.get('/api/runs/absent').status_code==404
def test_bad_file(client):
    r=client.post('/api/runs',json={'csv':'wrong\n1\n'});assert r.status_code==422 and r.get_json()['code']=='HEADER'


def test_custom_source_is_visible_after_run(client):
    from app.workflow import load
    raw=load('clean.csv').decode('utf-8-sig');submitted=client.post('/api/runs',json={'csv':raw,'parameters':{}}).get_json()
    from app.config import MODULES
    page=client.get('/'+MODULES[0][0]);assert submitted['run_id'] in page.data.decode()

def test_reselect_existing_run_updates_visible_batch(client):
    a=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json();b=client.post('/api/runs',json={'sample':'clean.csv'}).get_json();client.post('/api/runs',json={'sample':'dirty.csv'})
    assert client.get('/api/runs').get_json()[0]['id']==a['run_id'] and a['run_id']!=b['run_id']

def test_invalid_csv_type_rejected(client):
    assert client.post('/api/runs',json={'csv':123}).status_code==422

TICKET={'id':'WX-1001','device':'CLK-01','offset_minutes':-17,
    'window_start':'2026-10-01T21:30:00+08:00','window_end':'2026-10-02T06:30:00+08:00',
    'reason':'维修单确认设备快17分钟','appeals':['E001','E002']}

def test_correction_api_switches_visible_batch(client):
    base=client.post('/api/runs',json={'sample':'clock.csv'}).get_json()
    response=client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':1,'clock_tickets':[TICKET]})
    assert response.status_code==200
    corrected=response.get_json()
    assert corrected['review_version']==2 and corrected['business']['total']!=base['business']['total']
    assert client.get('/api/runs').get_json()[0]['version']==2

def test_correction_api_replay_is_rejected(client):
    base=client.post('/api/runs',json={'sample':'clock.csv'}).get_json()
    client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':1,'clock_tickets':[TICKET]})
    again=client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':2,'clock_tickets':[TICKET]})
    assert again.status_code==409 and again.get_json()['code']=='NOOP'
    assert client.get('/api/runs/'+base['run_id']).get_json()['review_version']==2

def test_correction_api_bad_ticket_keeps_old(client):
    base=client.post('/api/runs',json={'sample':'clock.csv'}).get_json()
    bad=dict(TICKET,offset_minutes=0)
    response=client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':1,'clock_tickets':[bad]})
    assert response.status_code==422 and client.get('/api/runs/'+base['run_id']).get_json()['review_version']==1

def test_correction_api_requires_current_version(client):
    base=client.post('/api/runs',json={'sample':'clock.csv'}).get_json()
    response=client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':9,'clock_tickets':[TICKET]})
    assert response.status_code==409 and response.get_json()['code']=='STALE'

def test_corrected_batch_exports_evidence(client):
    base=client.post('/api/runs',json={'sample':'clock.csv'}).get_json()
    client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':1,'clock_tickets':[TICKET]})
    export=client.get('/api/archive/'+base['run_id']+'/export.csv').data.decode('utf-8-sig')
    assert '校时口径' in export and '维修单' in export and 'WX-1001' in export
    assert '00001' in export and '2026-10-01T14:00:00+00:00' in export

def test_pages_show_correction_basis(client):
    base=client.post('/api/runs',json={'sample':'clock.csv'}).get_json()
    client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':1,'clock_tickets':[TICKET]})
    for mod in ('m1_ingest','m3_versions','m4_segments','m5_calculate','m7_archive'):
        page=client.get('/'+mod).data.decode()
        assert 'WX-1001' in page,mod
        assert '维修单确认设备快17分钟' in page or '校时' in page,mod

def test_rerun_verifies_without_overwriting(client):
    base=client.post('/api/runs',json={'sample':'clock.csv'}).get_json()
    client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':1,'clock_tickets':[TICKET]})
    before=client.get('/api/runs/'+base['run_id']).get_json()
    response=client.post('/api/runs/'+base['run_id']+'/rerun')
    assert response.status_code==200
    after=client.get('/api/runs/'+base['run_id']).get_json()
    assert after['review_version']==before['review_version'] and after['business']==before['business']
    assert after['times']==before['times']

def test_correction_api_rejects_changed_ticket_under_same_id(client):
    base=client.post('/api/runs',json={'sample':'clock.csv'}).get_json()
    client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':1,'clock_tickets':[TICKET]})
    changed=dict(TICKET,offset_minutes=-30)
    response=client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':2,'clock_tickets':[changed]})
    assert response.status_code==409 and response.get_json()['code']=='TICKET_CONFLICT'
    current=client.get('/api/runs/'+base['run_id']).get_json()
    assert current['review_version']==2 and current['times']['00001']['offset_minutes']==-17

def test_correction_api_rejects_ticket_hitting_no_shift(client):
    base=client.post('/api/runs',json={'sample':'clock.csv'}).get_json()
    miss=dict(TICKET,id='WX-2002',device='CLK-99')
    response=client.post('/api/runs/'+base['run_id']+'/corrections',json={'version':1,'clock_tickets':[miss]})
    assert response.status_code==422 and response.get_json()['code']=='TICKET'
    assert client.get('/api/runs/'+base['run_id']).get_json()['review_version']==1
