"""Freeze an offline source-evidence development review; never dispatch models.

Private originals stay in the requested output directory, outside tracked files.
Unannotated selections are explicitly not executable semantic benchmarks.
"""
import argparse
from collections import Counter
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from commentscope.factory.automatic_contract import digest


def build(artifacts):
    def read(name):return json.loads((artifacts/(name+'.json')).read_text(encoding='utf-8'))
    discourse=read('source-discourse');records=read('argument-extractions');members=read('memberships');result=read('output')
    sources={sid:row['source'] for sid,row in discourse.items()}
    seeds={r['source']['id'] for r in records}
    def thread(sid):return sources[sid]['parent']['id'] if sources[sid]['parent'] else sid
    def stratum(sid):
        s=sources[sid];text=s['text'].lower()
        if s['parent']:return 'reply_reference'
        if any(t in text for t in (' if ','unless','may ','could ','because','but ')):return 'mixed_conditional'
        if len(text)<60:return 'short_or_noise'
        return 'other'
    order=sorted(sources,key=lambda sid:digest(['source-evidence-review-v1',sid,digest(sources[sid])]))
    selected=sorted(seeds);used_threads={thread(sid) for sid in selected}
    # Rotate strata; no source/model success label is used for the new selections.
    while len(selected)<48:
        progressed=False
        for category in ('reply_reference','mixed_conditional','short_or_noise','other'):
            sid=next((s for s in order if s not in selected and thread(s) not in used_threads and stratum(s)==category),None)
            if sid is not None:selected.append(sid);used_threads.add(thread(sid));progressed=True
            if len(selected)==48:break
        if not progressed:break
    holdout=[]
    for sid in order:
        if thread(sid) in used_threads:continue
        holdout.append(sid);used_threads.add(thread(sid))
        if len(holdout)==48:break
    pairs=[row for batch in members for row in batch['memberships'] if row['relation']=='supported']
    failure_map=[]
    for r in records:
        holds=r.get('hold_reasons',[])
        failure_map.append(dict(source_ref=digest(r['source']),source_id=r['source']['id'],candidate_ids=r['candidate_ids'],
            first_recorded_hold=holds[0] if holds else None,overlapping_events=holds,
            classification='unknown',root_cause_proven=False,source_record_sha256=digest(r),
            reviewer_kind='offline_inventory_not_semantic_gold'))
    return dict(version='source-evidence-evaluation-20261111-v1',baseline_artifact_sha256={name:digest(read(name)) for name in
        ('source-discourse','argument-extractions','memberships')},
        development=[dict(source=sources[sid],source_sha256=digest(sources[sid]),stratum=stratum(sid),
            previously_deeply_assessed=sid in seeds,expected_semantics=None) for sid in selected],
        transfer=[dict(source_id=sid,source_sha256=digest(sources[sid])) for sid in holdout],
        transfer_kind='annotation_blind_same_corpus_not_unseen_domain',
        semantic_benchmark_ready=False,annotation_provenance='unannotated_selection',
        failure_map=failure_map,transport_and_binding_events=[dict(stage=e['stage'],task_sha256=e.get('task_sha256'),exception=e.get('exception'),
            message=e.get('message'),classification='unknown',root_cause_proven=False) for e in result['errors']],
        capacity_events=deepcopy_events(result['capacity_holds']),
        summary=dict(argument_records=len(records),argument_units=sum(len(r['units']) for r in records),
            verified_map_edges=len(pairs),development=len(selected),transfer=len(holdout),
            enum_events=sum(e['stage']=='membership-jev' for e in result['errors']),capacity_events=len(result['capacity_holds']),
            strata=dict(Counter(stratum(sid) for sid in selected))),
        comparison=dict(max_source_windows=48,max_source_target_pairs=256,total_proposed_usd='5.00',
            new_paid_authorization=False,minimum_reason_relations=20,minimum_net_gain='max(3,ceil(0.10*R))',
            maximum_net_support_loss=0,maximum_net_proposition_loss=0,automatic_retries=0),
        dispatch_enabled=False)


def deepcopy_events(events):
    # Distinct events are not claimed to be distinct lost sources or root causes.
    return [dict(e,root_cause_proven=False) for e in json.loads(json.dumps(events))]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();dest=args.output.resolve()
    if dest.is_relative_to(ROOT) and dest.relative_to(ROOT).parts[0] not in ('runs','artifacts'):
        parser.error('Private review output must be outside tracked source/document paths')
    value=build(args.artifacts)
    payload=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    if dest.exists() and dest.read_text(encoding='utf-8')!=payload:parser.error('Refusing to overwrite another frozen review')
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(payload,encoding='utf-8')
    print(json.dumps(dict(value['summary'],semantic_benchmark_ready=False,model_calls=0)))


if __name__=='__main__':main()
