"""Controller/provenance fixtures; no claims about actual model quality."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest
from commentscope.ingestion import load_snapshot
from commentscope.factory import source_closed_policy as closed,policy_stance_hypotheses as stance
from commentscope.factory import policy_stance_union as union,owned_arguments as oa,source_arguments as sa
from commentscope.factory import raw_membership as raw
from commentscope.factory import source_discourse as sd
from commentscope.factory.framed_corpus import sources as registry
from commentscope.factory.automatic_contract import digest
from experiments.grounding_contract_demo import MODEL
from test_policy_admission import PolicyRunner
from test_source_entailment import nli_response
import test_minimal_agents as agent_fixtures
from commentscope.providers import evidence_nli
from commentscope.providers import local_nli


class ClosingRunner(PolicyRunner):
    def __init__(self,bad_source=None,*,kind='value',audit_bad=False):
        super().__init__();self.bad_source=bad_source;self.kind=kind;self.audit_bad=audit_bad
    def call(self,stage,req):
        data=req['data'];system=req['system']
        if system.startswith(sd.SYSTEM):
            value={'decisions':[{'pair_id':p['id'],'relation':'independent','position_node_id':'none',
                'ground_node_id':'none'} for p in data['PAIRS']]}
        elif system.startswith(oa.META):
            value={'authorship':'asserted_or_endorsed','kind':self.kind,'entity':'Policy P','time_ids':[],'source_language':'en'}
            value={k:value[k] for k in req['schema']['properties']}
        elif system.startswith(raw.SYSTEM):
            value={'relation':'supported','authorship':'asserted_or_endorsed','candidate_interpretation':'clear',
                'scope_preserved':'yes','contribution':'substantive','evidence_segment_ids':['S000']}
        elif system.startswith(sa.AUDIT):
            value={'decisions':[{'task_id':t['task_id'],'verdict':'unsupported' if self.audit_bad else 'supported'} for t in data['TASKS']]}
        elif system.startswith(sa.LINK_SYSTEM):
            value={'status':'complete','links':[{'local_id':u['local_id'],'requires':[],'core_requires_for':[]} for u in data['UNITS']]}
        else:return super().call(stage,req)
        self.calls.append((stage,req));return {'raw':'controller fixture only','output':value,'errors':[]}


class PremiseRunner(ClosingRunner):
    def call(self,stage,req):
        if req['system'].startswith(oa.META):
            value={'authorship':'asserted_or_endorsed','kind':'fact' if req['data']['TARGET'].startswith('Considering') else 'value',
                'entity':'Policy P','time_ids':[],'source_language':'en'}
            return {'raw':'literal premise regression fixture','output':{k:value[k] for k in req['schema']['properties']},'errors':[]}
        return super().call(stage,req)


class ConsequenceRunner(ClosingRunner):
    def call(self,stage,req):
        if req['system'].startswith(sd.SYSTEM):
            return {'raw':'source-discourse controller fixture','output':{'decisions':[
                {'pair_id':p['id'],'relation':'reason','position_node_id':p['first'],
                 'ground_node_id':p['second']} for p in req['data']['PAIRS']]},'errors':[]}
        result=super().call(stage,req)
        if (req['system'].startswith(oa.META) and 'BOUND_SOURCE_DISCOURSE_CONTEXT' in req['data'] and
                'kind' in req['schema']['properties']):
            result['output']['kind']='prediction'
        return result


def empty_fact_classifier(req):
    if any(not c['evidence'] for c in req['data']['cases']):
        result=nli_response({**req,'data':{'cases':[]}})
        result.update(results=[{'id':c['id'],'pairs':[],**evidence_nli.aggregate([])}
            for c in req['data']['cases']],forward_pairs=0)
        return result
    return nli_response(req)


class SourceClosedPolicyTests(unittest.TestCase):
    def setUp(self):
        template=load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        text='Policy P (PP) '+stance.POLARITIES['favorable']
        self.snapshot=replace(template,video=replace(template.video,title='Policy P Explained PP'),
            usage=replace(template.usage,expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(template.comments[0],comment_id=str(i),
                text_original=text+' '+reason+' matters.',parent_id=None)
                for i,reason in enumerate(['Equity','Freedom','Fairness','Care'])))
        self.sources=list(registry(self.snapshot,include_video_context=True).values())
        self.req=stance.invocation(self.sources,'Policy P','PP');self.res=nli_response(self.req)
        # Only favorable is nominated. The fixture NNLI is not an evaluator.
        negative={c['id'] for c in self.req['data']['cases'] if 'an undesirable' in c['text']}
        self.res=nli_response(self.req,negative)
        self.record=union.combine([stance.bind(self.sources,'Policy P','PP',self.res)],self.sources)
    def process(self,runner,classify=nli_response):
        return closed.process(self.snapshot,self.record,[(self.req,self.res)],runner,
            lambda req:{'request_sha256':digest(req),'fits':True},classify,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION})

    def test_only_three_closed_sources_compile_remaining_source_stays_unprocessed(self):
        out=self.process(ClosingRunner())
        self.assertFalse(out['errors']);self.assertEqual(len(out['accepted']),3)
        self.assertEqual(len(out['agent_inputs']['compiled']['profiles']),1)
        self.assertEqual(out['agent_inputs']['compiled']['profiles'][0]['model_core_support_count'],3)
        self.assertEqual(sum(s['state']=='not_processed_after_three_closed_sources' for s in out['source_statuses']),1)
        self.assertEqual(len(out['census_status']),4);self.assertFalse(out['quality_gate_passed'])

    def test_failed_audits_do_not_count_or_silently_drop_sources(self):
        out=self.process(ClosingRunner(audit_bad=True))
        self.assertFalse(out['accepted']);self.assertFalse(out['agent_inputs']['compiled']['profiles'])
        self.assertEqual(len(out['source_statuses']),4)
        self.assertTrue(all('argument_not_verified' in s['reasons'] for s in out['source_statuses']))

    def test_unverified_facts_cannot_count_even_when_optional_omission_could_compile(self):
        def classify(req):
            if any(not c['evidence'] for c in req['data']['cases']):
                result=nli_response({**req,'data':{'cases':[]}})
                result.update(results=[{'id':c['id'],'pairs':[],**evidence_nli.aggregate([])}
                    for c in req['data']['cases']],forward_pairs=0)
                return result
            return nli_response(req,{c['id'] for c in req['data']['cases']} if
                any(c['id'].startswith('OA') for c in req['data']['cases']) else ())
        out=self.process(ClosingRunner(kind='fact'),classify)
        self.assertFalse(out['accepted']);self.assertTrue(all(
            'source_argument_or_fact_not_eligible' in s['reasons'] for s in out['source_statuses']))

    def test_explicit_monetary_premise_reaches_fact_gate_and_cannot_hide_in_value(self):
        comments=tuple(replace(c,text_original=f'Considering we spend ${50000+i:,} per year, Policy P seems worthwhile.')
            for i,c in enumerate(self.snapshot.comments))
        self.snapshot=replace(self.snapshot,comments=comments)
        self.sources=list(registry(self.snapshot,include_video_context=True).values())
        self.req=stance.invocation(self.sources,'Policy P','PP')
        negative={c['id'] for c in self.req['data']['cases'] if 'an undesirable' in c['text']}
        self.res=nli_response(self.req,negative)
        self.record=union.combine([stance.bind(self.sources,'Policy P','PP',self.res)],self.sources)
        seen=[]
        def classify(req):seen.extend(req['data']['cases']);return empty_fact_classifier(req)
        out=self.process(PremiseRunner(),classify)
        self.assertFalse(out['errors']);self.assertFalse(out['accepted'])
        self.assertFalse(out['agent_inputs']['compiled']['profiles'])
        facts=[c for c in seen if c['id'].startswith('SA')]
        self.assertEqual(len(facts),4)
        self.assertTrue(all(c['text'].startswith('Considering we spend $') for c in facts))
        self.assertTrue(all(s['reasons']==['source_argument_or_fact_not_eligible'] for s in out['source_statuses']))

    def test_unbound_generic_target_is_recorded_before_source_inference_not_manually_removed(self):
        comments=tuple(replace(c,text_original=f'A voluntary income scheme for need group {i} seems good.')
            for i,c in enumerate(self.snapshot.comments))
        self.snapshot=replace(self.snapshot,comments=comments)
        self.sources=list(registry(self.snapshot,include_video_context=True).values())
        self.req=stance.invocation(self.sources,'Policy P','PP')
        negative={c['id'] for c in self.req['data']['cases'] if 'an undesirable' in c['text']}
        self.res=nli_response(self.req,negative)
        self.record=union.combine([stance.bind(self.sources,'Policy P','PP',self.res)],self.sources)
        runner=ClosingRunner();out=self.process(runner)
        self.assertFalse(out['accepted']);self.assertEqual(len(out['census_status']),4)
        self.assertTrue(all('own_named_policy_reference_unbound' in s['reasons'] for s in out['source_statuses']))
        self.assertFalse(any(stage in ['own-policy-evaluation','policy-original','argument-node-metadata'] for stage,_ in runner.calls))

    def test_bound_hypothetical_consequence_is_retained_as_own_prediction_reason(self):
        text='Policy P (PP) '+stance.POLARITIES['favorable']
        self.snapshot=replace(self.snapshot,comments=tuple(replace(c,text_original=
            text+' Would make group '+['alpha','beta','gamma','delta'][i]+' more relaxed.')
            for i,c in enumerate(self.snapshot.comments)))
        self.sources=list(registry(self.snapshot,include_video_context=True).values())
        self.req=stance.invocation(self.sources,'Policy P','PP')
        self.res=nli_response(self.req,{c['id'] for c in self.req['data']['cases'] if 'an undesirable' in c['text']})
        self.record=union.combine([stance.bind(self.sources,'Policy P','PP',self.res)],self.sources)
        out=self.process(ConsequenceRunner())
        self.assertFalse(out['errors']);self.assertEqual(len(out['accepted']),3)
        for source in out['accepted']:
            reason=next(u for u in source['record']['units'] if u['role']=='reason')
            self.assertEqual(reason['kind'],'prediction');self.assertTrue(reason['text'].startswith('Would make group '))
            self.assertEqual(reason['candidate_ids'],[source['candidate_id']])
            self.assertIn('discourse_context',next(m for m in source['record']['extraction_record']['metadata']
                if m['node_id']==reason['source_node_id']))
        profile=out['agent_inputs']['compiled']['profiles'][0]
        forecasts=[e for e in profile['prompt_entries'] if e['text'].startswith('Would make group ')]
        self.assertEqual(len(forecasts),3);self.assertTrue(all(e['kind']=='prediction' for e in forecasts))


class ClosedAuditReceiptTests(unittest.TestCase):
    def test_independent_actual_audit_scopes_compose_without_rebinding_or_borrowing(self):
        fixture=agent_fixtures.MinimalAgentTests();fixture.setUp();records=fixture.records()
        audits=[fixture.audits([r])[0] for r in records]
        output=fixture.prepare(records,audits)
        self.assertEqual(len(output['compiled']['profiles']),1)
        changed=deepcopy(audits);changed[0]['records_sha256']=digest([records[1]])
        with self.assertRaises(ValueError):fixture.prepare(records,changed)


if __name__=='__main__':unittest.main()
