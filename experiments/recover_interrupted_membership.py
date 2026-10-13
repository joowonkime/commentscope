"""Record missing terminal outputs without retrying or inventing model verdicts.

The local server must be absent. Unfinished ledger reservations remain charged;
their elapsed time is unknown. This is transport recovery, not semantic repair.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import socket
import sqlite3
from commentscope.agents.runtime import request
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from experiments import fact_evidence_probe as base


def recover(directory,budget_path=base.DEFAULT_BUDGET):
    try:
        with socket.create_connection(('127.0.0.1',8091),timeout=.5):
            raise ValueError('Inference endpoint is live; do not recover a running call')
    except ConnectionRefusedError: pass
    plan=read_json(directory/'plan.json'); plan_hash=sha(directory/'plan.json')
    recovered=[]
    with sqlite3.connect(budget_path) as db:
        for row in plan['rows']:
            path=directory/(row['id']+'.json')
            if path.exists():continue
            calls=db.execute('SELECT id,state,response_json,error,charged,elapsed FROM calls WHERE plan_sha=? AND request_sha=? ORDER BY id',
                             (plan_hash,row['request_sha256'])).fetchall()
            if not calls:continue
            if len(calls)!=1:raise ValueError('Ambiguous attempts; preserve and inspect instead of choosing a favorable response')
            cid,state,response,error,charged,elapsed=calls[0]
            req=row['request']
            if digest(req)!=row['request_sha256']:raise ValueError('Frozen request changed')
            if state=='ok':
                saved=json.loads(response)
                result=request(req['system'],req['data'],req['schema'],lambda *_:saved)
                result['seconds']=elapsed
            else:
                result={'raw':None,'output':None,'errors':['interrupted_without_recorded_response' if state=='reserved' else 'recorded_'+state],
                        'seconds':elapsed,'usage':None}
            write(path,{'request_sha256':row['request_sha256'],'result':result,
                        'recovery':{'ledger_call_id':cid,'ledger_state':state,'charged_seconds':charged,
                                    'observed_at':datetime.now(timezone.utc).isoformat(),
                                    'endpoint_refused_connection':True,'model_retry':False,'elapsed_known':elapsed is not None}})
            recovered.append({'id':row['id'],'call_id':cid,'state':state})
    print({'recovered':recovered,'new_model_calls':0,'budget_refunded':False},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);a=p.parse_args();recover(a.directory)
