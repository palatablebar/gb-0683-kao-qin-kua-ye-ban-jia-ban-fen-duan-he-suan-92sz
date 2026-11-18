import base64,importlib,os
from flask import Flask,jsonify,request,redirect,Response
from app.config import MODULES
from app.errors import DomainError
from app.workflow import run,load
from app import store
from app.web import payload
from app.modules.m7_archive.export_out import bundle

def create_app():
    app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=2_000_000
    for entry in MODULES:app.register_blueprint(importlib.import_module('app.modules.'+entry[0]+'.handler').bp)
    @app.errorhandler(DomainError)
    def domain_error(error):return jsonify(code=error.code,message=error.message),error.status
    @app.errorhandler(404)
    def missing(error):return jsonify(code='NOT_FOUND',message='入口不存在'),404
    @app.get('/')
    def index():return redirect('/'+MODULES[0][0])
    @app.get('/healthz')
    def health():return jsonify(status='ok')
    @app.post('/api/runs')
    def submit():
        content,params=payload();state=run(content,params);return jsonify(store.save(state['run_id'],state))
    @app.get('/api/runs')
    def list_runs():return jsonify(store.history())
    @app.get('/api/runs/<run_id>')
    def get_run(run_id):return jsonify(store.get(run_id))
    @app.post('/api/runs/<run_id>/review')
    def review(run_id):
        data=request.get_json(silent=True) or {}
        if not isinstance(data.get('version'),int):raise DomainError('VERSION','请提交复核版本')
        return jsonify(store.review(run_id,data['version'],data.get('decision')))
    @app.post('/api/runs/<run_id>/corrections')
    def corrections(run_id):
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):raise DomainError('PAYLOAD','请求必须是对象')
        if not isinstance(data.get('version'),int):raise DomainError('VERSION','请提交批次版本')
        stored=store.get(run_id)
        source=base64.b64decode(stored['source_b64'])
        base=dict(stored.get('manifest',{}).get('parameters',{}) or {})
        stored_ids={t['id'] for t in stored.get('corrections',[])}
        existing={t['id']:t for t in stored.get('corrections',[])}
        # Drop tickets whose base copy is older than the applied one; the stored order is authoritative.
        tickets={t['id']:t for t in base.get('clock_tickets',[]) or [] if t['id'] not in existing}
        tickets.update({t['id']:t for t in stored.get('corrections',[])})
        supplied=[]
        for ticket in data.get('clock_tickets',[]) or []:
            if not isinstance(ticket,dict):raise DomainError('TICKET','维修单必须是对象')
            ticket_id=str(ticket.get('id','')).strip();supplied.append(ticket_id)
            before=existing.get(ticket_id)
            if before:
                from app.tickets import parse_ticket
                after=parse_ticket(ticket)
                if any(str(after[k])!=str(before[k]) for k in ('device','offset_minutes','window_start','window_end','reason','appeals')):
                    raise DomainError('TICKET_CONFLICT','维修单号已存在且内容不同，请以新单号登记修订',409)
            tickets[ticket_id]=ticket
        base['clock_tickets']=list(tickets.values())
        if 'correction_policy' in data:base['correction_policy']=data['correction_policy']
        corrected=run(source,base)
        corrected['run_id']=run_id
        from app.modules.m7_archive.export_out import checksum
        corrected['archive']['sha256']=checksum(corrected)
        fresh=[c for c in corrected['corrections'] if c['id'] in supplied and c['id'] not in stored_ids]
        if fresh and not any(c['shift_count'] for c in fresh):
            raise DomainError('TICKET','维修单未命中任何受影响班次，保留旧版')
        return jsonify(store.switch(run_id,data['version'],corrected))
    @app.post('/api/runs/<run_id>/rerun')
    def rerun(run_id):
        """Recompute from the stored source; never silently overwrite sealed evidence."""
        stored=store.get(run_id)
        source=base64.b64decode(stored['source_b64'])
        params=stored.get('manifest',{}).get('parameters',{}) or {}
        state=run(source,params)
        if store._wage_state(state)!=store._wage_state(stored) or state.get('reconcile')!=stored.get('reconcile'):
            raise DomainError('ARCHIVE','重算结果与封存证据不一致，保留旧版',409)
        return jsonify(stored)
    @app.get('/api/runs/<run_id>/versions')
    def versions(run_id):return jsonify(store.versions(run_id))
    @app.get('/api/archive/<run_id>/export.csv')
    def download(run_id):
        state=store.get(run_id)
        if not state.get('reconcile',{}).get('balanced'):raise DomainError('UNBALANCED','对账未平')
        return Response(bundle(state),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=evidence.csv'})
    with app.app_context():
        if not store.history():
            state=run(load('dirty.csv'),{});store.save(state['run_id'],state)
    return app

app=create_app()
if __name__=='__main__':app.run(host='0.0.0.0',port=8000)
