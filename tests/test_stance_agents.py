from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from commentscope.factory import position_frames as f, framed_clusters as clusters
from commentscope.factory import stance_membership as s, framed_agents as a
from commentscope.ingestion import load_snapshot
from commentscope.agents.grounded_runtime import GroundedSession
from experiments.grounding_contract_demo import MODEL, response


class Runner:
    def __init__(self, *, ground_kind='value', missing_premise=False, essential=False):
        self.calls = []; self.ground_kind = ground_kind
        self.missing_premise = missing_premise; self.essential = essential

    def call(self, stage, req):
        self.calls.append((stage, req))
        if stage == 'argument-core-type': value = {'kind': 'value'}
        elif stage == 'argument-select':
            parts = next(iter(req['data']['SOURCE_SEGMENTS'].values()))
            ids = [p['node_id'] for p in parts if p['eligible']][-1:]
            value = {'status': 'selected', 'node_ids': ids, 'essential_node_ids': ids if self.essential else []}
        elif stage.startswith('argument-ground-type-'): value = {'kind': self.ground_kind}
        elif stage == 'argument-audit':
            value = {'core_fidelity': 'faithful', 'core_kind_matches': True,
                     'major_premises': 'missing' if self.missing_premise else 'preserved',
                     'grounds': [{'node_id': n['node_id'], 'role': 'reason_for_core', 'kind_matches': True}
                                 for n in req['data']['SELECTED_GROUNDS']]}
        else: raise AssertionError(stage)
        return {'errors': [], 'output': value}


class StanceAgentTests(unittest.TestCase):
    def setUp(self):
        template = load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        texts = ['Adopt policy P. Equity matters.', 'Adopt policy P. Freedom matters.',
                 'Adopt policy P. Fairness matters.', 'Adopt policy P only if funding is secured.',
                 'Do not adopt policy P.']
        self.snapshot = replace(template, usage=replace(template.usage, expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(template.comments[0], comment_id=f's{i}', text_original=t) for i, t in enumerate(texts)))
        self.frames = [f.bind(f.source_packet(self.snapshot, c.comment_id), {'output': {'status': 'positions',
            'positions': [{'target': 'policy P', 'statement': c.text_original, 'mode': 'normative',
                           'entity': 'policy P', 'time': '', 'segment_ids': ['S000'],
                           'qualifications': [], 'reasons': []}]}}) for c in self.snapshot.comments]
        contract = {'target': 'policy P', 'statement': 'Adopt policy P.', 'entity': 'policy P', 'time': '', 'conditions': ''}
        self.candidate = clusters.proposals(self.frames, {'output': {'candidates': [{
            'contract': contract, 'nominees': [r['positions'][0]['id'] for r in self.frames[:3]]}]}})[0]
        self.memberships = [self.member(i, relation) for i, relation in enumerate(
            ['supported', 'supported', 'supported', 'conditional', 'opposed'])]

    def member(self, i, relation='supported', **extra):
        value = {'relation': relation, 'authorship': 'asserted_or_endorsed',
                 'scope_preserved': 'no' if relation == 'conditional' else 'yes', 'evidence_segment_ids': ['S000']}
        value.update(extra)
        return s.bind(f.source_packet(self.snapshot, f's{i}'), self.candidate, {'output': value})

    def analyses(self, runner=None):
        return a.prepare_arguments(self.snapshot, self.frames, [self.candidate], self.memberships, runner or Runner())

    def output(self, analyses=None, **kwargs):
        return a.bundle(self.snapshot, self.frames, [self.candidate], self.memberships,
                        self.analyses() if analyses is None else analyses, model=MODEL, **kwargs)

    def test_admission_does_not_import_extracted_reasons_or_labels(self):
        req = s.invocation(f.source_packet(self.snapshot, 's0'), self.candidate)
        self.assertEqual(set(req['data']), {'SOURCE_ID', 'ORIGINAL_SEGMENTS', 'PARENT_CONTEXT', 'CANDIDATE'})
        self.assertEqual(''.join(p['text'] for p in req['data']['ORIGINAL_SEGMENTS']), self.snapshot.comments[0].text_original)
        self.assertNotIn('expected', str(req))
        self.assertNotIn('frame_fidelity', str(req))

    def test_source_once_and_conditional_not_support(self):
        mapped = s.assemble_map(self.snapshot, self.frames, [self.candidate], self.memberships)
        p = mapped['opinion_map']['perspectives'][0]
        self.assertEqual(p['counts'], {'supported': 3, 'conditional': 1, 'not_supported': 1, 'uncertain': 0, 'unassessed': 0})
        self.assertFalse(mapped['quality_gate_passed'])

    def test_scope_and_author_guards(self):
        for kwargs in ({'scope_preserved': 'no'}, {'scope_preserved': 'unclear'},
                       {'authorship': 'not_asserted'}, {'authorship': 'unclear'}):
            with self.subTest(kwargs=kwargs): self.assertEqual(self.member(0, **kwargs)['relation'], 'uncertain')

    def test_failed_or_fabricated_original_evidence_rejected(self):
        for ids in ([], ['missing'], ['S000', 'S000']):
            with self.subTest(ids=ids), self.assertRaises(ValueError): self.member(0, evidence_segment_ids=ids)
        with self.assertRaises(ValueError):
            s.bind(f.source_packet(self.snapshot, 's0'), self.candidate, {'errors': ['timeout']})

    def test_judgment_bindings_and_duplicates_checked(self):
        for field in ('source_sha256', 'candidate_sha256', 'request_sha256'):
            changed = deepcopy(self.memberships); changed[0][field] = 'bad'
            with self.subTest(field=field), self.assertRaises(ValueError):
                s.assemble_map(self.snapshot, self.frames, [self.candidate], changed)
        with self.assertRaises(ValueError):
            s.assemble_map(self.snapshot, self.frames, [self.candidate], self.memberships * 2)

    def test_missing_judgment_is_unassessed_not_negative(self):
        out = s.assemble_map(self.snapshot, self.frames, [self.candidate], self.memberships[:2])
        self.assertEqual(out['opinion_map']['perspectives'][0]['counts']['unassessed'], 3)

    def test_each_authors_ground_is_retained_not_two_for_whole_cluster(self):
        out = self.output(); profile = out['compiled']['profiles'][0]
        self.assertEqual(profile['model_core_support_count'], 3)
        reasons = [r for r in profile['prompt_entries'] if r['claim_id'] != profile['core_claim_id']]
        self.assertEqual(len(reasons), 3)
        self.assertEqual({r['member_source_count'] for r in reasons}, {1})
        self.assertEqual({r['text'].strip() for r in reasons}, {'Equity matters.', 'Freedom matters.', 'Fairness matters.'})
        for r in reasons:
            self.assertEqual(len(profile['citations'][r['claim_id']]['comment_evidence']), 1)
        self.assertFalse(out['quality_gate_passed']); self.assertFalse(out['runtime_verified'])

    def test_single_bad_argument_defers_agent_without_rewriting_support_map(self):
        out = self.output(self.analyses(Runner(missing_premise=True)))
        self.assertEqual(out['compiled']['profiles'], [])
        self.assertEqual(out['argument_deferrals'][0]['reason'], 'member_arguments_incomplete')
        self.assertEqual(out['map']['opinion_map']['perspectives'][0]['counts']['supported'], 3)

    def test_missing_analysis_never_silently_omits_member(self):
        out = self.output(self.analyses()[:2])
        self.assertFalse(out['compiled']['profiles'])
        self.assertEqual(out['argument_deferrals'][0]['unassessed_source_ids'], ['s2'])

    def test_unverified_essential_fact_defers_and_preserves_dependency(self):
        out = self.output(self.analyses(Runner(ground_kind='fact', essential=True)))
        self.assertFalse(out['compiled']['profiles'])
        core = next(c for c in out['bundle']['claims'] if c['id'].endswith(':C'))
        self.assertEqual(len(core['requires']), 3)
        self.assertEqual(len(out['bundle']['candidates'][0]['major_fact_ids']), 3)
        self.assertEqual(out['compiled']['deferred'][0]['reason'], 'required_premise_unavailable')

    def test_mixed_ground_not_retyped_to_rescue_candidate(self):
        out = self.output(self.analyses(Runner(ground_kind='mixed_or_unclear')))
        self.assertFalse(out['compiled']['profiles'])

    def test_changed_analysis_text_kind_source_or_stage_fails(self):
        original = self.analyses()
        for mutate in (lambda r: r['typed']['claims']['R1'].update(text='Invented reason'),
                       lambda r: r['typed']['claims']['C'].update(kind='fact'),
                       lambda r: r.update(source_id='s4'),
                       lambda r: r['stages'][0].update(request_sha256='bad'),
                       lambda r: r['stages'].pop()):
            changed = deepcopy(original); mutate(changed[0])
            with self.assertRaises(ValueError): self.output(changed)

    def test_two_members_do_not_trigger_argument_calls(self):
        self.memberships = self.memberships[:2]
        runner = Runner(); analyses = self.analyses(runner)
        self.assertFalse(analyses); self.assertFalse(runner.calls)
        out = self.output(analyses)
        self.assertEqual(out['argument_deferrals'][0]['reason'], 'fewer_than_three_core_sources')

    def test_runtime_loads_cites_and_keeps_separate_history(self):
        out = self.output(); cid = self.candidate['id']; core_id = cid + ':C'
        provider = lambda system, data, schema, **kwargs: response({
            'answerability': 'grounded', 'claim_ids': [data['PERSPECTIVE']['core_claim_id']], 'limitation': 'none'})
        one = GroundedSession(out['bundle'], cid, provider=provider)
        two = GroundedSession(out['bundle'], cid, provider=provider)
        answer = one.ask('What is the position?')
        self.assertEqual(answer['status'], 'answered')
        self.assertEqual(answer['points'][0]['text'], 'Adopt policy P.')
        self.assertEqual(len(answer['points'][0]['citations']['comment_evidence']), 3)
        self.assertEqual(len(one.history), 1); self.assertEqual(two.history, [])

    def test_parent_context_never_becomes_ground_inventory_or_support_vote(self):
        source = f.source_packet(self.snapshot, 's0'); source['parent'] = {'id': 'parent', 'text': 'Outside reason.'}
        runner = Runner(); a.analyse_source(source, self.candidate, runner)
        for _, req in runner.calls:
            self.assertEqual(req['data']['PARENT_CONTEXT_ONLY'], source['parent'])
            if 'SOURCE_SEGMENTS' in req['data']: self.assertEqual(set(req['data']['SOURCE_SEGMENTS']), {'s0'})

    def test_no_fixed_six_candidate_cap(self):
        # Authored decisions test only scheduling/count limits, not semantics.
        candidates = []; memberships = []
        for i in range(7):
            contract = {**self.candidate['contract'], 'target': f'synthetic target {i}'}
            candidate = clusters.proposals(self.frames, {'output': {'candidates': [{
                'contract': contract, 'nominees': self.candidate['nominees']}]}})[0]
            candidates.append(candidate)
            for row in self.memberships[:3]:
                source = f.source_packet(self.snapshot, row['source_id'])
                memberships.append(s.bind(source, candidate, {'output': row['decision']}))
        analyses = a.prepare_arguments(self.snapshot, self.frames, candidates, memberships, Runner())
        out = a.bundle(self.snapshot, self.frames, candidates, memberships, analyses, model=MODEL)
        self.assertEqual(len(out['compiled']['profiles']), 7)

    def test_conditional_candidate_scope_survives_compilation(self):
        contract = {**self.candidate['contract'], 'conditions': 'only if funding is secured'}
        self.candidate = clusters.proposals(self.frames, {'output': {'candidates': [{
            'contract': contract, 'nominees': self.candidate['nominees']}]}})[0]
        self.memberships = [self.member(i) for i in range(3)]
        out = self.output()
        entry = next(e for e in out['compiled']['profiles'][0]['prompt_entries'] if e['claim_id'].endswith(':C'))
        self.assertEqual(entry['scope']['conditions'], 'only if funding is secured')


if __name__ == '__main__': unittest.main()
