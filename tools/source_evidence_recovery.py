"""Resume the frozen F4 comparison after a proven host reboot, without retrying.

Only a request started before the current Linux boot, with no saved response,
can be conservatively settled. Original plans, intents and requests stay intact.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from tools import source_evidence_trial as trial
from tools.wide_mining_recovery import database
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.shared_admission import PriorRequestUnavailable
from commentscope.providers.checkpoint_calls import VERSION as CHECKPOINT_VERSION
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write

VERSION='source-evidence-host-reboot-recovery-20261112-v1'
TOOL=Path(__file__).resolve()
ERROR='host_reboot_response_unavailable_no_retry'


def boot_observation():
    # A missing Linux boot clock is not evidence that an executor has stopped.
    seconds=int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime ')))
    return {'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'boot_at':datetime.fromtimestamp(seconds,timezone.utc).isoformat()}


def evidence(directory,plan,request_file,boot):
    directory=Path(directory).resolve();request_file=Path(request_file).resolve()
    if request_file.parent!=directory/'calls' or not request_file.name.endswith('.request.json'):
        raise ValueError('Exact original request file required')
    saved=read_json(request_file);request_sha=digest(saved['request']);plan_sha=sha(directory/'plan.json')
    if saved['plan_sha256']!=plan_sha or saved['request_sha256']!=request_sha:
        raise ValueError('Original request provenance changed')
    result=request_file.with_name(request_file.name.replace('.request.json','.result.json'))
    if result.exists():raise ValueError('A saved response cannot be treated as lost')
    stage=re.sub(r'^\d+-','',request_file.name.removesuffix('.request.json'))
    identity=dict(artifact_kind=CHECKPOINT_VERSION,plan_sha256=plan_sha,stage=stage,request_sha256=request_sha,
                  provider=trial.executor.openrouter.Runner.provider_identity)
    intent=directory/'checkpoints'/(digest(identity)+'.intent.json')
    if read_json(intent)!=identity or intent.with_name(intent.name.replace('.intent.json','.result.json')).exists():
        raise ValueError('Original pending checkpoint required')
    with database(directory/'inference.sqlite') as db:
        rows=db.execute('SELECT id,started_at,reserved,request_json,response_json,state,error FROM calls WHERE plan_sha=? AND request_sha=?',
                        (plan_sha,request_sha)).fetchall()
    if (len(rows)!=1 or json.loads(rows[0][3])!=saved['request'] or rows[0][4] is not None
            or rows[0][5] not in ('reserved','interrupted')
            or rows[0][5]=='interrupted' and rows[0][6]!=ERROR):
        raise ValueError('Unique original unfinished or audited interrupted call required')
    started=datetime.fromisoformat(rows[0][1]);boot_at=datetime.fromisoformat(boot['boot_at'])
    if not boot.get('boot_id') or not started<boot_at<=datetime.now(timezone.utc):
        raise ValueError('Request must predate the current audited kernel boot')
    with database(plan['spend_policy']['ledger']) as db:
        money=db.execute('SELECT id,reserved,charged,state FROM calls WHERE plan_sha=? AND request_sha=?',
                         (plan['spend_scope_sha256'],request_sha)).fetchall()
    if (len(money)!=1 or money[0][3] not in ('reserved','unknown','conservative')
            or money[0][1]!=money[0][2] or money[0][1]<=0):
        raise ValueError('Exact full money reservation required')
    return dict(plan_sha256=plan_sha,scope_sha256=plan['spend_scope_sha256'],request_sha256=request_sha,stage=stage,
        inference_id=rows[0][0],started_at=rows[0][1],reserved_seconds=rows[0][2],
        reconstructed_seconds_until_boot=max(rows[0][2],(boot_at-started).total_seconds()),
        elapsed_is_measured_provider_time=False,ledger_call_id=money[0][0],retained_units=money[0][1],boot=boot,
        files={str(f.relative_to(directory)):sha(f) for f in (request_file,intent)})


def settle(directory,plan,proof_file):
    proof=read_json(proof_file);row=proof['evidence'];request=directory/proof['request_file']
    if proof['version']!=VERSION+'-proof' or evidence(directory,plan,request,row['boot'])!=row:
        raise ValueError('Host interruption proof changed')
    time=trial.executor.InferenceBudget(directory/'inference.sqlite',trial.executor.VERSION,limit_seconds=None)
    with database(directory/'inference.sqlite') as db:
        state=db.execute('SELECT state FROM calls WHERE id=?',(row['inference_id'],)).fetchone()[0]
    if state=='reserved':
        time.finish(row['inference_id'],row['reconstructed_seconds_until_boot'],'interrupted',error=ERROR)
    money=trial.executor.ledger(plan['spend_policy'])
    with database(plan['spend_policy']['ledger']) as db:
        state=db.execute('SELECT state FROM calls WHERE id=?',(row['ledger_call_id'],)).fetchone()[0]
    if state=='reserved':money.finish(row['ledger_call_id'],None)
    with database(plan['spend_policy']['ledger']) as db:
        state=db.execute('SELECT state FROM calls WHERE id=?',(row['ledger_call_id'],)).fetchone()[0]
    if state=='unknown':
        money.resolve_conservatively(row['ledger_call_id'],plan_sha256=row['scope_sha256'],request_sha256=row['request_sha256'],
            evidence_sha256=sha(proof_file),reason='Proven kernel reboot; retain full reservation, no saved output and no provider retry.')
    settled(directory,plan,proof_file)


def settled(directory,plan,proof_file):
    proof=read_json(proof_file);row=proof['evidence']
    if proof['version']!=VERSION+'-proof' or evidence(directory,plan,directory/proof['request_file'],row['boot'])!=row:
        raise ValueError('Audited interrupted input changed')
    with database(plan['spend_policy']['ledger']) as db:
        state=db.execute('SELECT state FROM calls WHERE id=?',(row['ledger_call_id'],)).fetchone()
        resolution=db.execute('SELECT evidence_sha FROM resolutions WHERE call_id=?',(row['ledger_call_id'],)).fetchone()
    with database(directory/'inference.sqlite') as db:
        time=db.execute('SELECT state,error,elapsed FROM calls WHERE id=?',(row['inference_id'],)).fetchone()
    if (state!=('conservative',) or resolution!=(sha(proof_file),)
            or time!=('interrupted',ERROR,row['reconstructed_seconds_until_boot'])):
        raise ValueError('Full audited settlement required before continuation')
    return row


def prepare(root,manifest_file,*,user_request):
    root=Path(root).resolve();manifest_file=Path(manifest_file).resolve();trial.executor.private(manifest_file)
    if not user_request.strip() or manifest_file.exists() or not manifest_file.is_relative_to(root/'recoveries'):
        raise ValueError('New private recovery manifest and continuation instruction required')
    boot=boot_observation();entries=[]
    for arm in trial.ARMS:
        directory=root/arm;plan=trial.validate(directory)
        with trial.executor.experiment_lock(directory):
            for request in sorted((directory/'calls').glob('*.request.json')):
                if request.with_name(request.name.replace('.request.json','.result.json')).exists():continue
                row=evidence(directory,plan,request,boot);proof_file=manifest_file.parent/(arm+'-'+str(row['ledger_call_id'])+'-proof.json')
                proof=dict(version=VERSION+'-proof',request_file=str(request.relative_to(directory)),evidence=row)
                if proof_file.exists():
                    if read_json(proof_file)!=proof:raise ValueError('Existing interruption proof changed')
                else:write(proof_file,proof)
                entries.append(dict(arm=arm,proof_file=str(proof_file),proof_sha256=sha(proof_file)))
    if not entries:raise ValueError('No proven pre-reboot interrupted call')
    plan=read_json(root/'B/plan.json')
    with database(plan['spend_policy']['ledger']) as db:
        unresolved={row[0] for row in db.execute("SELECT id FROM calls WHERE state NOT IN ('complete','conservative')")}
    if not unresolved<={read_json(e['proof_file'])['evidence']['ledger_call_id'] for e in entries}:
        raise ValueError('Other active or uncertain charges block recovery')
    for entry in entries:
        directory=root/entry['arm']
        with trial.executor.experiment_lock(directory):settle(directory,read_json(directory/'plan.json'),Path(entry['proof_file']))
    archive=manifest_file.parent/'launcher.py'
    if archive.exists():
        if sha(archive)!=sha(TOOL):raise ValueError('Archived recovery code changed')
    else:
        with archive.open('xb') as stream:stream.write(TOOL.read_bytes())
    body=dict(version=VERSION,root=str(root),user_request=user_request,created_at=datetime.now(timezone.utc).isoformat(),
        original_tool_sha256=sha(trial.ROOT/'tools/source_evidence_trial.py'),launcher_sha256=sha(TOOL),launcher_archive=str(archive),
        plan_hashes={a:sha(root/a/'plan.json') for a in trial.ARMS},entries=entries,provider_retries=0,
        original_scope_money_deadline_and_semantic_contract_unchanged=True,formal_admission=False)
    write(manifest_file,{**body,'integrity_sha256':digest(body)})
    validate(root,manifest_file)
    return dict(unavailable_requests=len(entries),paid_retries=0,shared_charge=trial.executor.ledger(plan['spend_policy']).summary(plan_sha256=plan['spend_scope_sha256']))


def validate(root,manifest_file):
    root=Path(root).resolve();manifest_file=Path(manifest_file).resolve();value=read_json(manifest_file)
    body={k:v for k,v in value.items() if k!='integrity_sha256'}
    if (not manifest_file.is_relative_to(root/'recoveries') or value['version']!=VERSION or value['root']!=str(root)
            or value['integrity_sha256']!=digest(body) or value['provider_retries']!=0 or value['formal_admission'] is not False
            or value['original_scope_money_deadline_and_semantic_contract_unchanged'] is not True
            or value['launcher_sha256']!=sha(TOOL) or sha(value['launcher_archive'])!=sha(TOOL)
            or value['original_tool_sha256']!=sha(trial.ROOT/'tools/source_evidence_trial.py')
            or value['plan_hashes']!={a:sha(root/a/'plan.json') for a in trial.ARMS} or not value['entries']):
        raise ValueError('Frozen supplemental recovery control changed')
    for entry in value['entries']:
        if (entry['arm'] not in trial.ARMS or not Path(entry['proof_file']).resolve().is_relative_to(manifest_file.parent)
                or sha(entry['proof_file'])!=entry['proof_sha256']):raise ValueError('Original recovery proof required')
        settled(root/entry['arm'],read_json(root/entry['arm']/'plan.json'),Path(entry['proof_file']))
    return value


def wire_identity(plan,stage,request):
    family=trial.cost.canonical(stage,request);role=trial.remote.role(family)
    key='generation' if role=='interaction' else role
    field='deployment' if key=='generation' else 'verification_deployment'
    actual=allocate(request,trial.executor.openrouter.generation_allocation(plan[field],require_explicit=True))
    return key+'-'+family+'-'+digest(request)[:20],digest(actual)


def run(root,manifest_file):
    root=Path(root).resolve();manifest_file=Path(manifest_file).resolve();manifest=validate(root,manifest_file)
    pinned=sha(manifest_file);original=trial.Session
    blocked={(e['arm'],read_json(e['proof_file'])['evidence']['stage'],read_json(e['proof_file'])['evidence']['request_sha256']) for e in manifest['entries']}
    class RecoverySession(original):
        def call(self,stage,request):
            if sha(manifest_file)!=pinned:raise ValueError('Recovery manifest changed during execution')
            validate(root,manifest_file)
            key=(self.plan['arm'],*wire_identity(self.plan,stage,request))
            if key in blocked:
                family=trial.cost.canonical(stage,request);identity=(family,digest(request))
                if identity not in self.seen and len(self.seen)>=self.plan['maximum_physical_requests']:
                    raise trial.BudgetExhausted('Original physical cap retained')
                self.seen.add(identity)
                raise PriorRequestUnavailable('Audited pre-reboot request unavailable; full charge retained, no retry')
            return super().call(stage,request)
    # The original file/plan stays frozen. This explicit additional control is
    # archived and bound to each completion; it supplies no fabricated response.
    trial.Session=RecoverySession
    try:
        reports=[]
        for arm in trial.ARMS:
            report=trial.run_arm(root/arm);reports.append(report)
            binding=dict(version=VERSION+'-completion',manifest_sha256=pinned,completed_sha256=sha(root/arm/'completed.json'),
                         unavailable_requests=sum(e['arm']==arm for e in manifest['entries']),provider_retries=0,formal_admission=False)
            file=manifest_file.parent/(arm+'-completion.json')
            if file.exists():
                if read_json(file)!=binding:raise ValueError('Recovery completion changed')
            else:write(file,binding)
            print(json.dumps({'arm':arm,'profiles':report['profiles'],'errors':report['errors'],'shared_charge':report['shared_comparison_charge']}),flush=True)
        return reports
    finally:trial.Session=original


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','run'));p.add_argument('root',type=Path)
    p.add_argument('manifest',type=Path);p.add_argument('--user-request');p.add_argument('--key-file',type=Path);a=p.parse_args()
    if a.action=='prepare':result=prepare(a.root,a.manifest,user_request=a.user_request or '')
    else:
        if not a.key_file:p.error('Private key file required for continuation')
        os.environ['OPENROUTER_API_KEY']=a.key_file.read_text().strip();result=run(a.root,a.manifest)
    print(json.dumps(result,ensure_ascii=False,default=str),flush=True)


if __name__=='__main__':main()
