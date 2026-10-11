from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError

from commentscope.agents.profiles import build_bundle,load_bundle,require_live
from commentscope.agents.runtime import AgentSession,SYSTEM,AUDIT_SYSTEM,validate_answer
from commentscope.agents.demo import render,citation_html
from commentscope.factory.claim_clusters import sha
from commentscope.factory.source_facets import assemble
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive


def response(value,finish='stop'):
    return {'choices':[{'finish_reason':finish,'message':{'content':json.dumps(value)}}]}


def answer(evidence_id='A-0',text='한 댓글은 조건부 필요성을 주장합니다.'):
    return {'answerability':'grounded','points':[{'text':text,'evidence_id':evidence_id}],'missing_information':''}


def card(evidence_id):
    return {'evidence_id':evidence_id,'source_comment_id':'source-'+evidence_id,
            'original_text':'Original conditional claim '+evidence_id,'source_url':None,
            'reviewer_reading_ko':'검수 해석','cautions_ko':'조건 유지',
            'parent_context':{'comment_id':None,'status':'root','text':None,'may_cite_as_support':False}}


def profile(prefix='A'):
    return {'agent_id':prefix,'title':'개발 관점','assertion_family':'need','constraints':['Only own evidence'],
            'status':'development_only_not_approved','evidence':[card(prefix+'-'+str(i)) for i in range(3)]}


class AgentRuntimeTests(unittest.TestCase):
    def scripted(self,items):
        self.calls=[]
        def provider(system,data,schema):
            self.calls.append((system,deepcopy(data),schema)); item=items.pop(0)
            if isinstance(item,Exception): raise item
            return item
        return provider

    def test_supported_point_is_bound_to_exact_own_source(self):
        p=profile(); session=AgentSession(p,self.scripted([response(answer()),response({'verdict':'supported','reason':'same claim'})]))
        t=session.ask('왜 필요한가?')
        self.assertEqual(t['status'],'model_audit_passed_development_only')
        self.assertEqual(t['points'][0]['citation'],p['evidence'][0])
        self.assertFalse(t['semantic_guarantee']); self.assertFalse(t['human_approved'])
        self.assertEqual(self.calls[1][1]['ORIGINAL_COMMENT'],p['evidence'][0]['original_text'])

    def test_foreign_citation_blocked_before_audit(self):
        s=AgentSession(profile(),self.scripted([response(answer('B-0')),response(answer('B-0'))]))
        t=s.ask('question'); self.assertEqual(t['status'],'abstain'); self.assertEqual(t['points'],[])
        self.assertTrue(all(c[0]==SYSTEM for c in self.calls))
        self.assertIn('foreign_evidence_id',t['attempts'][0]['errors'])

    def test_rejected_draft_revised_once_and_not_put_in_history(self):
        s=AgentSession(profile(),self.scripted([response(answer(text='bad draft')),
            response({'verdict':'revise','reason':'condition omitted'}),response(answer(text='revised draft')),
            response({'verdict':'supported','reason':'condition kept'})]))
        t=s.ask('question'); self.assertEqual(len(t['attempts']),2)
        self.assertEqual(t['points'][0]['text'],'revised draft')
        self.assertNotIn('bad draft',json.dumps(s.history))
        self.assertIn('REPAIR',self.calls[2][1])

    def test_two_rejections_abstain_without_showing_drafts(self):
        s=AgentSession(profile(),self.scripted([response(answer()),response({'verdict':'revise','reason':'no'}),
                                              response(answer()),response({'verdict':'unclear','reason':'unclear'})]))
        t=s.ask('question'); self.assertEqual(t['status'],'abstain'); self.assertEqual(t['points'],[])
        self.assertEqual(s.history[0]['points'],[])

    def test_not_in_evidence_abstains_without_audit(self):
        s=AgentSession(profile(),self.scripted([response({'answerability':'not_in_evidence','points':[],'missing_information':'absent'})]))
        t=s.ask('금액은?'); self.assertEqual(t['reason'],'not_in_evidence'); self.assertEqual(len(self.calls),1)

    def test_transport_failure_has_recoverable_abstention(self):
        s=AgentSession(profile(),self.scripted([URLError('offline')]))
        t=s.ask('question'); self.assertEqual(t['status'],'abstain')
        self.assertEqual(t['attempts'][0]['errors'],['transport_error'])

    def test_audit_transport_failure_cannot_pass(self):
        s=AgentSession(profile(),self.scripted([response(answer()),URLError('offline'),
            response({'answerability':'not_in_evidence','points':[],'missing_information':''})]))
        t=s.ask('question'); self.assertEqual(t['status'],'abstain'); self.assertEqual(t['points'],[])

    def test_malformed_audit_cannot_pass(self):
        s=AgentSession(profile(),self.scripted([response(answer()),response({'verdict':'approved','reason':'x'}),
            response({'answerability':'not_in_evidence','points':[],'missing_information':''})]))
        t=s.ask('question'); self.assertIn('invalid_audit',t['attempts'][0]['audit'][0]['errors'])
        self.assertEqual(t['points'],[])

    def test_truncation_and_empty_answer_fail_closed(self):
        s=AgentSession(profile(),self.scripted([response(answer(),finish='length'),
            response({'answerability':'partial','points':[],'missing_information':'x'})]))
        t=s.ask('question'); self.assertEqual(t['status'],'abstain')
        self.assertIn('incomplete_generation',t['attempts'][0]['errors'])
        self.assertIn('empty_answer',t['attempts'][1]['errors'])

    def test_bad_field_types_do_not_raise_or_accept(self):
        for value in [None,[],{**answer(),'missing_information':None,'answerability':'partial'},
                      {**answer(),'points':[None]},{**answer(),'points':[{'text':[],'evidence_id':[]}]}]:
            self.assertTrue(validate_answer(value,{'A-0'}))

    def test_session_isolation_and_own_followup_history(self):
        calls=[]
        def provider(system,data,schema):
            calls.append((system,deepcopy(data)))
            if system==AUDIT_SYSTEM: return response({'verdict':'supported','reason':'same'})
            return response(answer(data['YOUR_EVIDENCE'][0]['evidence_id']))
        a=AgentSession(profile('A'),provider); b=AgentSession(profile('B'),provider)
        a.ask('first A'); b.ask('first B'); a.ask('followup A')
        for _,data in [c for c in calls if c[0]==SYSTEM]:
            ids=[e['evidence_id'] for e in data['YOUR_EVIDENCE']]
            self.assertEqual(len({i.split('-')[0] for i in ids}),1)
        self.assertEqual(calls[4][1]['OWN_HISTORY'][0]['question'],'first A')
        self.assertNotIn('first B',json.dumps(calls[4][1]))
        self.assertNotIn('B-0',json.dumps(calls[4][1]))
        self.assertEqual(calls[2][1]['OWN_HISTORY'],[])

    def test_session_copies_profile_and_restricts_questions(self):
        p=profile(); s=AgentSession(p); p['evidence'][0]['original_text']='changed'
        self.assertNotEqual(s.sources['A-0']['original_text'],'changed')
        for q in ['',None,'x'*1001]:
            with self.assertRaises(ValueError): s.ask(q)
        s.history=[{}]*6
        with self.assertRaises(ValueError): s.ask('seventh')

    def test_render_hides_rejected_drafts_and_uncited_model_limit(self):
        p=profile(); p['evidence'][0]['original_text']='<script>source</script>'
        turn={'agent_id':'A','status':'abstain','reason':'audit_rejected_or_failed','points':[],
              'attempts':[{'raw':'HIDDEN_BAD_DRAFT','audit':[]}], 'model_reported_limit':'HIDDEN_UNAUDITED_LIMIT'}
        r={'bundle':{'agents':[p],'non_agents':[],'dataset':{},'expires_at':'2099-01-01T00:00:00Z'},
           'rounds':[{'question':'<img onerror=x>','answers':[turn]}],'runtime':{}}
        page=render(r)
        self.assertNotIn('HIDDEN_BAD_DRAFT',page); self.assertNotIn('HIDDEN_UNAUDITED_LIMIT',page)
        self.assertNotIn('<script>',page); self.assertNotIn('<img',page)
        self.assertIn('&lt;script&gt;',page)

    def test_citation_url_is_allowlisted_and_parent_is_context_only(self):
        c=card('e'); c['source_url']='javascript:alert(1)'
        c['parent_context']['text']='parent <script>x</script>'
        page=citation_html(c)
        self.assertNotIn('javascript:',page); self.assertIn('문맥 전용',page); self.assertNotIn('<script>',page)


class DevelopmentProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); root=Path(self.temp.name)
        self.snapshot=root/'snapshot.json'; self.reviewed=root/'reviewed.json'; self.bundle=root/'bundle.json'
        data=json.loads((Path(__file__).parent/'fixtures/synthetic-snapshot.json').read_text(encoding='utf-8'))
        data['usage']['expires_at']='2099-01-01T00:00:00Z'; write_json_exclusive(self.snapshot,data)
        loaded=load_snapshot(self.snapshot)
        records=[]
        for i,source in enumerate(loaded.snapshot.comments[:4]):
            output={'topic_match':True,'assertion_type':'need' if i<3 else 'possible_benefit',
                    'polarity':'affirmed','assertion_quote':source.text_original}
            records.append({'id':f'M{i}','source_comment_id':source.comment_id,'source':source.text_original,
                            'result':{'origin':'assistant_review','output':output,'errors':[],'human_approved':False},
                            'review':{'reason_ko':'합성 검수','reading_ko':'합성 해석','cautions_ko':'조건 유지'}})
        self.review={'artifact_kind':'assistant-reviewed-source-facets-0.1','snapshot_sha256':loaded.sha256,
                     'expires_at':data['usage']['expires_at'],'reviewer':'conversation_assistant',
                     'human_approved':False,'accepted_perspectives':0,'reviewed_records':records,'assembly':assemble(records)}
        write_json_exclusive(self.reviewed,self.review)

    def test_unapproved_requires_explicit_opt_in(self):
        with self.assertRaises(ValueError): build_bundle(self.snapshot,self.reviewed)

    def test_only_supported_families_become_development_profiles(self):
        b=build_bundle(self.snapshot,self.reviewed,allow_unapproved=True)
        self.assertEqual(len(b['agents']),1); self.assertEqual(len(b['agents'][0]['evidence']),3)
        self.assertEqual(b['non_agents'][0]['reason'],'rare')
        self.assertEqual(b['accepted_perspectives'],0); self.assertFalse(b['human_approved'])
        self.assertEqual(b['agents'][0]['evidence'][0]['original_text'],self.review['reviewed_records'][0]['source'])

    def test_changed_source_or_group_rejected(self):
        for kind in ['source','assembly']:
            r=deepcopy(self.review)
            if kind=='source': r['reviewed_records'][0]['source']='edited'
            else: r['assembly']['groups'][0]['members']=[]
            path=Path(self.temp.name)/(kind+'.json'); write_json_exclusive(path,r)
            with self.assertRaises(ValueError): build_bundle(self.snapshot,path,allow_unapproved=True)

    def test_load_rebuilds_and_rejects_tampered_bundle(self):
        b=build_bundle(self.snapshot,self.reviewed,allow_unapproved=True); write_json_exclusive(self.bundle,b)
        self.assertEqual(load_bundle(self.snapshot,self.reviewed,self.bundle,allow_unapproved=True),b)
        b['agents'][0]['evidence'][0]['original_text']='tampered'; path=Path(self.temp.name)/'bad.json'; write_json_exclusive(path,b)
        with self.assertRaises(ValueError): load_bundle(self.snapshot,self.reviewed,path,allow_unapproved=True)

    def test_expired_missing_expiry_rejected(self):
        for expiry in [None,'2000-01-01T00:00:00Z']:
            with self.assertRaises(ValueError): require_live(expiry)
