import base64
from flask import request,render_template,jsonify
from app.errors import DomainError
from app.config import TITLE,MODULES,SHORT
from app.workflow import run,load
from app import store

def payload():
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):raise DomainError('PAYLOAD','请求必须是对象')
    if 'csv' in data and not isinstance(data['csv'],str):raise DomainError('CSV','CSV内容必须是文本')
    sample=data.get('sample',request.args.get('sample','dirty.csv'))
    content=data.get('csv')
    return (content.encode() if isinstance(content,str) else load(sample)),data.get('parameters',{})

def api(stage):
    content,parameters=payload();return jsonify(run(content,parameters,stage))

def page(stage,template):
    latest=store.history();state=store.get(latest[0]['id']) if latest else run(load('dirty.csv'),{})
    source=load(request.args['sample']) if 'sample' in request.args else base64.b64decode(state['source_b64']) if state.get('source_b64') else load('dirty.csv')
    parameters=state.get('manifest',{}).get('parameters',{})
    data=run(source,parameters,stage)
    evidence={'times':data.get('times',{}),'correction_meta':data.get('correction_meta',{}),'corrections':data.get('corrections',[])}
    if stage<3:
        # M1/M2 show machine-stamped cards; the full run supplies the applied correction for comparison.
        try:
            full=run(source,parameters)
            evidence={'times':full.get('times',{}),'correction_meta':full.get('correction_meta',{}),'corrections':full.get('corrections',[])}
        except DomainError:pass
    data['evidence']=evidence
    return render_template(template,title=TITLE,short=SHORT,modules=MODULES,current=stage,data=data,run=state,history=latest)
