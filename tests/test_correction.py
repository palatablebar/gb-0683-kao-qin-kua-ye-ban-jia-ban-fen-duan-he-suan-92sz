import json
import pytest
from app.errors import DomainError
from app.tickets import parse_ticket,parse_tickets,normalise_parameters
from app.workflow import load,run

def ticket(**overrides):
    base={'id':'WX-1001','device':'CLK-01','offset_minutes':-17,
        'window_start':'2026-10-01T21:30:00+08:00','window_end':'2026-10-02T06:30:00+08:00',
        'reason':'维修单确认设备快17分钟','appeals':['E001','E002']}
    base.update(overrides);return parse_ticket(base)

def test_ticket_requires_reason():
    with pytest.raises(DomainError) as e:parse_ticket({'id':'W','device':'D','offset_minutes':-17,'window_start':'2026-10-01T00:00:00+08:00','window_end':'2026-10-02T00:00:00+08:00'})
    assert e.value.code=='TICKET'

def test_ticket_offset_must_be_integer_minutes():
    for value in (0,17.5,True,'十七',121):
        with pytest.raises(DomainError):ticket(offset_minutes=value)

def test_ticket_window_needs_timezone():
    with pytest.raises(DomainError):ticket(window_start='2026-10-01T21:30:00')
    with pytest.raises(DomainError):ticket(window_end='2026-10-01T20:00:00+08:00')

def test_ticket_ids_unique_and_stable():
    one=ticket();two=parse_tickets([ticket(),json.loads(json.dumps(one))])
    assert len(two)==1
    with pytest.raises(DomainError) as e:parse_tickets([ticket(),ticket(offset_minutes=-5)])
    assert e.value.code=='TICKET_CONFLICT'

def test_policy_defaults_to_whole_shift():
    params=normalise_parameters({'clock_tickets':[ticket()]})
    assert params['correction_policy']=='ticket'
    with pytest.raises(DomainError):normalise_parameters({'correction_policy':'partial'})

def test_whole_shift_policy_corrects_unappealed_but_keeps_original():
    state=run(load('clock.csv'),{'clock_tickets':[ticket()]})
    times=state['times']['00005']  # E003 never appealed
    assert times['appealed'] is False
    assert times['original_at']=='2026-10-01T14:17:00+00:00'
    assert times['used_at']=='2026-10-01T14:00:00+00:00'
    assert times['ticket']=='WX-1001' and times['basis'].startswith('WX-1001 · CLK-01 · -17 分钟')
    assert times['reason']=='维修单确认设备快17分钟'

def test_appeals_policy_leaves_unappealed_pay_untouched():
    state=run(load('clock.csv'),{'clock_tickets':[ticket()],'correction_policy':'appeals'})
    assert state['times']['00005']['used_at']==state['times']['00005']['original_at']
    assert state['times']['00001']['used_at']=='2026-10-01T14:00:00+00:00'
    assert state['correction_meta']['unclaimed_shifts']==15

def test_both_policies_keep_in_out_pairs_together():
    for policy in ('ticket','appeals'):
        state=run(load('clock.csv'),{'clock_tickets':[ticket()],'correction_policy':policy})
        for shift in state['shifts']:
            cards=shift.get('correction',{}).get('cards',[])
            assert len(cards) in (0,2),shift['employee']
            if cards:assert {c['punch'] for c in cards}=={'IN','OUT'}

def test_mixed_device_shift_goes_to_manual_review():
    state=run(load('clock.csv'),{'clock_tickets':[ticket()]})
    review=[r for c in state['corrections'] for r in c['review']]
    assert [(r['employee'],r['code']) for r in review]==[('E018','MIXED')]
    assert 'E018' not in {s['employee'] for s in state['shifts'] if s.get('correction')}

def test_partial_window_coverage_is_not_half_corrected():
    params={'clock_tickets':[ticket(window_end='2026-10-02T00:00:00+08:00')]}
    state=run(load('clock.csv'),params)
    review=[r for c in state['corrections'] for r in c['review']]
    assert {r['code'] for r in review}=={'WINDOW','MIXED'}
    assert state['correction_meta']['corrected_shifts']==0

def test_rerun_same_ticket_does_not_stack_offset():
    params={'clock_tickets':[ticket()]}
    first=run(load('clock.csv'),params);second=run(load('clock.csv'),params)
    assert first['times']==second['times']
    assert second['times']['00001']['used_at']=='2026-10-01T14:00:00+00:00'

def test_two_tickets_with_overlap_rejected():
    with pytest.raises(DomainError) as e:
        run(load('clock.csv'),{'clock_tickets':[ticket(),ticket(id='WX-1002')]})
    assert e.value.code=='TICKET_CONFLICT'

def test_correction_recomputes_wages_and_evidence():
    plain=run(load('clock.csv'),{})
    fixed=run(load('clock.csv'),{'clock_tickets':[ticket()]})
    assert fixed['business']['total']!=plain['business']['total']
    assert fixed['business']['minutes']==plain['business']['minutes']==7560
    assert all(r['ticket']=='WX-1001' for r in fixed['calculations'] if r['id']!='E018/2026-10-01')

def test_ticket_outside_any_window_changes_nothing():
    plain=run(load('clean.csv'),{})
    same=run(load('clean.csv'),{'clock_tickets':[ticket(window_start='2026-10-05T00:00:00+08:00',window_end='2026-10-05T08:00:00+08:00')]})
    assert same['business']==plain['business'] and same['correction_meta']['corrected_shifts']==0

def test_missing_device_column_changes_nothing():
    # CSVs predating the device column must not be corrected by a device ticket.
    import csv,io
    rows=list(csv.reader(io.StringIO(load('clock.csv').decode('utf-8-sig'),newline='')))
    header=rows[0];drop=header.index('device')
    out=[header[:drop]+header[drop+1:]]+[[v for i,v in enumerate(r) if i!=drop] for r in rows[1:] if len(r)==len(header)]
    buffer=io.StringIO(newline='');csv.writer(buffer,lineterminator='\n').writerows(out)
    state=run(buffer.getvalue().encode(),{'clock_tickets':[ticket()]})
    assert state['correction_meta']['corrected_shifts']==0
    assert all(e['ticket'] is None for e in state['times'].values())
