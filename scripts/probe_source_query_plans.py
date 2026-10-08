"""Design-only SQLite probe on synthetic in-memory rows; imports no Bot modules."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time
from types import ModuleType, SimpleNamespace


def probe_encoded_bigrams(conn):
    """Capability/codec example only; no production index or lifecycle wiring."""
    ascii_lower = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')

    def tokens(text):
        normalized = text.translate(ascii_lower)
        return sorted({f'g{ord(a):06x}{ord(b):06x}' for a, b in zip(normalized, normalized[1:])})

    texts = ['浅紫色胖次', '桌上的赤陶杯', 'AbC', 'Äpfel', 'Straße', '胖 次', '👗紫色', '标记 *?']
    # Keep the failed parameter combination as a design finding.
    try:
        conn.execute("CREATE VIRTUAL TABLE probe_grams_invalid USING fts5(tokens,content='',contentless_delete=1,detail=none,columnsize=0,tokenize='unicode61')")
        invalid_combination = 'supported_on_this_sqlite'
    except sqlite3.OperationalError as exc:
        invalid_combination = str(exc)
    conn.execute("CREATE VIRTUAL TABLE probe_grams USING fts5(tokens,content='',contentless_delete=1,detail=none,tokenize='unicode61')")
    conn.executemany('INSERT INTO probe_grams(rowid,tokens) VALUES(?,?)',
                     [(i, ' '.join(tokens(text))) for i, text in enumerate(texts, 1)])
    cases = []
    for term in ['胖次', '陶杯', 'ab', 'Äp', 'äP', 'ßE', '👗紫', '*?']:
        token = tokens(term)
        assert len(token) == 1
        candidates = [r[0] for r in conn.execute('SELECT rowid FROM probe_grams WHERE probe_grams MATCH ?', ('"' + token[0] + '"',))]
        expected = [i for i, text in enumerate(texts, 1)
                    if conn.execute('SELECT instr(lower(?),lower(?))>0', (text, term)).fetchone()[0]]
        assert candidates == expected, (term, candidates, expected)
        cases.append({'term':term, 'expected':expected, 'candidate_ids':candidates})
    conn.execute('DELETE FROM probe_grams WHERE rowid=1')
    assert not conn.execute('SELECT rowid FROM probe_grams WHERE probe_grams MATCH ?', ('"'+tokens('胖次')[0]+'"',)).fetchall()
    conn.execute('INSERT INTO probe_grams(rowid,tokens) VALUES(?,?)',(1,' '.join(tokens('白色裙子'))))
    assert conn.execute('SELECT rowid FROM probe_grams WHERE probe_grams MATCH ?', ('"'+tokens('裙子')[0]+'"',)).fetchall() == [(1,)]
    return {'capability':'FTS5 unicode61 + contentless_delete; default columnsize=1', 'sources':len(texts), 'cases':cases,
            'rejected_parameter_combination':invalid_combination,
            'delete_and_reinsert':'passed', 'limitation':'small SQL codec/capability probe; no rebuild, concurrency, service or performance acceptance'}

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, help='Optional report path; omit to print only')
cli_options = parser.parse_args()

# Load the actual source_partition helper without constructing or importing a Bot.
pkg = ModuleType('c2b_probe_core')
pkg.__path__ = [str(ROOT / 'core')]
sys.modules[pkg.__name__] = pkg
models = ModuleType('c2b_probe_core.models')
models.clean_text = lambda value, limit: str(value or '').strip()[:limit]
models.stable_fingerprint = lambda *values: 'unused'
sys.modules[models.__name__] = models
evidence = ModuleType('c2b_probe_core.source_evidence')
evidence.record_source_read = lambda *a, **kw: None
sys.modules[evidence.__name__] = evidence
session = ModuleType('c2b_probe_core.query_session')
session.query_context = lambda *a, **kw: None
sys.modules[session.__name__] = session
spec = importlib.util.spec_from_file_location('c2b_probe_core.source_query', ROOT / 'core/source_query.py')
source_query = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = source_query
spec.loader.exec_module(source_query)
ctx = SimpleNamespace(scope='private', session_id='probe-session', user_id='probe-user',
                      group_id='', bot_id='probe-bot', persona_id='probe-persona', platform='qq')
partition, params = source_query.source_partition(ctx)
conn = sqlite3.connect(':memory:')
conn.executescript('''
CREATE TABLE timeline(id TEXT PRIMARY KEY,event_type TEXT,session_id TEXT,scope TEXT,
 subject_id TEXT,object_id TEXT,content TEXT,metadata TEXT,occurred_at TEXT,created_at TEXT);
CREATE INDEX idx_timeline_source_page ON timeline(scope,session_id,julianday(occurred_at) DESC,created_at DESC,id DESC);
''')
meta = json.dumps({'owner_bot_id':ctx.bot_id, 'platform':ctx.platform, 'persona_id':ctx.persona_id})
rows = [(f'tl_probe_{i:06}', 'user_message', ctx.session_id, 'private', ctx.user_id, ctx.user_id,
         f'合成记录 {i}', meta, f'2026-09-{i // 2400 + 1:02}T{i // 100 % 24:02}:{i % 60:02}:00+08:00', f'{i:06}')
        for i in range(50000)]
conn.executemany('INSERT INTO timeline VALUES(?,?,?,?,?,?,?,?,?,?)', rows)
conn.commit()
keycols = 'julianday(t.occurred_at),t.created_at,t.id'
base = 'SELECT t.*,julianday(t.occurred_at) AS source_sort_time FROM timeline t WHERE '+partition+' AND julianday(t.occurred_at) IS NOT NULL'
observations = []
for anchor_index in [500,25000,49000]:
    anchor = f'tl_probe_{anchor_index:06}'
    key = conn.execute('SELECT julianday(occurred_at),created_at,id FROM timeline WHERE id=?',(anchor,)).fetchone()
    for direction in ['before','after']:
        op, scalar, order = ('<','<=','DESC') if direction=='before' else ('>','>=','ASC')
        sort = ','.join(x+' '+order for x in keycols.split(','))
        tuple_sql = f' AND ({keycols}) {op} (?,?,?)'
        plans = {
            'existing_tuple':(base+tuple_sql+f' ORDER BY {sort} LIMIT ?', params+list(key)+[7]),
            'scalar_plus_tuple':(base+f' AND julianday(t.occurred_at){scalar}?'+tuple_sql+f' ORDER BY {sort} LIMIT ?',params+[key[0]]+list(key)+[7]),
        }
        ids_by_variant = {}
        for variant,(sql,args) in plans.items():
            counts=[];times=[]
            for _ in range(5):
                callbacks=[0]
                def tick():
                    callbacks[0]+=1
                    return 0
                conn.set_progress_handler(tick,100)
                start=time.perf_counter()
                found=conn.execute(sql,args).fetchall()
                times.append((time.perf_counter()-start)*1000)
                counts.append(callbacks[0]*100)
                conn.set_progress_handler(None,0)
            ids_by_variant[variant]=[r[0] for r in found]
            observations.append({'anchor_index':anchor_index,'direction':direction,'variant':variant,
                'median_ms':round(statistics.median(times),3),'vm_instruction_estimate':int(statistics.median(counts)),
                'vm_resolution':100,'returned':len(found),
                'plan':[list(row) for row in conn.execute('EXPLAIN QUERY PLAN '+sql,args)]})
        assert ids_by_variant['existing_tuple']==ids_by_variant['scalar_plus_tuple']

# Demonstrate why Python casefold cannot silently replace SQLite lower matching.
normalization=[]
for text,term in [('AbC','abc'),('Äpfel','ä'),('Straße','STRASSE'),('胖次','胖次'),('ＡB','aB')]:
    hit=bool(conn.execute('SELECT instr(lower(?),lower(?))>0',(text,term)).fetchone()[0])
    normalization.append({'text':text,'term':term,'sqlite_literal_hit':hit,'python_casefold_hit':term.casefold() in text.casefold()})
result={'type':'design_sql_probe_not_runtime_acceptance','sqlite':sqlite3.sqlite_version,'rows':len(rows),
    'repetitions':5,'dataset':'synthetic_in_memory_one_authorized_partition','query_owner_clause':'actual source_partition; valid identity values; imports stubbed',
    'source_query_sha256':hashlib.sha256((ROOT/'core/source_query.py').read_bytes()).hexdigest(),
    'measure_scope':'SQLite execute/fetch only; no service, locks, source receipts, model or network',
    'observations':observations,'normalization':normalization,'encoded_bigram_probe':probe_encoded_bigrams(conn),
    'production_writes':0,'host_reloads':0,'llm_calls':0,'embedding_calls':0,
    'reproduce':'python -X utf8 scripts/probe_source_query_plans.py --output <new-report.json>',
    'script':'scripts/probe_source_query_plans.py',
    'status':'design_probe_completed; C2b runtime implementation and acceptance not_run'}
if cli_options.output:
    cli_options.output.parent.mkdir(parents=True, exist_ok=True)
    cli_options.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
conn.close()
print(json.dumps(result,ensure_ascii=False))
