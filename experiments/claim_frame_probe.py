"""Frozen compatibility diagnostics. Reference labels never enter model requests."""
import argparse
from pathlib import Path

from commentscope.factory import claim_frame as f
from commentscope.factory.automatic import Calls, checked_call, local_provider, build_bundle
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.automatic_contract import digest
from commentscope.storage import write_json_exclusive


def unit(uid, source, claim):
    return {'claim_id': uid, 'statement': claim, 'spans': [{'text': source}]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot'); parser.add_argument('baseline_report'); parser.add_argument('reference_evaluation')
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--fixtures', default='tests/fixtures/claim-frame-cases.json')
    args=parser.parse_args()
    if (args.run_dir/'report.json').exists(): parser.error('Completed output exists')
    baseline=read_json(args.baseline_report)
    build_bundle(args.snapshot, baseline)
    refs=read_json(args.reference_evaluation)
    if refs['report_sha256'] != sha(args.baseline_report): parser.error('Reference baseline hash mismatch')
    fixtures=read_json(args.fixtures)
    by_id={u['claim_id']:u for u in baseline['units']}
    groups={g['cluster_id']:g for g in baseline['groups']}
    cases=[]
    for c in fixtures['cases']:
        cases.append({'id':c['id'], 'kind':'synthetic', 'expected':c['expected'],
                      'anchor':unit(c['id']+':a', c['left'], c.get('left_claim',c['left'])),
                      'member':unit(c['id']+':b', c['right'], c.get('right_claim',c['right']))})
    for ref in refs['groups']:
        g=groups[ref['cluster_id']]
        for m in ref['members']:
            if m['claim_id'] not in g['member_ids']: parser.error('Reference membership mismatch')
            cases.append({'id':g['cluster_id']+':'+m['claim_id'], 'kind':'real_development',
                          'expected':m['unit_faithful']==m['common_core']=='supported',
                          'anchor':by_id[g['anchor_id']], 'member':by_id[m['claim_id']]})
    manifest={'artifact_kind':'claim-frame-diagnostic-0.1', 'expires_at':baseline['expires_at'],
              'snapshot_sha256':sha(args.snapshot), 'baseline_sha256':sha(args.baseline_report),
              'reference_sha256':sha(args.reference_evaluation), 'fixture_sha256':sha(args.fixtures),
              'cases':cases, 'model':baseline['model'], 'independent_gold':False, 'service_time_input':False,
              'code_sha256':{p:sha(p) for p in ['src/commentscope/factory/claim_frame.py',
                  'src/commentscope/factory/automatic.py', 'src/commentscope/factory/automatic_contract.py', __file__]},
              'prompt_sha256':{'frame':digest(f.TASK_SYSTEMS),'conditions':digest(f.CONDITION_SYSTEM)}}
    calls=Calls(args.run_dir,manifest,local_provider)
    results=[]
    for c in cases:
        verdict=f.guard(calls,c['anchor'],c['member'],checked_call)
        f.replay(c['anchor'],c['member'],verdict)
        results.append({**c,'guard':verdict})
        print({'case':c['id'],'expected':c['expected'],'allowed':verdict['allowed'],
               'reasons':verdict['blocked_reasons']},flush=True)
    summary={}
    for kind in ['synthetic','real_development']:
        rows=[r for r in results if r['kind']==kind]
        summary[kind]={'cases':len(rows), 'positive_total':sum(r['expected'] for r in rows),
                      'positive_kept':sum(r['expected'] and r['guard']['allowed'] for r in rows),
                      'negative_total':sum(not r['expected'] for r in rows),
                      'negative_blocked':sum(not r['expected'] and not r['guard']['allowed'] for r in rows)}
    write_json_exclusive(args.run_dir/'report.json',{**manifest,'results':results,'summary':summary})
    print(summary,flush=True)


if __name__=='__main__': main()
