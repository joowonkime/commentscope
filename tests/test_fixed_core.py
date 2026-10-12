from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from commentscope.factory import fixed_core as f
from experiments import fixed_core_probe as p


def fixture():
    sources = [{'source_id': str(i), 'text': text} for i,text in enumerate(['Costs may rise.', 'Prices may rise.', 'Costs could rise.'])]
    units = [{'id': 'U'+s['source_id'], 'source_id': s['source_id'], 'statement': s['text'],
              'spans': [{'start': 0, 'end': len(s['text']), 'text': s['text']}]} for s in sources]
    vectors = [[1.,0.],[.9,.1],[.8,.2]]
    groups = [{'id': 'C1', 'unit_ids': [u['id'] for u in units], 'source_ids': ['0','1','2']}]
    return units, vectors, groups, sources


def supported(*args):
    return {'verdict': 'supported', 'errors': [], 'reason': 'Fixture only.'}


class FixedCoreTests(unittest.TestCase):
    def test_deterministic_immutable_candidates_not_support(self):
        args = fixture(); original = deepcopy(args)
        result = f.select_cores(*args)
        self.assertEqual(args, original)
        self.assertEqual(result, f.select_cores(*args))
        self.assertEqual(len(result['cores']), 3)
        self.assertEqual(result['agents'], [])
        for c in result['cores']:
            self.assertIn(c['text'], [u['statement'] for u in args[0]])

    def test_permuted_unit_order_keeps_selection(self):
        units, vectors, groups, sources = fixture()
        self.assertEqual(f.select_cores(units, vectors, groups, sources),
                         f.select_cores(units[::-1], vectors[::-1], groups, sources))

    def test_exact_duplicate_targets_selected_once(self):
        units, vectors, groups, sources = fixture()
        for u in units: u['statement'] = 'Costs may rise.'
        self.assertEqual(len(f.select_cores(units, vectors, groups, sources)['cores']), 1)

    def test_single_source_never_multisource(self):
        units, vectors, groups, sources = fixture()
        units = [deepcopy(units[0]) for _ in range(3)]
        for i,u in enumerate(units): u['id'] = 'U'+str(i)
        groups[0]['source_ids'] = ['0']
        result = f.select_cores(units, vectors, groups, sources)
        self.assertEqual(result['cores'], [])
        self.assertEqual(result['skipped'][0]['reason'], 'single_source')

    def test_bad_vectors_and_span_fail(self):
        for bad in [[[1],[1],[0]], [[1],[1,0],[1]], [[float('nan')],[1],[1]], []]:
            u,v,g,s = fixture()
            with self.assertRaises(ValueError): f.select_cores(u,bad,g,s)
        u,v,g,s = fixture();u[0]['spans'][0]['text'] = 'invented'
        with self.assertRaises(ValueError): f.select_cores(u,v,g,s)

    def test_bad_source_and_duplicate_unit_fail(self):
        u,v,g,s = fixture();g[0]['source_ids'] = ['0']
        with self.assertRaises(ValueError): f.select_cores(u,v,g,s)
        u,v,g,s = fixture();g[0]['unit_ids'].append('U0')
        with self.assertRaises(ValueError): f.select_cores(u,v,g,s)

    def test_anchor_checked_overlap_allowed_no_generated_details(self):
        u,v,g,s = fixture();selection = f.select_cores(u,v,g,s)
        calls = []
        def judge(core, source):
            calls.append((core['id'], source['source_id']))
            return supported()
        result = f.memberships(selection,s,judge)
        self.assertEqual(len(calls),9)
        self.assertEqual(len(set(calls)),9)
        for card in result['cards']:
            self.assertEqual(card['model_support_count'],3)
            self.assertIsNone(card['support_count'])
            self.assertEqual(card['generated_details'],[])
            self.assertFalse(card['quality_gate_passed'])
            self.assertEqual([e['original_text'] for e in card['evidence']], [x['text'] for x in s])
        self.assertEqual(result['agents'],[])

    def test_unknown_partial_errors_do_not_count(self):
        u,v,g,s = fixture();selection = f.select_cores(u,v,g,s,1)
        for value in ['unclear','partial','unsupported',None]:
            result = f.memberships(selection,s,lambda *a: {'verdict':value,'errors':[]})
            self.assertEqual(result['cards'][0]['model_support_count'],0)
        result = f.memberships(selection,s,lambda *a: {'verdict':'supported','errors':['transport_error']})
        self.assertEqual(result['cards'][0]['model_support_count'],0)

    def test_rare_and_unresolved_preserved(self):
        u,v,g,s = fixture();selection = f.select_cores(u,v,g,s,1)
        result = f.memberships(selection,s,lambda c,x: {'verdict':'supported' if x['source_id']=='0' else 'unclear','errors':[]})
        self.assertEqual(result['cards'][0]['status'],'rare_model_candidate')
        self.assertEqual(len(result['cards'][0]['relations']),3)

    def test_mutation_and_duplicate_support_fail(self):
        u,v,g,s = fixture();selection = f.select_cores(u,v,g,s,1)
        selection['cores'][0]['text'] = 'Different claim'
        with self.assertRaises(ValueError): f.memberships(selection,s,supported)
        selection = f.select_cores(u,v,g,s,1);selection['cores'][0]['source_ids'].append('0')
        with self.assertRaises(ValueError): f.memberships(selection,s,supported)
        with self.assertRaises(ValueError): f.memberships(f.select_cores(u,v,g,s,1),s,supported,2)

    def test_judge_cannot_mutate_registry_or_fixed_core(self):
        u,v,g,s = fixture();selection = f.select_cores(u,v,g,s,1);before = deepcopy((selection,s))
        def malicious(c,x):
            c['text'] = 'mutated';x['text'] = 'mutated';return supported()
        f.memberships(selection,s,malicious)
        self.assertEqual((selection,s),before)

    def test_judge_source_isolation_exact_cache_and_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = []
            def provider(system,data,schema,**kwargs):
                seen.append(data)
                return {'choices':[{'message':{'content':json.dumps({'P01':{'verdict':'supported','reason':'Test.'}})},'finish_reason':'stop'}]}
            judge = p.Judge({'expires_at':'2099-01-01T00:00:00Z'},Path(tmp),provider)
            c = {'text':'Costs may rise.'};s = {'source_id':'one','text':'Costs may rise.','parent_text':'Do not send.'}
            first = judge(c,s);self.assertEqual(first,judge(c,s));self.assertEqual(len(seen),1)
            self.assertEqual(seen[0],{'targets':{'M01':s['text']},'pairs':{'P01':{'text':c['text'],'member_id':'M01'}}})
            s['text'] = 'Different original';judge(c,s);self.assertEqual(len(seen),2)
            judge.calls.seconds = 600;s['text'] = 'Next'
            self.assertEqual(judge(c,s)['errors'],['budget_deferred']);self.assertEqual(len(seen),2)

    def test_expired_refuses_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            judge = p.Judge({'expires_at':'2000-01-01T00:00:00Z'},Path(tmp),lambda *a,**k: self.fail('expired call'))
            with self.assertRaises(ValueError): judge({'text':'x'},{'source_id':'one','text':'x'})

    def test_html_escapes_originals(self):
        u,v,g,s = fixture();s[0]['text'] = '<script>alert(1)</script>'
        u[0]['spans'] = [{'start':0,'end':len(s[0]['text']),'text':s[0]['text']}]
        membership = f.memberships(f.select_cores(u,v,g,s,1),s,supported)
        rendered = p.render({'summary':{},'membership':membership},s)
        self.assertNotIn('<script>',rendered);self.assertIn('&lt;script&gt;',rendered)


if __name__ == '__main__': unittest.main()
