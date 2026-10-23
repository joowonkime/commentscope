"""Read-only ledger validation for reusing completed common proposals.

No model execution, reservations, semantic labels or corrected candidates enter
this adapter. Raw outputs must match their original request and complete ledger
response, even if downstream Factory implementation has since changed.
"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from contextlib import closing

from commentscope.factory import shared_claims
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.checkpoint_calls import VERSION as CHECKPOINT_VERSION
from commentscope.providers.generation_limits import allocate

BOUNDARY = ('src/commentscope/factory/shared_claims.py',
            'src/commentscope/factory/minimal_claims.py',
            'src/commentscope/factory/position_frames.py',
            'src/commentscope/providers/local_llama.py',
            'src/commentscope/providers/generation_limits.py',
            'src/commentscope/contracts/perspective_draft.py')


def load(directory, *, deployment, originals):
    directory = Path(directory)
    if not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('Private completed proposal run required')
    plan = read_json(directory/'plan.json'); plan_hash = sha(directory/'plan.json')
    done = read_json(directory/'completed.json')
    if (plan.get('proposal_contract') != shared_claims.COMMON
            or plan['deployment'] != deployment or done['plan_sha256'] != plan_hash
            or done['output_sha256'] != sha(directory/'artifacts/output.json')
            or done['errors'] or done['capacity_holds']):
        raise ValueError('Exact completed common discovery and deployment required')
    # Shared proposal validation is append-only: later for_scope helpers may be
    # added, so replay exact logical requests rather than requiring the entire
    # historical module file to remain byte-identical forever.
    for path in BOUNDARY[1:]:
        if sha(path) != plan['code_sha256'][path]:
            raise ValueError('Proposal input/provider boundary changed: '+path)
    output = read_json(directory/'artifacts/output.json')
    records = shared_claims.for_scope(output['records'], originals)
    if shared_claims.candidates(records) != output['candidates']:
        raise ValueError('Cached candidates differ from automatic proposal binding')
    call_files = list((directory/'calls').glob('*.request.json'))
    by_request = {}
    for path in call_files:
        packet = read_json(path)
        key = digest(packet['request'])
        if key in by_request or packet['request_sha256'] != key or packet['plan_sha256'] != plan_hash:
            raise ValueError('Duplicate or changed proposal call identity')
        by_request[key] = (path, packet)
    receipts = []; used = set()
    ledger = Path(plan['budget']['ledger']).resolve()
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro', uri=True)) as db:
        for record in records:
            logical = shared_claims.request(record['sources'], version=shared_claims.COMMON)
            actual = allocate(logical, deployment['runtime']); key = digest(actual)
            path, packet = by_request[key]; used.add(key)
            if actual != packet['request'] or digest(logical) != record['request_sha256']:
                raise ValueError('Logical proposal request changed')
            result = read_json(path.with_name(path.name.replace('.request.json', '.result.json')))
            if result['errors'] or result['output'] != record['output']:
                raise ValueError('Cached proposal result changed')
            stage = 'shared-proposal-'+digest(logical)[:24]
            identity = {'artifact_kind': CHECKPOINT_VERSION, 'plan_sha256': plan_hash,
                        'stage': stage, 'request_sha256': key, 'provider': 'local_llama'}
            checkpoint = directory/'checkpoints'/digest(identity)
            if read_json(checkpoint.with_suffix('.intent.json')) != identity:
                raise ValueError('Checkpoint intent changed')
            expected = {'identity': identity, 'result': result, 'result_sha256': digest(result)}
            if read_json(checkpoint.with_suffix('.result.json')) != expected:
                raise ValueError('Checkpoint response changed')
            rows = db.execute('SELECT id,request_json,response_json FROM calls '
                              'WHERE plan_sha=? AND request_sha=? AND state=?',
                              (plan_hash, key, 'ok')).fetchall()
            if len(rows) != 1 or json.loads(rows[0][1]) != actual:
                raise ValueError('Unique completed ledger request required')
            response = json.loads(rows[0][2]); choice = response['choices'][0]
            if (choice['finish_reason'] != 'stop' or choice['message']['content'] != result['raw']
                    or json.loads(result['raw']) != result['output'] or response['usage'] != result['usage']):
                raise ValueError('Proposal differs from the completed raw ledger response')
            receipts.append({'ledger_call_id': rows[0][0], 'request_sha256': key,
                             'proposal_sha256': digest(record), 'result_sha256': digest(result)})
    if used != set(by_request) or len(records) != done['completed_proposal_calls']:
        raise ValueError('Incomplete proposal call coverage')
    return deepcopy(records), {'source_plan_sha256': plan_hash,
        'source_output_sha256': done['output_sha256'], 'receipts': receipts,
        'ledger': str(ledger), 'new_model_calls': 0, 'semantic_approval': False}
