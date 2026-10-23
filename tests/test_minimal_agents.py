from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import unittest

from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory import source_arguments as sa, minimal_agents as ma
from commentscope.factory.automatic_contract import digest
from commentscope.agents.grounded_runtime import GroundedSession
from commentscope.ingestion import load_snapshot
from commentscope.providers.context_capacity import measure, partition
from experiments.grounding_contract_demo import MODEL
from test_minimal_factory import extraction, membership


class MinimalAgentTests(unittest.TestCase):
    def setUp(self):
        texts = ['Adopt P. Equity matters.', 'Adopt P. Freedom matters.', 'Adopt P. Fairness matters.']
        self.sources = [{'id': f's{i}', 'text': t, 'parent': None} for i, t in enumerate(texts)]
        self.candidates = mc.candidates(extraction(self.sources, {s['id']: ['Adopt P.'] for s in self.sources}))
        self.cid = self.candidates[0]['id']
        self.members = [membership(self.sources, self.candidates, [{'source_id': s['id'], 'candidate_id': self.cid} for s in self.sources])]
        self.cores = [sa.bind_core(self.candidates[0], {'output': {'kind': 'value', 'scope': {'entity': 'P', 'time': '', 'conditions': ''}}})]
        self.value = {'sources': [{'source_id': s['id'], 'source_language': 'en', 'status': 'complete', 'units': [
            {'local_id': 'U1', 'text': s['text'].split('. ')[1], 'kind': 'value',
             'scope': {'entity': 'P', 'time': '', 'conditions': ''}, 'role': 'reason', 'candidate_ids': [self.cid],
             'requires': [], 'core_requires_for': [], 'evidence_segment_ids': ['S001']}]} for s in self.sources]}
        template = load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        self.snapshot = replace(template, usage=replace(template.usage, expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(template.comments[0], comment_id=s['id'], text_original=s['text'], parent_id=None) for s in self.sources))

    def records(self, *, linked=True):
        raw=deepcopy(self.value)
        links={s['source_id']:[{k:u[k] for k in ('local_id','requires','core_requires_for')} for u in s['units']]
               for s in raw['sources']}
        for source in raw['sources']:
            for unit in source['units']:
                unit.pop('requires');unit.pop('core_requires_for')
        records=sa.bind(self.sources, self.candidates, self.members, {'output': raw})
        if not linked:return records
        return [sa.bind_links(r,{'output':{'status':'complete','links':links[r['source']['id']]}}
                              if sa.link_request(r) else None) for r in records]

    def audits(self, records, *, bad=None):
        tasks = sa.audit_tasks(records, self.cores)
        return [sa.bind_audit(records, self.cores, tasks, {'output': {'decisions': [
            {'task_id': t['task_id'], 'verdict': 'uncertain' if t['task_id'] == bad else 'supported'} for t in tasks]}})]

    def prepare(self, records=None, audits=None):
        records = self.records() if records is None else records
        return ma.prepare(self.snapshot, self.candidates, self.members, records, self.cores,
                          self.audits(records) if audits is None else audits, model=MODEL)

    def test_distinct_reasons_remain_single_source_not_common_preconditions(self):
        out = self.prepare(); profile = out['compiled']['profiles'][0]
        core = next(c for c in out['bundle']['claims'] if c['id'].endswith(':C'))
        self.assertEqual(core['requires'], [])
        self.assertEqual(profile['model_core_support_count'], 3)
        reasons = [e for e in profile['prompt_entries'] if e['claim_id'] != core['id']]
        self.assertEqual(len(reasons), 3)
        self.assertEqual({r['member_source_count'] for r in reasons}, {1})
        self.assertEqual({r['text'] for r in reasons}, {'Equity matters.', 'Freedom matters.', 'Fairness matters.'})
        self.assertFalse(out['runtime_verified']); self.assertFalse(out['quality_gate_passed'])

    def test_missing_member_or_coverage_audit_holds_entire_candidate(self):
        records = self.records()[:-1]
        out = self.prepare(records)
        self.assertFalse(out['compiled']['profiles'])
        self.assertIn('member_arguments_unassessed', out['argument_holds'][0]['reasons'])
        out = self.prepare(audits=[])
        self.assertFalse(out['compiled']['profiles'])
        self.assertEqual(out['map']['opinion_map']['perspectives'][0]['counts']['supported'], 3)

    def test_private_single_source_draft_exposes_facts_for_checks_without_becoming_an_agent(self):
        records=self.records()[:1]
        members=[membership(self.sources,self.candidates,[{'source_id':self.sources[0]['id'],'candidate_id':self.cid}])]
        audits=self.audits(records)
        draft=ma.prepare(self.snapshot,self.candidates,members,records,self.cores,audits,model=MODEL,_draft_single_source=True)
        self.assertFalse(draft['compiled']['profiles'])
        self.assertEqual(len(draft['bundle']['candidates']),1)
        self.assertTrue(draft['bundle']['claims'])
        normal=ma.prepare(self.snapshot,self.candidates,members,records,self.cores,audits,model=MODEL)
        self.assertFalse(normal['compiled']['profiles']);self.assertFalse(normal['bundle']['candidates'])
        with self.assertRaises(ValueError):
            ma.prepare(self.snapshot,self.candidates,self.members,self.records(),self.cores,self.audits(self.records()),
                model=MODEL,_draft_single_source=True)

    def test_failed_unit_or_partial_source_never_becomes_agent(self):
        records = self.records(); bad = records[0]['units'][0]['id']
        self.assertFalse(self.prepare(records, self.audits(records, bad=bad))['compiled']['profiles'])
        self.value['sources'][0]['status'] = 'partial'
        self.assertFalse(self.prepare()['compiled']['profiles'])

    def test_core_condition_and_fact_cannot_be_erased_by_adapter(self):
        # Actual scoped declarations, not fake fields added to a legacy frame.
        self.cores = [sa.bind_core(self.candidates[0], {'output': {'kind': 'fact',
            'scope': {'entity': 'P', 'time': '2026', 'conditions': 'only if funded'}}})]
        out = self.prepare()
        self.assertFalse(out['compiled']['profiles'])
        core = next(c for c in out['bundle']['claims'] if c['id'].endswith(':C'))
        self.assertEqual(core['scope']['conditions'], 'only if funded')
        self.assertEqual(out['compiled']['deferred'][0]['reason'], 'fact_unassessed')

    def test_personal_factual_dependency_stays_on_own_reason(self):
        unit = self.value['sources'][0]['units'][0]
        unit['requires'] = ['U2']
        self.value['sources'][0]['units'].append({**deepcopy(unit), 'local_id': 'U2', 'text': 'P costs one dollar.',
                                                'kind': 'fact', 'requires': [], 'role': 'factual_premise'})
        out = self.prepare()
        core = next(c for c in out['bundle']['claims'] if c['id'].endswith(':C'))
        reason = next(c for c in out['bundle']['claims'] if c['text'] == 'Equity matters.')
        self.assertEqual(core['requires'], []); self.assertEqual(len(reason['requires']), 1)
        # No rescue by deleting the sole declared major fact.
        self.assertFalse(out['compiled']['profiles'])
        self.assertEqual(out['compiled']['deferred'][0]['reason'], 'no_verified_major_fact')

    def test_actual_common_factual_dependency_defers_core(self):
        unit = self.value['sources'][0]['units'][0]
        unit.update(kind='fact', core_requires_for=[self.cid])
        out = self.prepare(); core = next(c for c in out['bundle']['claims'] if c['id'].endswith(':C'))
        self.assertEqual(len(core['requires']), 1)
        self.assertFalse(out['compiled']['profiles'])
        self.assertEqual(out['compiled']['deferred'][0]['reason'], 'required_premise_unavailable')

    def test_non_english_fact_stays_held_without_translation_pipeline(self):
        self.value['sources'][0]['source_language'] = 'other'
        self.value['sources'][0]['units'][0]['kind'] = 'fact'
        out = self.prepare()
        self.assertIn('fact_source_language_unsupported', out['argument_holds'][0]['reasons'])
        self.assertFalse(out['compiled']['profiles'])

    def test_invalid_dependency_and_other_source_link_rejected(self):
        for key, value in [('candidate_ids', ['outside']), ('requires', ['U2']), ('core_requires_for', [self.cid])]:
            changed = deepcopy(self.value); changed['sources'][0]['units'][0][key] = value
            with self.assertRaises(ValueError): sa.bind(self.sources, self.candidates, self.members, {'output': changed})
        changed = deepcopy(self.value); changed['sources'][0]['units'][0].update(kind='fact', requires=['U1'])
        with self.assertRaises(ValueError): sa.bind(self.sources, self.candidates, self.members, {'output': changed})

    def test_additional_argument_pass_exactly_once(self):
        self.value['sources'][0]['status'] = 'partial'
        records = self.records(linked=False); first = records[:1]
        extra = {'sources': [{'source_id': 's0', 'source_language': 'en', 'status': 'complete', 'units': []}]}
        final = sa.bind(self.sources[:1], self.candidates, self.members, {'output': extra}, first)
        self.assertEqual(final[0]['units'], first[0]['units']); sa.validate(final[0])
        with self.assertRaises(ValueError): sa.extraction_request(self.sources[:1], self.candidates, self.members, final)

    def test_complete_stance_without_reason_is_not_invented(self):
        for source in self.value['sources']: source['units'] = []
        out = self.prepare()
        self.assertEqual(len(out['compiled']['profiles']), 1)
        self.assertEqual(len(out['compiled']['profiles'][0]['prompt_entries']), 1)

    def test_unassessed_dependency_graph_cannot_enter_agent_or_audit(self):
        raw=self.records(linked=False)
        with self.assertRaises(ValueError):self.prepare(raw,[])
        with self.assertRaises(ValueError):sa.audit_tasks(raw,self.cores)
        self.assertNotIn('requires',raw[0]['units'][0])

    def test_graph_only_links_local_facts_and_missing_premises_hold(self):
        self.value['sources'][0]['units'][0]['kind']='fact'
        raw=self.records(linked=False)[0]
        self.assertIsNotNone(sa.link_request(raw))
        with self.assertRaises(ValueError):sa.bind_links(raw)
        for requires in (['U1'],['outside']):
            with self.assertRaises(ValueError):sa.bind_links(raw,{'output':{'status':'complete','links':[
                {'local_id':'U1','requires':requires,'core_requires_for':[]}]}})
        linked=sa.bind_links(raw,{'output':{'status':'unresolved','links':[
            {'local_id':'U1','requires':[],'core_requires_for':[]}]}})
        records=[linked,*self.records()[1:]]
        out=self.prepare(records)
        self.assertIn('member_dependencies_unresolved',out['argument_holds'][0]['reasons'])

    def test_concession_and_separate_request_roles_survive_runtime(self):
        self.value['sources'][0]['units'][0]['role']='concession'
        self.value['sources'][1]['units'][0]['role']='additional_position'
        out=self.prepare();session=GroundedSession(out['bundle'],self.cid)
        entries=session.invocation('What are the available considerations?')['data']['PERSPECTIVE']['allowed_entries']
        roles={e['text']:e['declared_role'] for e in entries}
        self.assertEqual(roles['Equity matters.'],'concession')
        self.assertEqual(roles['Freedom matters.'],'additional_position')
        self.assertEqual(roles['Fairness matters.'],'reason')
        chosen=next(e['claim_id'] for e in entries if e['declared_role']=='concession')
        session.provider=lambda *a,**kw: {'choices':[{'message':{'content':json.dumps(
            {'answerability':'grounded','claim_ids':[chosen],'limitation':'none'})},'finish_reason':'stop'}]}
        self.assertEqual(session.ask('What concession is given?')['points'][0]['declared_role'],'concession')
        changed=deepcopy(out['bundle']);changed['candidates'][0]['argument_roles'].clear()
        with self.assertRaises(ValueError):GroundedSession(changed,self.cid)

    def test_audit_or_core_hash_mutation_rejected(self):
        records = self.records(); audits = self.audits(records)
        audits[0]['cores_sha256'] = 'bad'
        with self.assertRaises(ValueError): self.prepare(records, audits)
        self.cores[0]['output']['kind'] = 'prediction'
        with self.assertRaises(ValueError): self.prepare()

    def test_existing_runtime_loads_and_keeps_independent_history(self):
        out = self.prepare(); cid = self.cid
        def provider(system, data, schema, max_tokens):
            value = ({'answerability': 'not_in_evidence', 'claim_ids': [], 'limitation': 'missing_evidence'}
                     if 'cost' in data['QUESTION'] else
                     {'answerability': 'grounded', 'claim_ids': [data['PERSPECTIVE']['core_claim_id']], 'limitation': 'none'})
            return {'choices': [{'message': {'content': json.dumps(value)}, 'finish_reason': 'stop'}]}
        one = GroundedSession(out['bundle'], cid, provider=provider)
        two = GroundedSession(out['bundle'], cid, provider=provider)
        turn = one.ask('What is the position?')
        self.assertEqual(turn['status'], 'answered')
        self.assertEqual(len(turn['points'][0]['citations']['comment_evidence']), 3)
        self.assertEqual(one.ask('What is the cost?')['status'], 'abstain')
        self.assertEqual(two.history, [])

    def test_three_long_claim_ids_use_short_addresses_then_restore_exact_ids(self):
        out=self.prepare();session=GroundedSession(out['bundle'],self.cid)
        request=session.invocation('What reasons are provided?')
        self.assertEqual(request['max_tokens'],180)
        entries=request['data']['PERSPECTIVE']['allowed_entries']
        selected=[e['claim_id'] for e in entries if e['declared_role']=='reason']
        self.assertEqual(len(selected),3)
        self.assertTrue(all(len(cid)<=3 for cid in selected))
        canonical={c['id'] for c in out['bundle']['claims'] if not c['id'].endswith(':C')}
        self.assertTrue(all(len(cid)>60 for cid in canonical))
        self.assertTrue(all(cid not in json.dumps(request) for cid in canonical))
        session.provider=lambda *a,**kw:{'choices':[{'message':{'content':json.dumps(
            {'answerability':'grounded','claim_ids':selected,'limitation':'none'})},'finish_reason':'stop'}]}
        turn=session.ask('What reasons are provided?')
        self.assertEqual({p['claim_id'] for p in turn['points']},canonical)
        self.assertEqual(set(session.history[-1]['selected_claim_ids']),canonical)
        self.assertEqual(session.invocation('And those?')['data']['HISTORY'][-1]['selected_claim_ids'],selected)


class CapacityTests(unittest.TestCase):
    def test_actual_template_with_schema_and_output_reservation(self):
        calls = []
        def transport(path, value):
            calls.append((path, value))
            return {'prompt': 'actual template'} if path == '/apply-template' else {'tokens': [1]*5000}
        req = mc.extraction_request([{'id': 'a', 'text': 'Do not cut this original.', 'parent': None}])
        measured = measure(req, transport=transport)
        self.assertFalse(measured['fits'])  # 5000 +3072 +256 >8192.
        self.assertIn('Required JSON schema', calls[0][1]['messages'][0]['content'])
        self.assertEqual(calls[1][1]['content'], 'actual template')
        self.assertTrue(calls[1][1]['parse_special'])

    def test_split_or_hold_singleton_never_truncates_or_calls_generation(self):
        items = ['a', 'b', 'long']
        def build(group): return {'items': group[:]}
        def inspect(req): return {'request_sha256': digest(req), 'fits': len(req['items']) == 1 and req['items'] != ['long']}
        fitted, deferred = partition(items, build, inspect)
        self.assertEqual([r['items'] for r in fitted], [['a'], ['b']])
        self.assertEqual(deferred[0]['item'], 'long')
        self.assertEqual(items, ['a', 'b', 'long'])


if __name__ == '__main__': unittest.main()
