"""One bounded original-only policy-value nomination census over the fixed96.

This performs no Qwen generation, source admission, ownership/fact approval or
Agent compilation. Classifier nominations must pass the normal independent
gates before they can count. No input or condition is edited to make them pass.
"""
import argparse
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter

from commentscope.factory import policy_stance_hypotheses as stance,fact_checks
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources as registry
from commentscope.ingestion import load_snapshot
from commentscope.providers import evidence_nli,host_resources
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.compare_backend_discovery import SCOPE,check_quota,quota_watch
from experiments.fresh_grounded_pipeline import Runner
from experiments.scoped_discovery_probe import code_hashes
from experiments.corpus_resource_guard import host_observation
from experiments.framed_corpus_pipeline import experiment_lock

VERSION='policy-value-nomination-census-20261023-v1'


def originals(plan):
    snapshot=load_snapshot(Path(plan['snapshot'])).snapshot;fact_checks.live(snapshot.usage.expires_at)
    lookup=registry(snapshot,include_video_context=True)
    return [lookup[sid] for sid in plan['scope_ids']]


def prepare(directory):
    check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('New private stance-census directory required')
    prior=read_json(SCOPE)
    plan={'artifact_kind':VERSION,'at':datetime.now(timezone.utc).isoformat(),
        'hypothesis':'Common conditional policy-value hypotheses can be nominated from whole original entailment without inventing a shared purpose or comparing multiple authors in one generative prompt.',
        'bottleneck':'Previous generated36cores carried absent rationales/comparisons, and raw/evidence checks alone accepted author stance inversion.',
        'change':'Two transparent domain-independent conditional-value templates with a task topic verbatim in video metadata, evaluated on every unchanged own original; nominations unapproved.',
        'snapshot':prior['snapshot'],'scope_ids':prior['scope_ids'],'topic':'Universal Basic Income','alias':'UBI',
        'deployment':prior['deployment'],'classifier':prior['classifier'],
        'model_files':{p:h for p,h in prior['model_files'].items() if 'MoritzLaurer' in p},
        'resource_policy':prior['resource_policy'],'budget':prior['budget'],
        'limits':{**prior['limits'],'analysis_seconds':None},'timeout_seconds':prior['limits']['fact_batch_seconds'],
        'source_expansion':False,'source_selection':'All96, both hypotheses for every source; no parent text in premise; no truncation. Errors remain explicit holds.',
        'condition_policy':'Existing raw, full own-source, essential-condition, owned-reason and fact gates unchanged. A can-under-some-circumstances core does not itself approve deleting any source condition.',
        'evaluation':['All192 comparison outcomes and overflow/error holds','Nominees per hypothesis, never valid support counts','Possible>=3candidate sources only; actualAgent count remains0 until independent downstream compilation'],
        'decision':'If the original-only census exposes two plausible>=3-source cores, inspect their original scopes and run raw/own-source admission plus fixed-condition/argument/fact gates. Otherwise use this full-census evidence to reassess source/context limitations before any pre-frozen same-snapshot expansion.',
        'expected_calls':{'new_Qwen_proposal_calls':0,'new_embedding_calls':0,'new_NLI_batches':1,'forward_pairs':192},
        'inputs':{str(p):sha(p) for p in [SCOPE,Path(prior['snapshot']),
            Path('runs/compare-backend-20261023-v1/M1-candidate-strategy-reassessment-v2.json')]},
        'code_sha256':code_hashes(),'quality_gate_passed':False}
    sources=originals(plan);request=stance.invocation(sources,plan['topic'],plan['alias'])
    if len(sources)!=96 or len(request['data']['cases'])!=192:raise ValueError('Unchanged whole96 development scope required')
    plan.update(request=request,request_sha256=digest(request),sources_sha256=digest(sources))
    write(directory/'plan.json',plan)
    return {'prepared':True,'sources':96,'comparisons':192,'new_Qwen_calls':0}


def run(directory):
    check_quota()
    with experiment_lock(directory),quota_watch():
        plan=read_json(directory/'plan.json')
        if plan['artifact_kind']!=VERSION:raise ValueError('Stance census contract changed')
        for field in ['inputs','code_sha256','model_files']:
            for path,expected in plan[field].items():
                if sha(path)!=expected:raise ValueError('Frozen census input changed: '+path)
        if (directory/'started.json').exists():raise RuntimeError('Prior attempt exists; reconcile, no implicit retry')
        sources=originals(plan);request=stance.invocation(sources,plan['topic'],plan['alias'])
        if request!=plan['request'] or digest(sources)!=plan['sources_sha256']:raise ValueError('Original inventory changed')
        budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'],limit_seconds=None)
        write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
        runner=Runner(directory,plan,budget)
        with host_resources.watch(directory/'resources',plan['resource_policy'],host_observation):
            response=runner.call('policy-value-census',request,provider=evidence_nli.generate,maximum=plan['timeout_seconds'])
            check_quota()
        record=stance.bind(sources,plan['topic'],plan['alias'],response)
        candidates=stance.candidates(record)
        write(directory/'artifacts/record.json',record)
        write(directory/'artifacts/candidates.json',candidates)
        states=Counter(r['state'] for r in response['results'])
        report={'artifact_kind':VERSION,'source_scope':len(sources),'all_comparisons':len(response['results']),
            'states':dict(states),'candidate_nominee_counts':{c['id']:len(c['nominees']) for c in candidates},
            'candidate_texts':{c['id']:c['text'] for c in candidates},
            'actual_valid_supports':0,'actual_agents':0,'new_Qwen_calls':0,'new_NLI_batches':1,
            'all_nominees_need_independent_approval':True,'quality_gate_passed':False}
        write(directory/'report.json',report)
        write(directory/'completed.json',{'plan_sha256':sha(directory/'plan.json'),'report_sha256':sha(directory/'report.json'),
            'record_sha256':sha(directory/'artifacts/record.json')})
        return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run']);parser.add_argument('directory',type=Path)
    args=parser.parse_args();print(prepare(args.directory) if args.action=='prepare' else run(args.directory),flush=True)
