"""Offline product regressions for the fixed automatic debate contract."""
from copy import deepcopy
from decimal import Decimal
import json
import secrets
import threading
import unittest

from commentscope.agents.web import WebError
from commentscope.agents.debate_quantities import changes_weekly_hours
from commentscope.product.analysis import Analysis
from commentscope.product.app import ProductApp
from commentscope.product.debate_execution import room_at
from commentscope.providers.openai_schema import compile_schema
from test_jev_membership import receipt
import test_product_app as fixtures
from test_seeded_perspectives import seeded_bundle


class AutomaticDebateTests(unittest.TestCase):
    call = fixtures.ProductAppTests.call
    job = fixtures.ProductAppTests.job

    def setUp(self):
        self.events = []
        self.overrides = {}
        self.reject = set()
        self.no_proposal = False
        self.use_reference = False
        self.pair_conflict = False
        self.extra_opening_point = False
        fixtures.ProductAppTests.setUp(self)

    def build(self):
        bundle = seeded_bundle()
        bundle['candidates'].extend({**deepcopy(bundle['candidates'][0]), 'id': f'P{i}'} for i in (2, 3, 4))
        self.analysis = Analysis(bundle, {'source': 'synthetic-test'})
        return ProductApp(self.path, [self.analysis], self.model, session_ttl_seconds=3600, room_maximum_usd='1',
                          reservation=lambda req: '0.001', decision=self.decide,
                          decision_reservation=lambda: '0.002', debate_execution_binding={'fixture': True})

    def model(self, stage, request):
        if stage == 'reflection':
            return fixtures.ProductAppTests.model(self, stage, request)
        compile_schema(request['schema'])
        self.events.append((stage, deepcopy(request)))
        data = request['data']
        scope = data['DEBATE_SCOPE']
        if stage == 'turn-generate':
            origin = ('external_evidence' if self.use_reference else 'original_comment'
                      if scope['phase'] == 'opening' else 'ai_reasoning')
            point = {
                'origin': origin, 'text': '' if origin == 'original_comment' else 'Checks can help when hazards matter.',
                'anchor_ids': ['E1'], 'reference_ids': ['D1'] if self.use_reference else [],
                'targets': [{'target_id': key, 'relation': 'conditional'} for key in data['TARGETS']]}
            output = {'answerability': 'answered', 'points': {'P1': point, 'P2': None, 'P3': None}}
            if self.extra_opening_point and (scope['phase'], scope['agent_id']) == ('opening', 'P2'):
                output['points']['P2'] = {**point, 'origin': 'ai_reasoning', 'text': 'This claim exceeds the evidence.'}
        elif stage == 'draft-generate':
            candidate = {
                'origin': 'external_evidence' if self.use_reference else 'ai_reasoning',
                'text': 'Check for safety where the scope warrants it.', 'premise_ids': list(data['POINTS'])[:3],
                'condition_ids': list(data['CONDITIONS']), 'reference_ids': ['D1'] if self.use_reference else [],
            }
            output = {'candidates': [] if self.no_proposal else [
                {**candidate, 'text': candidate['text'] + f' {i}'}
                for i in range(3 if self.pair_conflict else 1)]}
        else:
            self.assertEqual(stage, 'ratify-generate')
            output = {key: {'decision': 'reject' if scope['agent_id'] in self.reject else 'accept',
                            'reason_ids': [next(reversed(data['OWN_POINTS']))], 'missing_condition_ids': []}
                      for key in data['CANDIDATES']}
        return {'output': output, 'errors': [], 'new_cost_usd': '0.001'}

    def decide(self, stage, payload):
        self.events.append((stage, deepcopy(payload)))
        scope = payload['state']['DEBATE_SCOPE']
        def choose(key, q):
            return self.overrides.get((stage, scope.get('phase'), scope.get('agent_id'), key),
                                      'incompatible' if stage == 'draft-verify' and self.pair_conflict and key == 'A1_A2'
                                      else next(iter(q['criteria'])))
        return receipt(payload, choose)

    def debate(self, participants=('P2', 'P1'), request_id='debate', question='Should we require a safety check?'):
        status, value = self.call('POST', self.base+'/debates', {
            'analysis_revision': self.analysis.revision, 'participant_ids': list(participants),
            'initial_revision': 1, 'question': question, 'request_id': request_id})
        self.assertEqual(status, 201)
        return '/api/v1/debates/'+value['debate_id'], value

    def start(self, path, debate):
        return self.call('POST', path+'/start', {'expected_revision': debate['revision'], 'request_id': 'start'})

    def complete(self, participants=('P2', 'P1')):
        path, debate = self.debate(participants)
        status, job = self.start(path, debate)
        self.assertEqual(status, 202)
        settled = self.job(job)
        self.assertEqual(settled['state'], 'succeeded', settled)
        return path, self.call('GET', path)[1]

    def control(self, path, action, request_id=None):
        current = self.call('GET', path)[1]
        return self.call('POST', path+'/control', {'action': action, 'expected_revision': current['revision'],
                                                 'request_id': request_id or action})

    def test_full_debate_lineage_restart_derived_question_and_reflection(self):
        path, final = self.complete()
        self.assertEqual(final['state'], 'completed')
        self.assertFalse(final['can_ask'])
        self.assertEqual(len(self.events), 14)
        messages = final['messages']
        self.assertEqual([m['agent_id'] for m in messages[1:]], ['P2', 'P1', 'P2', 'P1'])
        self.assertEqual(final['opening_cutoff_seq'], 3)
        self.assertEqual([m['seq'] for m in self.call('GET', path+'?after_seq=3')[1]['messages']], [4, 5])
        for message in messages[3:]:
            point = message['points'][0]
            edge = point['target_edges'][0]
            self.assertEqual(edge['point_id'], messages[1 if message['agent_id']=='P1' else 2]['points'][0]['point_id'])
            self.assertNotIn('_lineage_sources', point)
        gens = [req['data'] for stage, req in self.events if stage == 'turn-generate']
        self.assertTrue(all(g['QUESTION'] == final['plan']['question'] for g in gens))
        self.assertFalse(any(g['OTHER_CONTEXT_ONLY'] for g in gens[:2]))
        verified = [req['state'] for stage, req in self.events if stage == 'turn-verify']
        self.assertEqual([g['PHASE_TASK'] for g in gens], [v['PHASE_TASK'] for v in verified])
        self.assertIn('Leave peer responses', gens[0]['PHASE_TASK'])
        self.assertIn('each supplied peer target', gens[2]['PHASE_TASK'])
        self.assertEqual({p['message_id'] for g in gens[2:] for p in g['OWN_CONTEXT']+g['OTHER_CONTEXT_ONLY']},
                         {m['message_id'] for m in messages[1:3]})
        votes = [req['data'] for stage, req in self.events if stage == 'ratify-generate']
        self.assertEqual(votes[0]['CANDIDATES'], votes[1]['CANDIDATES'])
        self.assertEqual(votes[0]['DRAFT_SHA256'], votes[1]['DRAFT_SHA256'])
        self.assertFalse(any('VOTES' in v for v in votes))
        vote_reviews = [req for stage, req in self.events if stage == 'ratify-verify']
        for generation, review in zip(votes, vote_reviews, strict=True):
            state = review['state']
            self.assertEqual(state['DRAFT_SHA256'], generation['DRAFT_SHA256'])
            ballot = state['RATIFICATIONS']['A1']
            self.assertEqual(ballot['candidate'], generation['CANDIDATES']['A1'])
            self.assertEqual(list(ballot['reason_points']), [next(reversed(generation['OWN_POINTS']))])
            reason, = ballot['reason_points'].values()
            self.assertEqual(reason['origin'], 'ai_reasoning')
            self.assertNotIn('targets', reason)
            self.assertNotIn('OTHER_CONTEXT_ONLY', state)
            self.assertIn('RATIFICATIONS.A1', review['questions']['A1_stance']['instructions'])
        report_path = '/api/v1/syntheses/'+final['conclusion']['synthesis_id']
        report = self.call('GET', report_path)[1]
        self.assertEqual(report['outcome'], 'consensus_ready')
        self.assertEqual(report['shared_claims'][0]['accepting_agent_ids'], ['P2', 'P1'])
        self.assertEqual(report['root_source_count'], 1)
        self.assertEqual(report['direct_comment_support_count'], 0)
        self.assertEqual(report['shared_claims'][0]['member_source_count'], 0)
        with self.app.store.transaction() as db:
            room = room_at(db, final['room_id'])
            self.assertEqual(Decimal(room['cost_usd']), Decimal('0.007007'))
            self.assertEqual(db.execute('SELECT count(*) FROM ratifications').fetchone()[0], 2)
        agent_path = '/api/v1/synthesis-agents/'+report['agent_id']
        self.app.close()
        self.app = self.build()
        self.assertEqual(self.call('GET', path)[1], final)
        agent = self.call('GET', agent_path)[1]
        self.assertEqual(agent['kind'], 'derived_consensus')
        self.assertEqual(self.call('GET', agent_path+'/sources/'+agent['root_source_ids'][0])[0], 200)
        for private in (path, report_path, agent_path):
            with self.assertRaises(WebError) as err:
                self.call('GET', private, token=secrets.token_urlsafe(32))
            self.assertEqual(err.exception.status, 404)

        status, room = self.call('POST', agent_path+'/rooms', {
            'agent_revision': 1, 'initial_revision': 1, 'request_id': 'derived'})
        self.assertEqual(status, 201)
        room_path = '/api/v1/rooms/'+room['room_id']
        _, job = self.call('POST', room_path+'/start', {
            'opening_question': 'Where can this approach help?', 'expected_revision': room['revision'],
            'request_id': 'ask'})
        self.assertEqual(self.job(job)['state'], 'succeeded')
        after = self.call('GET', room_path)[1]
        self.assertEqual(after['messages'][-1]['points'][0]['origin'], 'ai_reasoning')
        self.assertEqual(after['messages'][-1]['agent_id'], agent['agent_id'])
        output = self.call('PUT', self.base+'/opinions/current', {'text': 'I still support checks.',
                           'expected_revision': 0, 'request_id': 'reply'})[1]
        mids = [messages[2]['message_id'], after['messages'][-1]['message_id']]
        _, reflect = self.call('POST', self.base+'/reflection-analyses', {
            'initial_revision': 1, 'current_revision': output['revision'], 'context_message_ids': mids,
            'request_id': 'reflect'})
        self.assertEqual(self.job(reflect)['result']['context_message_ids'], mids)
        self.assertNotIn('_lineage_sources', json.dumps(self.calls))
        self.assertEqual(len(self.events), 16)

    def test_draft_assessment_does_not_block_a_surviving_responsive_point(self):
        self.extra_opening_point = True
        turn = ('turn-verify', 'opening', 'P2')
        self.overrides[(*turn, 'answer')] = 'reject'
        self.overrides[(*turn, 'P2_basis')] = 'reject'
        _, final = self.complete()
        opening = final['messages'][1]
        self.assertEqual(opening['coverage'], 'complete')
        self.assertEqual(opening['answerability'], 'partial')
        self.assertEqual([p['task_fit'] for p in opening['points']], ['responsive'])
        self.assertEqual(final['state'], 'completed')

    def test_user_rate_scope_hold_keeps_valid_conversion_and_discards_changed_unit(self):
        query = 'Would you accept four workdays while keeping 40 hours per week?'
        convert = 'If work is split equally, four ten-hour days total 40 hours per week.'
        changed = 'I would support four forty-hour days.'

        def draft(stage, request):
            result = self.model(stage, request)
            scope = request['data']['DEBATE_SCOPE']
            if (stage, scope.get('phase'), scope.get('agent_id')) == ('turn-generate', 'opening', 'P2'):
                self.assertIn('rate denominators', request['system'])
                point = {**result['output']['points']['P1'], 'origin': 'ai_reasoning'}
                result['output']['points'].update(P1={**point, 'text':convert}, P2={**point, 'text':changed})
            return result

        self.app.model = draft
        path, debate = self.debate(question=query)
        self.assertEqual(self.job(self.start(path, debate)[1])['state'], 'succeeded')
        final = self.call('GET', path)[1]
        opening = final['messages'][1]
        self.assertEqual(opening['answerability'], 'partial')
        self.assertEqual([point['text'] for point in opening['points']], [convert])
        decision = next(req for stage, req in self.events if stage == 'turn-verify')
        self.assertEqual(decision['state']['QUESTION'], query)
        self.assertIn('rate denominators', decision['questions']['P1_scope']['instructions'])
        self.assertNotIn('P2', decision['state']['PROPOSED_POINTS'])
        proposals = next(req for stage, req in self.events if stage == 'draft-generate')
        self.assertNotIn(changed, json.dumps(proposals))

    def test_quantity_guard_is_limited_to_reused_weekly_values(self):
        question = 'What if four workdays maintain forty weekly hours?'
        for text in ('Working four forty-hour days might help.', 'I would compare four 40-hour workdays.',
                     'That means working 40 hours per day.', '그러면 하루 40시간 근무하게 됩니다.'):
            self.assertTrue(changes_weekly_hours(question, text), text)
        for text in ('Four ten-hour days still total 40 hours a week.',
                     'An alternative could be four eight-hour days for a 32-hour week.',
                     'This means four ten-hour days, not four forty-hour days.',
                     'One forty-hour workday would total 40 hours across the week.',
                     'Four forty-hour days would be a different scenario.',
                     'In a separate scenario, four forty-hour days would mean 160 hours a week.'):
            self.assertFalse(changes_weekly_hours(question, text), text)
        self.assertTrue(changes_weekly_hours('주당 36시간이면 조건이 달라지나요?', '하루 36시간입니다.'))
        self.assertFalse(changes_weekly_hours('Compare a 40-hour week and 40 hours per day.', '40 hours per day.'))
        self.assertFalse(changes_weekly_hours('Compare 32 hours a week and 40 hours a week.', '40 hours per day.'))

    def test_quantity_guard_holds_a_changed_synthesis_proposal_before_voting(self):
        query = 'What if weekly work stayed at 40 hours per week?'

        def draft(stage, request):
            output = self.model(stage, request)
            if stage == 'draft-generate':
                output['output']['candidates'][0]['text'] = 'Both support four 40-hour days.'
            return output

        self.app.model = draft
        path, debate = self.debate(question=query)
        self.assertEqual(self.job(self.start(path, debate)[1])['state'], 'succeeded')
        final = self.call('GET', path)[1]
        self.assertEqual(final['state'], 'verification_hold')
        self.assertIsNone(final['synthesis_agent'])
        self.assertNotIn('ratify-generate', [stage for stage, _ in self.events])

    def test_draft_assessment_still_applies_when_the_entire_draft_is_published(self):
        self.overrides[('turn-verify', 'opening', 'P2', 'answer')] = 'reject'
        _, final = self.complete()
        self.assertEqual(final['state'], 'incomplete')
        self.assertEqual(final['messages'][1]['coverage'], 'incomplete')

    def test_incomplete_reply_keeps_turns_and_skips_entire_agreement(self):
        self.overrides[('turn-verify', 'reply', 'P2', 'P1_task_fit')] = 'reject'
        _, final = self.complete()
        self.assertEqual(final['state'], 'incomplete')
        unanswered, = final['conclusion']['unanswered']
        self.assertEqual(unanswered['agent_id'], 'P2')
        self.assertEqual(unanswered['targets'][0]['agent_id'], 'P1')
        self.assertEqual(len(self.events), 8)
        self.assertIsNone(final['synthesis_agent'])

    def test_rejection_no_proposal_and_verification_hold_are_distinct(self):
        for mode, expected, calls in [('reject', 'completed_no_consensus', 14),
                                      ('empty', 'completed_no_proposal', 9),
                                      ('hold', 'verification_hold', 14)]:
            with self.subTest(mode=mode):
                self.events.clear()
                self.reject = {'P1'} if mode == 'reject' else set()
                self.no_proposal = mode == 'empty'
                self.overrides = {('ratify-verify', 'synthesizing', 'P1', 'A1_basis'): 'uncertain'} if mode == 'hold' else {}
                path, debate = self.debate(request_id=mode)
                self.assertEqual(self.job(self.start(path, debate)[1])['state'], 'succeeded')
                state = self.call('GET', path)[1]
                self.assertEqual(state['state'], expected)
                self.assertIsNone(state['synthesis_agent'])
                self.assertEqual(len(self.events), calls)
                if mode == 'reject':
                    self.assertTrue(any(d['relation'] == 'reject' for d in state['conclusion']['disagreements']))

    def test_three_participants_partial_conflict_and_exact_prepared_passage(self):
        self.use_reference = True
        self.pair_conflict = True
        _, final = self.complete(('P3', 'P2', 'P1'))
        self.assertEqual(final['plan']['max_physical_calls'], 20)
        self.assertEqual(len(self.events), 20)
        report = self.call('GET', '/api/v1/syntheses/'+final['conclusion']['synthesis_id'])[1]
        self.assertEqual(report['outcome'], 'consensus_ready')
        self.assertEqual(len(report['held_claim_ids']), 2)
        accepted, = report['shared_claims']
        self.assertEqual(accepted['accepting_agent_ids'], ['P3', 'P2', 'P1'])
        passage, = accepted['citations']['external_evidence']
        self.assertEqual(passage['span']['text'], self.analysis.bundle['documents'][0]['text'])

    def test_pause_checkpoints_response_and_resume_uses_it_once(self):
        path, debate = self.debate()
        waiting, release = threading.Event(), threading.Event()
        def blocked(stage, request):
            waiting.set()
            if not release.wait(5):
                raise AssertionError('Test did not release the worker')
            return self.model(stage, request)
        self.app.model = blocked
        _, first = self.start(path, debate)
        try:
            self.assertTrue(waiting.wait(5))
            self.assertEqual(self.control(path, 'pause')[1]['state'], 'pausing')
        finally:
            release.set()
        self.job(first)
        self.assertEqual(self.call('GET', path)[1]['state'], 'paused')
        self.assertEqual([stage for stage, _ in self.events], ['turn-generate'])
        self.assertEqual(self.job(self.control(path, 'resume')[1])['state'], 'succeeded')
        self.assertEqual(self.call('GET', path)[1]['state'], 'completed')
        self.assertEqual(len(self.events), 14)
        self.assertEqual(self.start(path, debate)[0], 200)
        self.assertEqual(len(self.events), 14)

    def test_close_suppresses_late_delivery_but_settles_it(self):
        path, debate = self.debate()
        waiting, release = threading.Event(), threading.Event()
        def blocked(stage, request):
            waiting.set()
            if not release.wait(5):
                raise AssertionError('Test did not release the worker')
            return self.model(stage, request)
        self.app.model = blocked
        _, job = self.start(path, debate)
        try:
            self.assertTrue(waiting.wait(5))
            self.assertEqual(self.control(path, 'close')[1]['state'], 'closing')
        finally:
            release.set()
        self.assertEqual(self.job(job)['state'], 'cancelled')
        final = self.call('GET', path)[1]
        self.assertEqual(final['state'], 'closed')
        self.assertEqual(len(final['messages']), 1)
        self.assertFalse(final['turn_count'])
        with self.app.store.transaction() as db:
            self.assertEqual(Decimal(room_at(db, final['room_id'])['cost_usd']), Decimal('0.001'))

    def test_preflight_checks_whole_debate_allowlist_and_detects_expiry(self):
        self.app.room_limit = Decimal('0.020')
        for selected in [('P1',), ('P1', 'P1'), ('P1', 'foreign'), ('P1', 'P2', 'P3', 'P4')]:
            with self.assertRaises(WebError) as err:
                self.debate(selected)
            self.assertEqual(err.exception.code, 'invalid_participants')
        self.assertEqual(len(self.analysis.public()['perspectives']), 4)
        path, debate = self.debate()
        with self.assertRaises(WebError) as err:
            self.call('POST', '/api/v1/rooms/'+debate['room_id']+'/start', {
                'opening_question': 'Changed', 'expected_revision': debate['revision'], 'request_id': 'wrong'})
        self.assertEqual(err.exception.code, 'debate_controls_required')
        with self.assertRaises(WebError) as err:
            self.start(path, debate)
        self.assertEqual(err.exception.code, 'budget_exhausted')
        self.analysis.bundle['expires_at'] = '2020-01-01T00:00:00Z'
        with self.assertRaises(WebError) as err:
            self.start(path, debate)
        self.assertEqual(err.exception.status, 410)
        self.assertFalse(self.events)
        self.assertEqual(self.call('GET', path)[1]['last_seq'], 0)

    def test_shared_ledger_preflight_is_checked_before_queueing(self):
        self.app.debate_balance = lambda: '0.020'
        path, debate = self.debate()
        with self.assertRaises(WebError) as err:
            self.start(path, debate)
        self.assertEqual(err.exception.code, 'budget_exhausted')
        self.assertFalse(self.events)
        self.assertEqual(self.call('GET', path)[1]['state'], 'idle')

    def test_unknown_charge_preserves_settled_generation_and_blocks_resubmission(self):
        def unknown(stage, payload):
            result = self.decide(stage, payload)
            result.pop('usage')
            return result
        self.app.decision = unknown
        path, debate = self.debate()
        _, job = self.start(path, debate)
        self.assertEqual(self.job(job)['state'], 'needs_reconciliation')
        final = self.call('GET', path)[1]
        self.assertEqual(final['state'], 'needs_reconciliation')
        self.assertEqual(final['turn_count'], 0)
        with self.app.store.transaction() as db:
            room = room_at(db, final['room_id'])
            self.assertEqual(Decimal(room['cost_usd']), Decimal('0.001'))
            self.assertTrue(room['_stages'])
        self.assertEqual(self.start(path, debate)[0], 200)
        self.assertEqual(len(self.events), 2)

    def test_existing_v1_session_and_room_survive_migration(self):
        _, room = self.call('POST', self.base+'/rooms', {'mode': 'one_to_one', 'participant_ids': ['P1'],
            'initial_revision': 1, 'request_id': 'legacy'})
        with self.app.store.transaction() as db:
            for table in ('synthesis_agents', 'ratifications', 'syntheses', 'debates'):
                db.execute('DROP TABLE '+table)
            db.execute('UPDATE version SET schema_version=1')
        self.app.close()
        self.app = self.build()
        with self.app.store.transaction() as db:
            self.assertEqual(db.execute('SELECT schema_version FROM version').fetchone()[0], 2)
        self.assertEqual(self.call('GET', '/api/v1/rooms/'+room['room_id'])[1], room)
        self.assertEqual(self.call('GET', self.base)[1]['initial_opinion']['revision'], 1)
        self.assertFalse(self.events)
