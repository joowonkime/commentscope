"""Typed membership keeps complete observations and the existing independent vetoes."""
from copy import deepcopy
import re
import unittest

from commentscope.factory import jev_membership as j, raw_membership as raw
from commentscope.factory import source_context_observations as contexts, statement_worlds as worlds
from commentscope.factory import raw_membership_verification as verify, argument_observations as obs
from commentscope.factory.automatic_contract import digest
from commentscope.providers import openrouter_decisions as od
from test_raw_membership import candidate
from test_raw_membership_source_context import observation
from test_shared_typed_pipeline import SharedRunner
import test_minimal_pipeline as fixture


def receipt(payload,choose):
    answers={}
    for key,q in payload['questions'].items():
        value=choose(key,q)
        answers[key]={'type':'choice','choice':value,'confidence':1.,
                      'probabilities':{v:float(v==value) for v in q['criteria']}}
    return {'id':'synthetic-fixture','model':od.DEPLOYMENT['model'],'provider':'TypeSafe',
            'usage':{'cost':0.000001},'answers':answers}


def responses(task,output):
    manifest={m['alias']:m for m in task['manifest']}
    def choose(key,q):
        m=manifest[key]
        if m['kind']=='enum':value=output[m['field']]
        elif m['kind']=='descriptor':value=next(v['use'] for v in output['reported_descriptor_uses'] if v['id']==m['item_id'])
        else:value='needed' if m['item_id'] in output['evidence_segment_ids'] else 'not_needed'
        return value if value in q['criteria'] else j.OTHER
    return [receipt(p,choose) for p in task['requests']]


class JevContractTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'a','text':'Buses should be free only if hospital funding stays intact.','parent':None}
        self.target=candidate(self.source,self.source['text'])
        self.context=contexts.bind(self.source,{'output':{'source_use':'substantive_assertion','reported_descriptors':[]}})
        self.world=lambda text:worlds.bind(text,{'output':{'world':'real_world','anchor':''}})
        self.kw={'source_context':self.context,'source_world':self.world(self.source['text']),
                 'candidate_world':self.world(self.target['text'])}
        self.task=j.task(self.source,self.target,**self.kw)

    def test_typed_observation_preserves_scalar_checks_and_all_source_use_categories(self):
        fields=set(self.task['requests'][0]['state'])
        self.assertEqual(fields,{'TASK_CONTRACT','READING_INPUT'})
        self.assertNotIn('expected',str(self.task['requests']))
        for use in raw.SOURCE_USES:
            output={**observation(),'source_use':use}
            proof=j.bind(self.task,responses(self.task,output))
            scalar=raw.bind(self.source,self.target,{'output':output},version=raw.WORLD_CONTEXT,**self.kw)
            for key in ('output','passed','guards','relation','evidence'):self.assertEqual(proof[key],scalar[key])
            self.assertEqual(raw.validate(proof),proof)
        self.assertEqual(od.DEPLOYMENT['max_questions'],16)
        self.assertTrue(all(len(q['criteria'])<=8 for p in self.task['requests'] for q in p['questions'].values()))

    def test_overflow_needs_one_consistent_value_not_two_or_zero(self):
        good=responses(self.task,observation());split=[m for m in self.task['manifest'] if m['field']=='source_use']
        self.assertEqual(len(split),2)
        for mode in ('none','two'):
            bad=deepcopy(good)
            for p,r in zip(self.task['requests'],bad):
                for m in split:
                    if m['alias'] not in p['questions']:continue
                    q=p['questions'][m['alias']];v=j.OTHER if mode=='none' else m['values'][0]
                    r['answers'][m['alias']]={'type':'choice','choice':v,'confidence':1.,'probabilities':{k:float(k==v) for k in q['criteria']}}
            with self.subTest(mode=mode),self.assertRaises(ValueError):j.bind(self.task,bad)

    def test_missing_packets_answers_wrong_model_provider_cost_and_probabilities_rejected(self):
        good=responses(self.task,observation())
        for mode in ('packet','answer','model','provider','cost','probabilities'):
            bad=deepcopy(good)
            if mode=='packet':bad=[]
            elif mode=='answer':bad[0]['answers'].pop(next(iter(bad[0]['answers'])))
            elif mode in ('model','provider'):bad[0][mode]='wrong'
            elif mode=='cost':bad[0]['usage']={}
            else:next(iter(bad[0]['answers'].values()))['probabilities']={}
            with self.subTest(mode=mode),self.assertRaises((ValueError,KeyError)):j.bind(self.task,bad)

    def test_entire_raw_task_receipt_and_output_are_revalidated(self):
        proof=j.bind(self.task,responses(self.task,observation()))
        for what in ('source','candidate','request_sha256','output','witness'):
            bad=deepcopy(proof)
            if what in ('source','candidate'):bad[what]['text']+=' changed'
            elif what=='output':bad[what]['relation']='unrelated'
            elif what=='witness':bad['typed_observation']['task']['manifest'][0]['field']='foreign'
            else:bad[what]='changed'
            with self.subTest(what=what),self.assertRaises((ValueError,KeyError)):raw.validate(bad)

    def test_original_response_cannot_move_to_another_source_with_same_schema(self):
        original=responses(self.task,observation())
        source={**self.source,'id':'different-original'}
        context=contexts.bind(source,{'output':{'source_use':'substantive_assertion','reported_descriptors':[]}})
        task=j.task(source,self.target,source_context=context,source_world=self.kw['source_world'],candidate_world=self.kw['candidate_world'])
        with self.assertRaises(ValueError):j.bind(task,original)

    def test_unclear_evidence_never_approves_support(self):
        output=responses(self.task,observation());m=next(m for m in self.task['manifest'] if m['kind']=='evidence')
        for p,r in zip(self.task['requests'],output):
            if m['alias'] in p['questions']:
                q=p['questions'][m['alias']];r['answers'][m['alias']]={'type':'choice','choice':'unclear','confidence':1.,
                    'probabilities':{v:float(v=='unclear') for v in q['criteria']}}
        proof=j.bind(self.task,output);self.assertFalse(proof['passed'])
        self.assertIn('jev_evidence_scope_uncertain',proof['guards'])

    def test_world_authorship_and_conditional_vetoes_remain(self):
        for update in ({'authorship':'not_asserted'},{'scope_preserved':'no'},
                       {'population_scope':'changed'},{'predicate_scope':'inferred'}):
            value={**observation(),**update}
            self.assertFalse(j.bind(self.task,responses(self.task,value))['passed'])
        bad=deepcopy(self.kw);bad['candidate_world']=worlds.bind(self.target['text'],{'output':{'world':'fictional_world','anchor':'Buses'}})
        task=j.task(self.source,self.target,**bad)
        self.assertIn('independent_world_scope_unapproved',j.bind(task,responses(task,observation()))['guards'])

    def test_many_segments_partition_questions_without_dropping_any(self):
        source={'id':'many','text':' '.join('Claim '+str(i)+'.' for i in range(28)),'parent':None}
        context=contexts.bind(source,{'output':{'source_use':'substantive_assertion','reported_descriptors':[]}})
        task=j.task(source,candidate(source,'Claim 0.'),source_context=context,
                    source_world=self.world(source['text']),candidate_world=self.world('Claim 0.'))
        self.assertGreater(len(task['requests']),1)
        self.assertEqual(sum(len(p['questions']) for p in task['requests']),len(task['manifest']))
        self.assertTrue(all(j.measure(p)['fits'] for p in task['requests']))
        output=observation();output['evidence_segment_ids']=[m['item_id'] for m in task['manifest'] if m['kind']=='evidence']
        with self.assertRaises(ValueError):j.bind(task,responses(task,output))

    def test_reported_descriptor_adoption_is_not_support(self):
        source={'id':'report','text':'They call residents idle. I reject that description.','parent':None}
        context=contexts.bind(source,{'output':{'source_use':'substantive_assertion','reported_descriptors':[{'segment_id':'S000','text':'idle'}]}})
        target=candidate(source,'Idle residents need help.')
        task=j.task(source,target,source_context=context,source_world=self.world(source['text']),candidate_world=self.world(target['text']))
        value={**observation(),'reported_descriptor_uses':[{'id':'R000','use':'adopted_report'}]}
        self.assertIn('independent_descriptor_attribution_unapproved',j.bind(task,responses(task,value))['guards'])


class JevRunner(SharedRunner):
    def __init__(self,*,invalid=False,veto=False,**kw):
        super().__init__(**kw);self.typed_calls=[];self.invalid=invalid;self.veto=veto
    def decide(self,stage,payload):
        self.typed_calls.append((stage,payload));data=payload['state']['READING_INPUT']
        own=data['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')
        value=observation(relation='supported' if own==data['CANDIDATE']['text'].rstrip('.') else 'opposed')
        def choose(key,q):
            field=re.search(r'Observe (\w+) for READING_INPUT',q['instructions'])
            v=value[field.group(1)] if field else 'not_used' if 'reported descriptor' in q['instructions'] else 'needed'
            return v if v in q['criteria'] else j.OTHER
        result=receipt(payload,choose)
        if self.invalid:result['answers']={}
        return result
    def call(self,stage,req):
        result=super().call(stage,req)
        if self.veto and stage.startswith('raw-own-evidence'):result['output']['verdict']='extra_assertion'
        return result


class JevPipelineTests(unittest.TestCase):
    def setUp(self):self.h=fixture.MinimalPipelineTests();self.h.setUp()
    def process(self,runner,**extra):
        return self.h.process(runner,discovery_mode='shared',membership_mode='raw',
            verification_contract=verify.FULL_SCOPE,argument_audit_protocol=obs.SHARED_TYPED_CHAT,
            agent_source_policy='candidate_verified_subset',membership_judge_protocol=j.VERSION,**extra)
    def test_full_pipeline_keeps_two_agents_three_supports_and_independent_evidence(self):
        runner=JevRunner();result=self.process(runner,membership_evidence_protocol=verify.QUALIFIED_CONTEXT)
        self.assertFalse(result['errors']);self.assertEqual(len(result['agent_inputs']['compiled']['profiles']),2)
        self.assertTrue(all(p['model_core_support_count']==3 for p in result['agent_inputs']['compiled']['profiles']))
        self.assertTrue(runner.typed_calls);self.assertTrue(any(s.startswith('raw-own-evidence') for s,_ in runner.calls))
        self.assertFalse(any(s.startswith(('nomination-raw','membership-initial-raw','membership-expanded-raw')) for s,_ in runner.calls))
        self.assertEqual(result['membership_judge_protocol'],j.VERSION);self.assertFalse(result['quality_gate_passed'])
    def test_m2_veto_still_holds_all_agents(self):
        result=self.process(JevRunner(veto=True));self.assertFalse(result['agent_inputs']['compiled']['profiles'])
    def test_bad_typed_response_is_not_retried_as_scalar(self):
        runner=JevRunner(invalid=True);result=self.process(runner)
        self.assertTrue(result['errors']);self.assertFalse(result['agent_inputs']['compiled']['profiles'])
        self.assertFalse(any(s.startswith(('nomination-raw','membership-initial-raw')) for s,_ in runner.calls))
        keys=[digest(p) for _,p in runner.typed_calls];self.assertEqual(len(keys),len(set(keys)))
    def test_incompatible_or_missing_typed_runner_rejected_before_inference(self):
        from commentscope.factory import source_membership_batch as batch
        for runner,kwargs in ((SharedRunner(),{}),(JevRunner(),{'membership_batch_protocol':batch.VERSION})):
            with self.assertRaises(ValueError):self.process(runner,**kwargs)
            self.assertEqual(runner.calls,[])


class TypedCostTests(unittest.TestCase):
    def test_missing_typed_price_cannot_borrow_scalar_sol_prices(self):
        from test_factory_cost_plan import CostPlanningTests,cost_profile
        h=CostPlanningTests();h.setUp()
        h.plan.update(membership_judge_protocol=j.VERSION,membership_deployment=deepcopy(od.DEPLOYMENT))
        h.work['counts']['membership-raw']=0
        # The old profile's Sol fingerprint is not a Jev unit price.
        self.assertIn('membership-jev',h.estimate()['unknown_stages'])
        h.profile=cost_profile(h.plan)
        self.assertNotIn('membership-jev',h.estimate()['unknown_stages'])
        from commentscope.factory import cost_planning as c
        caps=dict.fromkeys(c.STAGES,0);caps['membership-jev']=1
        limits=c.CallLimits(caps)
        fixture=JevContractTests();fixture.setUp();payload=fixture.task['requests'][0]
        stage='membership-jev-'+od.wire_sha256(payload,od.DEPLOYMENT)[:20]
        limits.admit(stage,payload);limits.admit(stage,deepcopy(payload))
        another=deepcopy(payload);another['state']['new_original']='A different source requires a new request.'
        with self.assertRaises(c.CostPlanError):
            limits.admit('membership-jev-'+od.wire_sha256(another,od.DEPLOYMENT)[:20],another)
        self.assertEqual(limits.used['membership-jev'],1)

    def test_typed_archive_cost_is_counted_once_with_actual_provider_receipt(self):
        import tempfile,json
        from commentscope.factory import cost_planning as c
        from commentscope.factory.claim_clusters import sha
        from commentscope.storage import write_json_exclusive as write
        from tools import plan_factory_cost as cost_tool
        from commentscope.providers import remote_verification as remote
        with tempfile.TemporaryDirectory(dir='runs') as temp:
            root=__import__('pathlib').Path(temp);source=root/'frozen-code/synthetic.py'
            source.parent.mkdir();source.write_text('# Synthetic archive\n')
            plan={'membership_judge_protocol':j.VERSION,'membership_deployment':od.DEPLOYMENT,
                'deployment':remote.SOL,'verification_deployment':remote.SOL,
                'code_sha256':{'synthetic.py':sha(source)}}
            write(root/'plan.json',plan);write(root/'frozen.json',{'plan_sha256':sha(root/'plan.json')})
            helper=JevContractTests();helper.setUp();payload=helper.task['requests'][0]
            result=responses(helper.task,observation())[0];stage='membership-jev-'+od.wire_sha256(payload,od.DEPLOYMENT)[:20]
            identity={'plan_sha256':sha(root/'plan.json'),'stage':stage,'request_sha256':digest(payload)}
            write(root/'calls'/('0001-'+stage+'.request.json'),{**identity,'request':payload})
            write(root/'calls'/('0001-'+stage+'.result.json'),result)
            write(root/'checkpoints/one.intent.json',identity)
            write(root/'checkpoints/one.result.json',{'identity':identity,'result':result,'result_sha256':digest(result)})
            profile=cost_tool.audit(root);row=profile['stages']['membership-jev']
            self.assertEqual(row['calls'],1);self.assertEqual(row['cost_usd'],'0.000001')
            self.assertEqual(row['maximum_questions'],len(payload['questions']))
