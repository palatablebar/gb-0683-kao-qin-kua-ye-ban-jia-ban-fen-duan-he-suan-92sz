import sqlite3,json,os
from pathlib import Path
from app.errors import DomainError

SCHEMA='CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核")'
VERSIONS='CREATE TABLE IF NOT EXISTS run_versions (id TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL, decision TEXT NOT NULL, PRIMARY KEY(id,version))'

def connection():
    path=Path(os.environ.get('DB_PATH','data/records.db'));path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=10);db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute(SCHEMA);db.execute(VERSIONS)
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    return db

def save(run_id, body):
    with connection() as db:
        db.execute('INSERT OR IGNORE INTO runs(id,body) VALUES (?,?)',(run_id,json.dumps(body,ensure_ascii=False)))
        db.execute("INSERT INTO meta(key,value) VALUES ('latest',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(run_id,))
    return get(run_id)

def get(run_id):
    with connection() as db:r=db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    if not r:raise DomainError('NOT_FOUND','批次不存在',404)
    body=json.loads(r['body']);body.update(run_id=r['id'],review_version=r['version'],decision=r['decision']);return body

def history():
    with connection() as db:rows=db.execute("SELECT id,version,decision FROM runs ORDER BY CASE WHEN id=(SELECT value FROM meta WHERE key='latest') THEN 0 ELSE 1 END,rowid DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]

def review(run_id, version, decision):
    if decision not in ('通过','退回'):raise DomainError('DECISION','复核状态无效')
    with connection() as db:
        cur=db.execute('UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?',(decision,run_id,version))
        if cur.rowcount!=1:
            if not db.execute('SELECT 1 FROM runs WHERE id=?',(run_id,)).fetchone():raise DomainError('NOT_FOUND','批次不存在',404)
            raise DomainError('STALE','复核版本已更新，请刷新',409)
    return get(run_id)

def _body(body):
    return {k:v for k,v in body.items() if k not in ('review_version','decision')}

def _wage_state(body):
    """Deterministic wage result of a batch.

    Identical correction evidence, used times, calculation lines and totals mean
    the same ticket was already applied: resubmitting it must not bump the
    version or apply the offset a second time.
    """
    return {'times':body.get('times'),'corrections':body.get('corrections'),
        'correction_meta':body.get('correction_meta'),'business':body.get('business'),
        'calculations':body.get('calculations')}

def switch(run_id, version, corrected):
    """Atomically replace the batch body with its ticket-corrected version.

    `corrected` is recomputed from the stored original source, so the same
    maintenance ticket always yields the same body. Preconditions: the new body
    must be balanced and its archive checksum must match its own wage evidence.
    The swap and the version bump run in one BEGIN IMMEDIATE transaction; any
    failure rolls back and leaves the old body, version and review state exactly
    as they were.

    Re-running the same ticket produces identical wage evidence, which is
    reported as NOOP instead of bumping the version and rolling the clock twice.
    """
    from app.modules.m7_archive.export_out import checksum
    body=_body({**corrected,'run_id':run_id})
    if not body.get('reconcile',{}).get('balanced'):raise DomainError('UNBALANCED','对账未平，保留旧版')
    if body.get('archive',{}).get('sha256')!=checksum(body):raise DomainError('ARCHIVE','封存证据与工资不一致，保留旧版')
    if not body.get('correction_meta',{}).get('corrected_shifts'):raise DomainError('SWITCH','没有可切换的受影响班次')
    payload=json.dumps(body,ensure_ascii=False)
    with connection() as db:
        try:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT body,version,decision FROM runs WHERE id=?',(run_id,)).fetchone()
            if not current:
                db.rollback();raise DomainError('NOT_FOUND','批次不存在',404)
            if current['version']!=version:
                db.rollback();raise DomainError('STALE','批次版本已更新，请刷新后重试',409)
            old=_body(json.loads(current['body']))
            if _wage_state(old)==_wage_state(body):
                db.rollback();raise DomainError('NOOP','该维修单已生效，未重复回拨',409)
            db.execute('INSERT OR REPLACE INTO run_versions(id,version,body,decision) VALUES (?,?,?,?)',
                (run_id,current['version'],current['body'],current['decision']))
            db.execute('UPDATE runs SET body=?,version=version+1,decision=? WHERE id=? AND version=?',
                (payload,'待复核',run_id,version))
            db.execute('COMMIT')
        except Exception:
            if db.in_transaction:db.rollback()
            raise
    return get(run_id)

def versions(run_id):
    with connection() as db:
        current=db.execute('SELECT body,version,decision FROM runs WHERE id=?',(run_id,)).fetchone()
        if not current:raise DomainError('NOT_FOUND','批次不存在',404)
        rows=db.execute('SELECT version,decision FROM run_versions WHERE id=? ORDER BY version DESC LIMIT 50',(run_id,)).fetchall()
    return [{'version':current['version'],'decision':current['decision'],'current':True}]+[
        {'version':r['version'],'decision':r['decision'],'current':False} for r in rows]
