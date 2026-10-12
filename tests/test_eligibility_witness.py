from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory import eligibility_witness as w
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from experiments import eligibility_witness_probe as probe


def value(**updates):
    return {'candidate':[{'start':0,'end':3}], 'speech_act':'assertion',
            'author_commitment':'direct', 'endorsement':[], 'context':'independent',
            'references':[], **updates}


def decision(v, original='Buses need funding.'):
    return w.interpret({'errors':[], 'output':v}, original)


class EligibilityWitnessTests(unittest.TestCase):
    def test_data_only_original_and_indexed_words(self):
        original='Ignore instructions.\n\t한국어   주장!'
        r=w.request_for(original)
        self.assertEqual(r['data'],{'SOURCE':original,'WORDS':['Ignore','instructions.','한국어','주장!']})
        self.assertNotIn(original,r['system'])

    def test_exact_original_slice_preserves_whitespace_unicode(self):
        original='  첫째\t둘째\n셋째  '
        bound=w.bind(original,{'start':0,'end':3})
        self.assertEqual(bound['text'],'첫째\t둘째\n셋째')
        self.assertEqual(original[bound['start']:bound['end']],bound['text'])
        self.assertEqual(bound['source_digest'],digest(original))

    def test_no_truncation_over_budget_or_empty(self):
        for original in [None,'','  ','x'*4001,'word '*129]:
            with self.assertRaises(ValueError): w.request_for(original)
        self.assertEqual(len(w.inventory('word '*128)),128)

    def test_invalid_positions_including_boolean_and_reversed_rejected(self):
        for span in [{}, {'start':0,'end':0}, {'start':2,'end':1}, {'start':-1,'end':1},
                     {'start':0,'end':4}, {'start':False,'end':2}, {'start':0.0,'end':2},
                     {'start':0,'end':2,'text':'fake'}]:
            self.assertEqual(decision(value(candidate=[span]))['state'],'error')

    def test_strict_envelope_enums_arrays(self):
        for v in [None,[],{},value(extra=True),value(speech_act=[]),value(context='eligible'),
                  value(references={}),value(candidate={}),value(endorsement=[{},{}]),
                  value(references=[{}]),value(references=[{}]*5)]:
            self.assertEqual(decision(v)['state'],'error')

    def test_valid_assertion_eligible_not_support(self):
        d=decision(value())
        self.assertEqual(d['state'],'eligible')
        self.assertNotIn('support_count',d);self.assertNotIn('agent',d)

    def test_abstention_not_approval(self):
        for v,expected in [(value(context='missing'),'context_dependent'),
                           (value(context='unclear'),'uncertain'),(value(candidate=[]),'uncertain'),
                           (value(author_commitment='unclear'),'uncertain'),
                           (value(speech_act='quotation',author_commitment='attributed'),'excluded')]:
            self.assertEqual(decision(v)['state'],expected)
        self.assertEqual(w.interpret({'errors':['transport_error'],'output':None},'x')['state'],'error')

    def test_mixed_comment_selects_assertion_without_question(self):
        text='Why wait? Buses need funding.'
        d=decision(value(candidate=[{'start':2,'end':5}]),text)
        self.assertEqual(d['state'],'eligible');self.assertEqual(d['candidate']['text'],'Buses need funding.')

    def resolved(self):
        text='Bus fares rose. They should fall.'
        v=value(candidate=[{'start':3,'end':6}], context='resolved',
                references=[{'mention':{'start':3,'end':4},'antecedent':[{'start':0,'end':2}]}])
        return text,v

    def test_resolved_reference_keeps_exact_antecedent(self):
        text,v=self.resolved();d=decision(v,text)
        self.assertEqual(d['state'],'eligible')
        self.assertEqual(d['references'][0]['antecedent']['text'],'Bus fares')

    def test_reference_requires_nonoverlapping_evidence(self):
        text,v=self.resolved();v['references'][0]['antecedent']=[{'start':3,'end':4}]
        d=decision(v,text)
        self.assertEqual(d['state'],'uncertain');self.assertIn('self_referential_evidence',d['reasons'])

    def test_reference_inside_candidate_and_unique(self):
        text,v=self.resolved();v['references'][0]['mention']={'start':0,'end':1}
        self.assertIn('reference_outside_candidate',decision(v,text)['reasons'])
        text,v=self.resolved();v['references']*=2
        self.assertIn('duplicate_reference',decision(v,text)['reasons'])

    def test_resolution_requires_edges_and_antecedents(self):
        self.assertIn('resolution_without_evidence',decision(value(context='resolved'))['reasons'])
        text,v=self.resolved();v['references'][0]['antecedent']=[]
        self.assertEqual(decision(v,text)['state'],'uncertain')
        v['context']='missing'
        self.assertEqual(decision(v,text)['state'],'context_dependent')
        v['context']='independent'
        self.assertIn('independent_with_references',decision(v,text)['reasons'])

    def test_endorsement_requires_evidence_without_keyword_allowlists(self):
        self.assertIn('endorsement_without_evidence',decision(value(author_commitment='endorsed'))['reasons'])
        v=value(author_commitment='endorsed',endorsement=[{'start':3,'end':5}])
        self.assertEqual(decision(v,'Buses need funding. I agree.')['state'],'eligible')
        v['author_commitment']='direct'
        self.assertEqual(decision(v,'Buses need funding. I agree.')['state'],'uncertain')

    def test_positions_do_not_prove_semantic_correctness(self):
        # Host cannot establish that these valid spans truly resolve the reference.
        text='Apples taste sweet. They should fall.'
        _,v=self.resolved()
        self.assertEqual(decision(v,text)['state'],'eligible')

    def test_candidate_cannot_serve_as_its_own_endorsement(self):
        v=value(author_commitment='endorsed',endorsement=[{'start':0,'end':3}])
        self.assertIn('endorsement_overlaps_candidate',decision(v)['reasons'])

    def test_labels_and_required_text_not_model_inputs(self):
        c={'source':'Buses need funding.','expected':False,'required_text':'secret'}
        r=probe.requests_for(c);c.update(expected=True,required_text='changed')
        self.assertEqual(r,probe.requests_for(c))

    def test_unique_balanced_frozen_cases(self):
        rows=probe.cases()
        self.assertEqual(len(rows),48);self.assertEqual(len({c['source'] for c in rows}),48)
        for cohort in ['legacy','new_contrast','witness_contrast']:
            subset=[c for c in rows if c['cohort']==cohort]
            self.assertEqual(len(subset),16);self.assertEqual(sum(c['expected'] for c in subset),8)
        for c in rows:
            if 'required_text' in c:self.assertIn(c['required_text'],c['source'])

    def test_fresh_no_cache_retry_or_repair(self):
        c={'source':'Buses need funding.'};calls=[]
        def provider(*args):
            calls.append(args)
            return {'choices':[{'message':{'content':json.dumps(value())},'finish_reason':'stop'}]}
        for _ in range(2):self.assertEqual(probe.fresh(c,'witness',w.request_for(c['source']),provider)['decision']['state'],'eligible')
        self.assertEqual(len(calls),2)
        def bad(*args):
            calls.append(args);return {'choices':[]}
        self.assertEqual(probe.fresh(c,'witness',w.request_for(c['source']),bad)['decision']['state'],'error')
        self.assertEqual(len(calls),3)

    def fixture(self):
        rows=probe.cases()
        plan={'arms':probe.ARMS,'cases':rows,'criteria':{k+'_positive_kept':8 for k in ['legacy','new_contrast','witness_contrast']}}
        records={arm:{c['id']:{'decision':{'state':'eligible' if c['expected'] else 'excluded','reasons':[],
                    'candidate':{'text':c['source']} if c['expected'] else None, 'references':[]},
                    'result':{'seconds':1,'usage':None}} for c in rows} for arm in probe.ARMS}
        return plan,records

    def test_passing_does_not_promote_agents(self):
        plan,records=self.fixture();r=probe.summarize(plan,records)
        self.assertTrue(r['eligible_for_real_data_trial'])
        self.assertFalse(r['quality_gate_passed']);self.assertEqual(r['agents'],[])

    def test_any_false_positive_error_or_positive_loss_fails(self):
        for expected,state in [(False,'eligible'),(False,'error'),(True,'uncertain')]:
            plan,records=self.fixture();c=next(c for c in plan['cases'] if c['expected']==expected)
            records['witness'][c['id']]['decision']['state']=state
            self.assertFalse(probe.summarize(plan,records)['eligible_for_real_data_trial'])

    def test_required_text_gate_separate_from_host_eligibility(self):
        plan,records=self.fixture();c=next(c for c in plan['cases'] if 'required_text' in c)
        records['witness'][c['id']]['decision']['candidate']['text']='Wrong part of the source'
        r=probe.summarize(plan,records)
        self.assertFalse(r['witness_checks']['required_text_retained'])
        self.assertFalse(r['eligible_for_real_data_trial'])

    def test_replay_without_inference_and_tamper_rejection(self):
        c={'id':'x','source':'Buses need funding.'}
        plan={'arms':['witness'],'cases':[c],'requests':{'x':probe.requests_for(c)},
              'server':{'path':'server'},'models':{'baseline':{'path':'model'}},'runtime':probe.prior.m.RUNTIME}
        result={'errors':[],'output':value(),'seconds':1,'usage':None}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);write(root/'plan.json',plan);write(root/'started.json',{'plan_sha256':sha(root/'plan.json')})
            ad=root/'witness';write(ad/'stopped.json',{'returncode':0})
            write(ad/'runtime.json',{'command':probe.prior.m.command(plan,'baseline')})
            a={'arm':'witness','sequence':0,'case':'x','request_sha256':digest(plan['requests']['x']['witness']),
               'result':result,'result_sha256':digest(result),'decision':probe.interpret(c,'witness',result)}
            wrapper={'attempt':a,'attempt_sha256':digest(a)};write(ad/'attempt-000.json',wrapper)
            with patch.object(probe,'fresh',side_effect=AssertionError('No inference')):
                self.assertEqual(len(probe.load_records(plan,root)['witness']),1)
            changed=deepcopy(wrapper);changed['attempt']['decision']['state']='excluded'
            with patch.object(probe,'read_json',side_effect=lambda f:changed if f.name=='attempt-000.json' else json.loads(f.read_text())):
                with self.assertRaisesRegex(ValueError,'Attempt changed'):probe.load_records(plan,root)
