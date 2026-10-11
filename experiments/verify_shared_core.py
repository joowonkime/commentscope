"""Read-only replay of frozen shared-core diagnostics; never contacts a model."""
import argparse
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.factory.automatic import Calls
from commentscope.factory import shared_core
from commentscope.factory.claim_clusters import read_json, sha
from experiments.claim_frame_probe import prepare_cases
from experiments.claim_support_probe import CachedScores
from experiments.shared_core_probe import has_errors


def verify(snapshot, baseline_report, reference_evaluation, report_path,
           fixtures='tests/fixtures/claim-frame-cases.json'):
    path=Path(report_path)
    report=read_json(path)
    manifest=read_json(path.parent/'llm'/'manifest.json')
    require_live(report['expires_at'])
    if (read_json(path.parent/'nli'/'manifest.json')!=manifest
            or any(report.get(k)!=v for k,v in manifest.items())):
        raise ValueError('Report/manifest changed')
    for file,expected in manifest['code_sha256'].items():
        if sha(file)!=expected: raise ValueError('Inference code changed; use recorded revision')
    hashes={'snapshot_sha256':snapshot,'baseline_sha256':baseline_report,
            'reference_sha256':reference_evaluation,'fixture_sha256':fixtures}
    if any(report[k]!=sha(file) for k,file in hashes.items()): raise ValueError('Input hash changed')
    _,cases=prepare_cases(snapshot,baseline_report,reference_evaluation,fixtures)
    if cases!=report['cases'] or len(cases)!=len(report['results']): raise ValueError('Case inventory changed')
    def forbidden(*args): raise ValueError('Missing checkpoint; verification must not run a model')
    calls=Calls(path.parent/'llm',manifest,forbidden)
    scores=CachedScores(path.parent/'nli',manifest,forbidden)
    for case,row in zip(cases,report['results']):
        if {k:row[k] for k in case}!=case: raise ValueError('Case binding changed')
        if shared_core.discover(case['anchor'],case['member'],calls,scores)!=row['trace']:
            raise ValueError('Decision replay changed')
    summary={}
    for kind in ['synthetic','real_development']:
        rows=[r for r in report['results'] if r['kind']==kind]
        summary[kind]={'positive_total':sum(r['expected'] for r in rows),
                       'positive_kept':sum(r['expected'] and bool(r['trace']['selected_core']) for r in rows),
                       'negative_total':sum(not r['expected'] for r in rows),
                       'negative_blocked':sum(not r['expected'] and not r['trace']['selected_core'] for r in rows),
                       'cases_with_errors':sum(has_errors(r['trace']) for r in rows)}
    eligible=all(s['positive_kept']==s['positive_total'] and s['negative_blocked']==s['negative_total']
                 and not s['cases_with_errors'] for s in summary.values())
    if summary!=report['summary'] or eligible!=report['next_stage_eligible']: raise ValueError('Summary changed')
    return {'replayed_cases':len(cases),'unique_nli_requests':len(scores.records),'model_calls':0,
            'next_stage_eligible':eligible}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['snapshot','baseline_report','reference_evaluation','report']: parser.add_argument(name)
    parser.add_argument('--fixtures',default='tests/fixtures/claim-frame-cases.json')
    args=parser.parse_args()
    print(verify(args.snapshot,args.baseline_report,args.reference_evaluation,args.report,args.fixtures))


if __name__=='__main__': main()
