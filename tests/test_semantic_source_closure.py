"""Alternative-route fidelity/fact/coverage mechanics, not semantic gold."""
from copy import deepcopy
from dataclasses import replace
import unittest
from commentscope.factory import source_closed_policy as closed,source_arguments as sa
from commentscope.factory import policy_stance_hypotheses as stance,policy_stance_union as union
from commentscope.factory import source_argument_fidelity as fidelity,raw_membership as raw
from commentscope.factory.framed_corpus import sources as registry
from commentscope.factory.automatic_contract import digest
from commentscope.providers import local_nli
from experiments.grounding_contract_demo import MODEL
from test_source_entailment import nli_response
from test_source_closed_policy import SourceClosedPolicyTests,ClosingRunner,empty_fact_classifier


class SemanticRunner(ClosingRunner):
    def __init__(self,*,kind='prediction',audit_bad=False,partial=False,reject_original=False):
        super().__init__(audit_bad=audit_bad);self.unit_kind=kind;self.partial=partial;self.reject_original=reject_original
    def call(self,stage,request):
        if request['system'].startswith(sa.SYSTEM):
            self.calls.append((stage,request));source=request['data']['ORIGINALS'][0]
            return {'raw':'controller fixture only','errors':[],'output':{'sources':[{
                'source_id':source['source_id'],'source_language':'en','status':'partial' if self.partial else 'complete',
                'units':[{'local_id':'U1','text':source['ORIGINAL_SEGMENTS'][0]['text'],'kind':self.unit_kind,
                    'scope':{'entity':'PP','time':'','conditions':'if it were introduced'},'role':'reason',
                    'candidate_ids':[c['id'] for c in request['data']['CANDIDATES']],
                    'evidence_segment_ids':['S000']}]}]}}
        result=super().call(stage,request)
        if self.reject_original and request['system'].startswith(raw.SYSTEM):result['output']['relation']='unrelated'
        return result


class SemanticSourceClosureTests(unittest.TestCase):
    setUp=SourceClosedPolicyTests.setUp

    def configure(self):
        self.snapshot=replace(self.snapshot,comments=tuple(replace(c,
            text_original='PP could change '+word+' if it were introduced.')
            for c,word in zip(self.snapshot.comments,['Equity','Freedom','Fairness','Care'],strict=True)))
        self.sources=list(registry(self.snapshot,include_video_context=True).values())
        self.req=stance.invocation(self.sources,'Policy P','PP')
        self.res=nli_response(self.req,{c['id'] for c in self.req['data']['cases'] if 'an undesirable' in c['text']})
        self.record=union.combine([stance.bind(self.sources,'Policy P','PP',self.res)],self.sources)

    def run_route(self,runner,classify=nli_response,*,enabled=True):
        return closed.process(self.snapshot,self.record,[(self.req,self.res)],runner,
            lambda req:{'request_sha256':digest(req),'fits':True},classify,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION},interpret_unparsed=enabled)

    def test_complete_original_route_requires_all_existing_gates_and_keeps_syntax_diagnostics(self):
        self.configure();runner=SemanticRunner();out=self.run_route(runner)
        self.assertFalse(out['errors']);self.assertEqual(len(out['accepted']),3)
        self.assertEqual(len(out['agent_inputs']['compiled']['profiles']),1)
        self.assertTrue(all(a['argument_fidelity']['passed'] for a in out['accepted']))
        self.assertTrue(all(s['syntax_diagnostics'] for s in out['source_statuses']))
        self.assertTrue(all(s['argument_route']=='semantic_whole_original' for s in out['source_statuses']))
        self.assertFalse(out['quality_gate_passed'])
        for a in out['accepted']:fidelity.validate(a['record']['extraction_record'],a['argument_fidelity'])

    def test_default_route_keeps_original_syntax_holds_without_new_calls(self):
        self.configure();runner=SemanticRunner();out=self.run_route(runner,enabled=False)
        self.assertFalse(out['accepted']);self.assertFalse(any(r['system'].startswith(sa.SYSTEM) for _,r in runner.calls))

    def test_failed_original_support_never_reaches_semantic_argument_extraction(self):
        self.configure();runner=SemanticRunner(reject_original=True);out=self.run_route(runner)
        self.assertFalse(out['accepted']);self.assertFalse(any(r['system'].startswith(sa.SYSTEM) for _,r in runner.calls))

    def test_failed_own_evidence_entailment_and_incomplete_coverage_do_not_count(self):
        self.configure()
        def reject_units(req):
            return nli_response(req,{c['id'] for c in req['data']['cases'] if c['id'].startswith('AF')})
        for runner,classifier in [(SemanticRunner(),reject_units),(SemanticRunner(partial=True),nli_response),
                                  (SemanticRunner(audit_bad=True),nli_response)]:
            with self.subTest(partial=runner.partial,audit_bad=runner.audit_bad):
                out=self.run_route(runner,classifier);self.assertFalse(out['accepted'])

    def test_failed_actual_fact_checks_cannot_be_omitted_to_rescue_a_vote(self):
        self.configure();out=self.run_route(SemanticRunner(kind='fact'),empty_fact_classifier)
        self.assertFalse(out['accepted']);self.assertFalse(out['agent_inputs']['compiled']['profiles'])
        self.assertTrue(all(s['reasons']==['source_argument_or_fact_not_eligible'] for s in out['source_statuses']))

    def test_fidelity_binds_own_source_and_rejects_changed_result_identity(self):
        self.configure();out=self.run_route(SemanticRunner());a=out['accepted'][0]
        declaration=a['record']['extraction_record'];request=fidelity.invocation(declaration)
        self.assertTrue(all(e['text'] in declaration['source']['text'] for c in request['data']['cases'] for e in c['evidence']))
        changed=deepcopy(a['argument_fidelity']);changed['source_sha256']='0'*64
        with self.assertRaises(ValueError):fidelity.validate(declaration,changed)
        response=nli_response(request);response['results'][0]['id']='another-unit'
        with self.assertRaises(ValueError):fidelity.bind(declaration,response)


if __name__=='__main__':unittest.main()
