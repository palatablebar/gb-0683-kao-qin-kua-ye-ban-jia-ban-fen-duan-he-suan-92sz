from app.modules.m1_ingest.reader import read
from app.tickets import policy,local

def execute(content, parameters=None):
    state=read(content);state['parameters']=parameters or {}
    chosen=policy(state['parameters'].get('correction_policy'))
    state['times']={row['id']:{'line':row['_line'],'original_at':row['at'],'used_at':row['at'],'ticket':None,
        'original_local':local(row['at']),'used_local':local(row['at'])} for row in state['rows']}
    state['corrections']=[];state['correction_meta']={'policy':chosen,'ticket_count':0,'corrected_rows':0,
        'corrected_shifts':0,'appealed_rows':0,'unappealed_rows':0,'review_shifts':0,'unclaimed_shifts':0,'applied_ticket_ids':[]}
    return state
