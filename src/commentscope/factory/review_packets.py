"""Canonical full-output review inventory; no model calls or verdicts.

Packet generation and evaluation share this projection of immutable artifacts.
Reviewer labels stay in the separate review and are never pipeline inputs.
"""
from commentscope.factory import acceptance
from commentscope.factory.automatic_contract import digest
from commentscope.factory.position_frames import source_packet


def build_packet(run, plan, completion, snapshot, output, runtime, *, version,
                 fact_report, initial_candidates):
    profile = acceptance.from_plan(plan)
    opinion = output['agent_inputs']['map']['opinion_map']; lookup = {p['id']: p for p in opinion['perspectives']}
    original = {sid: source_packet(snapshot, sid) for sid in plan['scope_ids']}
    initial = {c['id']: c for c in initial_candidates}
    if len(initial) != len(initial_candidates):
        raise ValueError('Duplicate initial candidate identity')
    rows = []
    def task(kind, key, data):
        rows.append({'id': kind+':'+digest(key), 'kind': kind, 'key': key, 'data': data})
    for sid in plan['scope_ids']:
        record = next((r for r in output['extractions'] if r['source']['id'] == sid), None)
        data = {'original': original[sid], 'extraction': record}
        if profile is not None:
            data['retained_memberships'] = [p for p in opinion['perspectives'] if sid in p['supported_canonical_ids']]
        task('source', sid, data)
    for p in opinion['perspectives']:
        task('candidate', p['id'], p)
    for r in opinion['assessments']:
        if r['relation'] == 'supported':
            sid, cid = r['canonical_source_id'], r['perspective_id']
            task('support', [cid, sid], {'original': original[sid], 'claim': lookup[cid]['claim'], 'assessment': r})
    for eq in output['equivalences']:
        for r in eq['relations']:
            task('equivalence', [r['a'], r['b']], {'a': initial[r['a']],
                 'b': initial[r['b']], 'decision': r})
    for record in output['arguments']:
        task('argument', record['source']['id'], record)
    for agent in output['agent_inputs']['compiled']['profiles']:
        task('agent', agent['candidate_id'], agent)
    for row in runtime['turns']:
        task('runtime', [row['candidate_id'], row['question_id']], row)
    packet = {'artifact_kind': version+'-packet', 'run': str(run), 'plan_sha256': completion['plan_sha256'],
              'output_sha256': completion['output_sha256'], 'runtime_sha256': completion['runtime_sha256'],
              'tasks': rows, 'fact_benchmark': fact_report, 'runtime_input': False, 'independent_gold': False,
              'rubric': 'Every source/candidate/support/equivalence/argument/agent/turn. Review stance, author, conditions, reason ownership, facts and citations. '
                        'source pass requires at least one substantive faithfully retained proposition; report other omissions separately. '
                        'All counted support must pass; a correct edge never cancels an incorrect edge. '
                        'candidate pass means coherent full stance; equivalence pass means the recorded relation preserves full essential scope. '
                        'Agent pass includes core and all major arguments and external fact scope. Runtime pass requires question relevance, own citations, appropriate abstention and history isolation.'}
    return packet
