import io,csv,json,hashlib

def bundle(state):
    out=io.StringIO(newline='');writer=csv.writer(out)
    writer.writerow(['记录类型','批次','来源行','业务ID','原因码','内容'])
    rid=state.get('run_id','preview')
    writer.writerow(['运行清单',rid,'','','',json.dumps(state.get('manifest',{}),ensure_ascii=False,sort_keys=True)])
    writer.writerow(['对账',rid,'','','',json.dumps(state.get('reconcile',{}),ensure_ascii=False,sort_keys=True)])
    writer.writerow(['校时口径',rid,'','','',json.dumps(state.get('correction_meta',{}),ensure_ascii=False,sort_keys=True)])
    for ticket in state.get('corrections',[]):
        writer.writerow(['维修单',rid,'','','',json.dumps(ticket,ensure_ascii=False,sort_keys=True)])
    for row in state.get('calculations',[]):
        writer.writerow(['计算',rid,row.get('line',''),row.get('id',''),row.get('code',''),json.dumps(row,ensure_ascii=False,sort_keys=True)])
    for line,evidence in sorted(state.get('times',{}).items(),key=lambda kv:kv[1].get('original_at','')):
        if not evidence.get('ticket'):continue
        writer.writerow(['校时',rid,evidence.get('line',''),line,'TICKET',
            json.dumps(evidence,ensure_ascii=False,sort_keys=True)])
    for row in state['quarantine']:writer.writerow(['隔离',rid,row['line'],row.get('id',''),row['code'],json.dumps(row.get('raw',{}),ensure_ascii=False,sort_keys=True)])
    return '﻿'+out.getvalue()

def checksum(state):
    return hashlib.sha256(bundle(state).encode('utf-8')).hexdigest()
