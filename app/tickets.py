import re,unicodedata
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from app.errors import DomainError

POLICIES={'ticket':'按维修单修正全部受影响班次','appeals':'仅修正申诉记录'}
ZONE=ZoneInfo('Asia/Shanghai')
MAX_OFFSET=120

def _instant(value,label):
    try:
        d=datetime.fromisoformat(str(value).strip().replace('Z','+00:00'))
        if d.tzinfo is None:raise ValueError()
        return d.astimezone(timezone.utc)
    except (ValueError,AttributeError):raise DomainError('TICKET',label+'必须包含时区')

def parse_ticket(body):
    if not isinstance(body,dict):raise DomainError('TICKET','维修单必须是对象')
    ticket_id=str(body.get('id','')).strip();device=str(body.get('device','')).strip()
    if not ticket_id or not device:raise DomainError('TICKET','维修单号与设备号必填')
    raw_offset=body.get('offset_minutes')
    if isinstance(raw_offset,bool):raise DomainError('TICKET','偏移分钟必须是整数')
    text=unicodedata.normalize('NFKC',str(raw_offset)).strip()
    if not re.fullmatch(r'[+-]?\d+',text):raise DomainError('TICKET','偏移分钟必须是整数')
    offset=int(text)
    if offset==0 or abs(offset)>MAX_OFFSET:raise DomainError('TICKET','偏移分钟必须非零且不超过120')
    start=_instant(body.get('window_start'),'维修单窗口起点');end=_instant(body.get('window_end'),'维修单窗口终点')
    if end<=start:raise DomainError('TICKET','维修单窗口终点必须晚于起点')
    appeals=body.get('appeals',[])
    if not isinstance(appeals,list) or any(not isinstance(a,str) or not a.strip() for a in appeals):
        raise DomainError('TICKET','申诉员工必须是工号列表')
    reason=str(body.get('reason','')).strip()
    if not reason:raise DomainError('TICKET','维修单依据必填')
    return {'id':ticket_id,'device':device,'offset_minutes':offset,
        'window_start':start.isoformat(),'window_end':end.isoformat(),
        'appeals':sorted({a.strip() for a in appeals}),'reason':reason}

def parse_tickets(values):
    if values in (None,''):return []
    if not isinstance(values,list):raise DomainError('TICKET','维修单参数必须是列表')
    tickets=[parse_ticket(v) for v in values]
    seen={}
    for t in tickets:
        if t['id'] in seen and seen[t['id']]!=t:raise DomainError('TICKET_CONFLICT','维修单号重复且内容不同',409)
        seen[t['id']]=t
    return sorted(seen.values(),key=lambda t:t['id'])

def policy(value):
    value=value or 'ticket'
    if value not in POLICIES:raise DomainError('POLICY','校时口径无效')
    return value

def normalise_parameters(parameters):
    """Parse and freeze ticket parameters before any module runs."""
    params=dict(parameters or {})
    params['clock_tickets']=parse_tickets(params.get('clock_tickets'))
    params['correction_policy']=policy(params.get('correction_policy'))
    return params

def covers(ticket,row):
    if str(row.get('device','')).strip()!=ticket['device']:return False
    try:at=datetime.fromisoformat(str(row['at']))
    except (KeyError,ValueError):return False
    if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(ticket['window_start'])<=at<=datetime.fromisoformat(ticket['window_end'])

def local(value):
    return datetime.fromisoformat(value).astimezone(ZONE).isoformat()

def window_label(ticket):
    return local(ticket['window_start'])+'~'+local(ticket['window_end'])

def basis(ticket):
    sign='+' if ticket['offset_minutes']>0 else ''
    return '%s · %s · %s%d 分钟 · %s'%(ticket['id'],ticket['device'],sign,ticket['offset_minutes'],window_label(ticket))
