"""Prove failed gates from partial runs without excluding unexecuted cases."""
import argparse
from pathlib import Path
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.scoped_discovery import verdict
from commentscope.storage import write_json_exclusive as write


def analyze(source,nli_directory):
    plan=read_json(source/'plan.json');refs=read_json(source/'references.json')['labels']
    if read_json(source/'reference-frozen.json')['sha256']!=sha(source/'references.json'):raise ValueError('References changed')
    ids=plan['evaluation_ids'];positive=[i for i in ids if refs[i]=='supported']
    actual={}
    hashes={}
    for row in plan['rows']:
        path=source/(row['id']+'.json')
        if path.exists():actual[row['id']]=verdict(read_json(path)['result']);hashes[str(path)]=sha(path)
    nli={r['id']:r['state'] for r in read_json(nli_directory/'result.json')['results']}
    false=[i for i in ids if actual.get(i)=='supported' and refs[i]!='supported']
    nli_positive=[i for i in positive if nli[i]=='supported']
    precision_upper=len(positive)/(len(positive)+len(false))
    retention_upper=len(nli_positive)/len(positive)
    impossible=precision_upper<.95 and retention_upper<.8
    if not impossible:raise ValueError('Bounds do not justify stopping both variants')
    report={'planned_evaluation':100,'reference_positive':len(positive),
        'llm_observed_cases':sum(i in actual for i in ids),'llm_observed_supports':sum(actual.get(i)=='supported' for i in ids),
        'llm_false_supports_observed':false,'llm_precision_best_possible':precision_upper,
        'intersection_retention_best_possible':retention_upper,'nli_positive_kept':nli_positive,
        'errors':[i for i in ids if actual.get(i)=='error'],'unexecuted':[i for i in ids if i not in actual],
        'stop_reason':'Both preregistered adoptable variants fail even if every unexecuted case is favorable.',
        'fixed_denominator_preserved':True,'thresholds_changed':False,'quality_gate_passed':False,
        'independent_gold':False,'inputs':{str(source/'plan.json'):sha(source/'plan.json'),
            str(source/'references.json'):sha(source/'references.json'),str(nli_directory/'result.json'):sha(nli_directory/'result.json'),**hashes}}
    write(source/'early-stopped.json',report)
    print({k:v for k,v in report.items() if k not in ['inputs','nli_positive_kept','unexecuted']},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('nli_directory',type=Path)
    a=p.parse_args();analyze(a.source,a.nli_directory)
