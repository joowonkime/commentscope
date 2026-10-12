"""Bind previously recorded NLI batches to packets without new inference.

This checks input/output hashes and replays the current record contract, not the
historical runner's code identity. The original experiment retains its revision.
"""
import argparse
from pathlib import Path
from commentscope.factory import nli_fact_records as records
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.local_nli import MODEL, REVISION
from commentscope.storage import write_json_exclusive as write


def replay(directory,output):
    plan=read_json(directory/'plan.json'); completed=read_json(directory/'completed.json')
    for name in ['plan','result','report']:
        if completed[name+'_sha256']!=sha(directory/(name+'.json')): raise ValueError('Artifact changed')
    for path,value in plan['inputs'].items():
        if sha(path)!=value:raise ValueError('Source artifact changed')
    source=read_json(Path(plan['source_directory'])/'plan.json')
    weights=next(value for path,value in plan['model_sha256'].items() if path.endswith('/model.safetensors'))
    from commentscope.factory.automatic_contract import digest
    model={'name':MODEL,'revision':REVISION,'weights_sha256':weights,
           'runtime_sha256':digest({'code_sha256':plan['code_sha256'],'model_files':plan['model_sha256']})}
    packets=[r['packet'] for r in source['rows']]
    made=records.records(packets,model,read_json(directory/'result.json'),batch_request=plan['request'])
    for record,packet in zip(made,packets,strict=True): records.validate_record(record,packet,model)
    report={'records':made,'model':model,'original_plan_sha256':completed['plan_sha256'],
            'new_model_calls':0,'records_replayed':len(made),'quality_gate_passed':False}
    write(output,report)
    print({'records_replayed':len(made),'new_model_calls':0},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();replay(a.directory,a.output)
