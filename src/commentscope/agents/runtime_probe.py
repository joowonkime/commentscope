"""Fixed grounded-Agent execution checks; semantic review remains separate.

The questions and emitted artifacts retain the existing Factory contract. This
module receives a runner and does not load models or choose evaluation labels.
"""
import json

from commentscope.agents.grounded_runtime import GroundedSession
from commentscope.factory.automatic_contract import digest

QUESTIONS = [
    {'id': 'position', 'text': 'What is the central position represented here?'},
    {'id': 'reasons', 'text': 'What reasons and conditions are actually available for this position?'},
    {'id': 'missing', 'text': 'What are the exact annual implementation cost and measured percentage reduction in accidents?'}]


def runtime_probe(bundle, runner, *, save_turn=None):
    from commentscope.agents.grounded_inputs import compile_inputs
    profiles = compile_inputs(bundle)['profiles']; sessions = {}; rows = []
    def provider(system, data, schema, *, max_tokens):
        result = runner.call('runtime', {'system': system, 'data': data, 'schema': schema, 'max_tokens': max_tokens})
        if result.get('errors'): raise ValueError('Bounded runtime inference failed')
        return {'choices': [{'message': {'content': json.dumps(result['output'])}, 'finish_reason': 'stop'}]}
    for p in profiles:
        cid = p['candidate_id']; sessions[cid] = GroundedSession(bundle, cid, provider=provider)
    for cid, session in sessions.items():
        for question in QUESTIONS:
            before = {other: digest(s.history) for other, s in sessions.items() if other != cid}
            turn = session.ask(question['text'])
            isolated = all(digest(sessions[other].history) == h for other, h in before.items())
            row={'candidate_id': cid, 'question_id': question['id'], 'turn': turn,
                 'other_histories_unchanged': isolated}
            rows.append(row)
            if save_turn is not None:
                save_turn(row)
                if turn['status']=='error':
                    raise ValueError('Actual runtime turn failed; exact turn persisted: '+cid+'/'+question['id'])
    return {'all_compiled_candidate_ids': list(sessions), 'turns': rows,
            'quality_gate_passed': False, 'requires_semantic_review': True}


def runtime_check(runtime, compiled, *, questions=QUESTIONS):
    ids = [p['candidate_id'] for p in compiled['profiles']]
    expected = {(cid, q['id']) for cid in ids for q in questions}
    actual = {(r['candidate_id'], r['question_id']) for r in runtime['turns']}
    if (runtime['all_compiled_candidate_ids'] != ids or actual != expected or len(runtime['turns']) != len(expected)
            or any(r['turn']['compiled_sha256'] != digest(compiled) for r in runtime['turns'])):
        raise ValueError('Same-plan runtime artifact changed')
    question_text = {q['id']: q['text'] for q in questions}
    for row in runtime['turns']:
        turn = row['turn']
        if row.get('other_histories_unchanged') is not True:
            raise ValueError('Other Agent history changed or was not verified')
        if turn.get('candidate_id') != row['candidate_id']:
            raise ValueError('Runtime Agent identity changed')
        if turn.get('question') != question_text[row['question_id']]:
            raise ValueError('Runtime fixed question text changed')
        if turn.get('status') not in ('answered', 'abstain'):
            raise ValueError('Runtime answer status is not a valid execution')
