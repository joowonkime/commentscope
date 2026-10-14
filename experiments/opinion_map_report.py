"""Account for every existing candidate against a complete frozen snapshot.

Offline compatibility report only: preserves legacy semantic decisions; does
not implement the newly agreed common-position discovery algorithm.
"""
import argparse
from pathlib import Path

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory import opinion_map
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive as write

LEGACY = {'supported': 'supported', 'partial': 'uncertain',
          'unsupported': 'not_supported', 'unassessed': 'unassessed'}


def report(source, supplement=None):
    plan = read_json(source/'plan.json'); completed = read_json(source/'completed.json')
    if plan['artifact_kind'] != 'fresh-direct-ground-product-0.1' or completed['artifact_kind'] != plan['artifact_kind']:
        raise ValueError('Completed fresh direct source required')
    loaded = load_snapshot(plan['snapshot'])
    if loaded.sha256 != plan['inputs'][plan['snapshot']]:
        raise ValueError('Snapshot changed')
    queue = read_json(source/'selected-queue.json'); outcomes = completed['outcomes']
    if [p['id'] for p in queue] != [o['id'] for o in outcomes]:
        raise ValueError('Full ordered candidate population required')
    paths = [source/n for n in ('plan.json','completed.json','selected-queue.json')]
    paths.append(Path(plan['snapshot']))
    directories = [source]; supplemented_ids = set()
    if supplement is not None:
        extra = read_json(supplement/'plan.json'); result = read_json(supplement/'completed.json')
        if (extra['artifact_kind'] != 'pending-core-population-diagnostic-0.1'
                or result['artifact_kind'] != extra['artifact_kind']
                or Path(extra['source_directory']).resolve() != source.resolve()
                or extra['inputs'][str(source/'plan.json')] != sha(source/'plan.json')
                or extra['inputs'][str(source/'completed.json')] != sha(source/'completed.json')):
            raise ValueError('Supplement must bind to this completed source')
        expected = [p for p,o in zip(queue,outcomes,strict=True) if o['state']=='unprocessed_completion_budget']
        if [t['proposal'] for t in extra['tasks']] != expected or [o['id'] for o in result['outcomes']] != [p['id'] for p in expected]:
            raise ValueError('Complete unchanged pending population required')
        supplemented_ids = {p['id'] for p in expected}
        paths += [supplement/'plan.json', supplement/'completed.json']
        directories.append(supplement)
    perspectives = []; assessments = []
    for p, outcome in zip(queue, outcomes, strict=True):
        perspectives.append({'id': p['id'], 'claim': p['claims']['C'],
                             'upstream_agent_state': outcome['state']})
        found = [d/'candidates'/p['id']/'membership.json' for d in directories
                 if (d/'candidates'/p['id']/'membership.json').exists()]
        if len(found) > 1:
            raise ValueError('Do not overwrite an already measured candidate')
        if not found:
            if p['id'] in supplemented_ids or not outcome['state'].startswith('unprocessed_'):
                raise ValueError('Measured membership missing')
            continue
        path = found[0]; paths.append(path); m = read_json(path)
        if (m['proposals'] != [p] or len(m['rows']) != len(p['sources'])
                or len({r['id'] for r in m['rows']}) != len(m['rows'])
                or {r['source_id'] for r in m['rows']} != set(p['sources'])
                or {r['id'] for r in m['rows']} != set(m['actual'])):
            raise ValueError('Membership population changed')
        for r in m['rows']:
            if r['claim'] != p['claims']['C'] or r['text'] != p['sources'][r['source_id']]:
                raise ValueError('Membership target/source changed')
            assessments.append({'perspective_id': p['id'], 'source_id': r['source_id'],
                'claim_sha256': digest(r['claim']), 'source_sha256': digest(r['text']),
                'relation': LEGACY[m['actual'][r['id']]], 'evidence_ref': str(path)+'#'+r['id']})
    output = opinion_map.build(loaded.snapshot, perspectives, assessments)
    output.update(input_sha256={str(p): sha(p) for p in paths},
                  fresh_analysis=False, new_inference_calls=0, common_position_algorithm_implemented=False)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--supplement', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); output = report(args.source, args.supplement)
    write(args.output, output)
    print(output['coverage'])
