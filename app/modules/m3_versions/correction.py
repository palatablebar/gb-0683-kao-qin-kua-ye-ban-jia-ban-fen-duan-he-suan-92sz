"""维修单校时：按设备与窗口校正受影响班次，保留原始打卡与校时依据。

裁决口径（默认 `ticket`）：设备偏差是维修单确认的客观事实，受影响班次整体按维修单
修正；申诉只用于标记异议员工，不改变“是否修正”，否则未申诉员工的工资会留下一半
错误、同班进出卡也会一半校正一半未校正。`appeals` 口径仅作对照，须显式选择。

边界：
- 受影响打卡 = 设备号与维修单一致，且设备显示时刻落在维修单窗口内。
- 受影响班次 = 含至少一张受影响打卡的 (employee, shift_day)。
- 班次是修正的最小单位：同班同设备的进出卡一起修正。
- 同班存在窗口外同设备打卡（窗口覆盖不全）或进出卡来自不同设备（单边校正会拆散
  配对）时，整班不自动修正，转人工复核。
- 校时永远从原始打卡重算，不叠加：同一维修单重跑结果不变。
"""
from datetime import datetime,timedelta
from app.errors import DomainError
from app.tickets import covers,basis,policy,local

def _key(row):return (row['employee'],row['shift_day'])

def _plan(state,ticket,chosen):
    rows=state['rows']
    hit=[r for r in rows if covers(ticket,r)]
    plan=[];review=[]
    for key in sorted({_key(r) for r in hit}):
        members=[r for r in rows if _key(r)==key and r.get('punch') in ('IN','OUT')]
        device_rows=[r for r in members if str(r.get('device','')).strip()==ticket['device']]
        outside=[r for r in device_rows if not covers(ticket,r)]
        mixed=[r for r in members if str(r.get('device','')).strip()!=ticket['device']]
        if outside:
            review.append({'employee':key[0],'shift_day':key[1],'rows':[r['id'] for r in outside],
                'code':'WINDOW','detail':'同班同设备存在窗口外打卡，整班转人工'})
            continue
        if mixed:
            review.append({'employee':key[0],'shift_day':key[1],'rows':[r['id'] for r in mixed],
                'code':'MIXED','detail':'同班进出卡来自不同设备，单边校时会拆散配对，整班转人工'})
            continue
        if chosen=='appeals' and key[0] not in ticket['appeals']:continue
        plan.extend(device_rows)
    return plan,review

def _skipped(state,ticket,chosen):
    if chosen!='appeals':return []
    hit=[r for r in state['rows'] if covers(ticket,r)]
    _,review=_plan(state,ticket,chosen)
    manual={(r['employee'],r['shift_day']) for r in review}
    return [{'employee':k[0],'shift_day':k[1],'code':'UNCLAIMED',
             'detail':'设备偏差已确认，员工未申诉，按申诉口径保留原卡'}
            for k in sorted({_key(r) for r in hit}) if k[0] not in ticket['appeals'] and k not in manual]

def _moved_at(ticket,row):
    return (datetime.fromisoformat(row['at'])+timedelta(minutes=ticket['offset_minutes'])).isoformat()

def apply(state):
    parameters=state.get('parameters',{}) or {}
    chosen=policy(parameters.get('correction_policy'))
    tickets=parameters.get('clock_tickets',[]) or []
    seen={}
    for ticket in tickets:
        if ticket['id'] in seen:raise DomainError('TICKET_CONFLICT','维修单重复',409)
        seen[ticket['id']]=ticket
    state['times']={};state['corrections']=[];touched={}
    for ticket in tickets:
        plan,review=_plan(state,ticket,chosen)
        for r in plan:
            if r['id'] in touched:
                raise DomainError('TICKET_CONFLICT','维修单窗口重叠，同一打卡被两张维修单修正，请先合并维修单',409)
            touched[r['id']]=ticket
        state['corrections'].append({**ticket,'policy':chosen,
            'shift_rows':[r['id'] for r in plan],
            'appeal_rows':[r['id'] for r in plan if r['employee'] in ticket['appeals']],
            'skipped_rows':_skipped(state,ticket,chosen),
            'review':review,
            'shift_count':len({_key(r) for r in plan}),
            'appealed_shift_count':len({_key(r) for r in plan if r['employee'] in ticket['appeals']})})
    for r in state['rows']:
        entry={'line':r['_line'],'original_at':r['at'],'used_at':r['at'],'ticket':None,
            'original_local':local(r['at']),'used_local':local(r['at'])}
        ticket=touched.get(r['id'])
        if ticket:
            entry.update(used_at=_moved_at(ticket,r),used_local=local(_moved_at(ticket,r)),ticket=ticket['id'],device=ticket['device'],
                offset_minutes=ticket['offset_minutes'],basis=basis(ticket),reason=ticket['reason'],
                appealed=r['employee'] in ticket['appeals'],
                window_start=ticket['window_start'],window_end=ticket['window_end'],policy=chosen)
            r['at']=entry['used_at']
            if entry['appealed']:r['appeal']=ticket['id']
        state['times'][r['id']]=entry
    corrected=[e for e in state['times'].values() if e['ticket']]
    state['correction_meta']={'policy':chosen,'ticket_count':len(tickets),'corrected_rows':len(corrected),
        'corrected_shifts':len({_key(r) for r in state['rows'] if state['times'][r['id']]['ticket']}),
        'appealed_rows':sum(1 for e in corrected if e['appealed']),
        'unappealed_rows':sum(1 for e in corrected if not e['appealed']),
        'review_shifts':sum(len(t['review']) for t in state['corrections']),
        'unclaimed_shifts':sum(len(t['skipped_rows']) for t in state['corrections']),
        'applied_ticket_ids':[t['id'] for t in state['corrections']]}
    return state

def annotate_shifts(state):
    """Attach per-shift correction evidence used by the pairing screen."""
    times=state.get('times',{})
    for shift in state.get('shifts',[]):
        moved=[]
        for kind in ('in','out'):
            row=shift.get(kind)
            if not row:continue
            entry=times.get(row['id'],{})
            if entry.get('ticket'):
                moved.append({'punch':kind.upper(),'line':row['_line'],'id':row['id'],
                    'employee':row['employee'],'shift_day':row['shift_day'],
                    'original_at':entry['original_at'],'used_at':entry['used_at'],
                    'original_local':local(entry['original_at']),'used_local':local(entry['used_at']),
                    'ticket':entry['ticket'],'basis':entry['basis'],'appealed':entry['appealed']})
        if moved:
            shift['correction']={'ticket':moved[0]['ticket'],'basis':moved[0]['basis'],
                'appealed':all(m['appealed'] for m in moved),'cards':moved}
    return state
