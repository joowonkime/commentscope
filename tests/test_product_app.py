from copy import deepcopy
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest

from commentscope.product.analysis import Analysis
from commentscope.product.app import ProductApp
from commentscope.agents.web import WebError
from experiments.grounding_contract_demo import fixture
from test_grounded_web import provider


class ProductAppTests(unittest.TestCase):
    def test_public_composition_does_not_count_shared_sources_twice(self):
        value=self.analysis.public()
        self.assertEqual(value['analyzed_comments'],3)
        self.assertEqual(sum(x['count'] for x in value['composition']),3)
        self.assertEqual(next(x['count'] for x in value['composition'] if x.get('kind')=='multiple'),3)
        self.assertTrue(all(g['claim_id']!='eliminated' for p in value['perspectives'] for g in p['grounds']))

    def test_processed_scope_and_population_have_different_public_counts(self):
        value=Analysis(self.analysis.bundle,{'processing_count':6,'canonical_population':999}).public()
        self.assertEqual(value['analyzed_comments'],6);self.assertEqual(value['canonical_population'],999)
        self.assertEqual(value['count_scope'],'processed_comments')
        self.assertEqual(sum(x['count'] for x in value['composition']),6)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'app.sqlite'
        bundle = fixture(); bundle['candidates'].append({**deepcopy(bundle['candidates'][0]), 'id': 'P2'})
        self.analysis = Analysis(bundle, {'source': 'synthetic-test'})
        self.calls = []
        self.app = self.build()
        self.token = secrets.token_urlsafe(32)
        self.status, first = self.call('POST', '/api/v1/sessions', {
            'analysis_id': self.analysis.id, 'bundle_revision': self.analysis.revision,
            'initial_opinion': 'I support this policy.', 'request_id': 'create1'})
        self.sid = first['session_id']; self.base = '/api/v1/sessions/'+self.sid
        self.addCleanup(lambda: self.app.close())

    def model(self, stage, request):
        self.calls.append(deepcopy(request))
        data = request['data']
        if stage == 'comparison':
            output = {'items': [{'relation': 'agreement', 'user_span_ids': ['I000'],
                'perspective_claim_ids': [data['PERSPECTIVE_CLAIMS'][0]['id']],
                'explanation': 'These statements express support.', 'consideration_question': None}]}
        elif stage == 'reflection':
            output = {key: [] for key in ('stayed','changed','newly_learned','worth_more_thought')}
            output['stayed'] = [{'initial_span_ids':['I000'], 'current_span_ids':['C000'],
                'related_message_ids': [], 'explanation':'The stated support remains.'}]
        else:
            raw = provider(request['system'],data,request['schema'])
            output = json.loads(raw['choices'][0]['message']['content'])
        return {'output': output, 'errors': [], 'usage': {'cost': 0.0001}, 'new_cost_usd': '0.0001'}

    def build(self):
        return ProductApp(self.path, [self.analysis], self.model, session_ttl_seconds=3600,
                          room_maximum_usd='1', reservation=lambda req: '0.001')

    def call(self, method, path, body=None, token=None):
        return self.app.handle(method,path,self.token if token is None else token,body)

    def job(self, value):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            result = self.call('GET','/api/v1/jobs/'+value['job_id'])[1]
            if result['state'] not in ('queued','running'): return result
            time.sleep(.005)
        self.fail('Job did not settle')

    def room(self):
        return self.call('POST',self.base+'/rooms',{'mode':'group','participant_ids':['P1','P2'],
            'initial_revision':1,'request_id':'room1'})[1]

    def test_session_opinions_persist_with_exact_text_and_request_conflicts(self):
        self.assertEqual(self.status,201)
        body={'text':'  An updated view.\n','expected_revision':1,'request_id':'op1'}
        first=self.call('PUT',self.base+'/opinions/initial',body)
        self.assertEqual(first[0],200)
        self.assertEqual(self.call('PUT',self.base+'/opinions/initial',body),first)
        with self.assertRaises(WebError):
            self.call('PUT',self.base+'/opinions/initial',{**body,'text':'Different'})
        self.app.close();self.app=self.build()
        state=self.call('GET',self.base)[1]
        self.assertEqual(state['initial_opinion']['text'],body['text'])
        self.assertEqual(state['initial_opinion']['revision'],2)
        self.assertNotIn(self.token.encode(),self.path.read_bytes())
        self.assertFalse(self.calls)

    def test_other_session_cannot_read_resources(self):
        other=secrets.token_urlsafe(32)
        with self.assertRaises(WebError) as error:self.call('GET',self.base,token=other)
        self.assertEqual(error.exception.status,404)

    def test_explore_reuses_job_and_old_revision_is_stale(self):
        body={'perspective_id':'P1','initial_revision':1,'request_id':'compare1'}
        first=self.call('POST',self.base+'/comparisons',body)
        done=self.job(first[1]);self.assertEqual(done['state'],'succeeded')
        self.assertEqual(done['result']['items'][0]['user_spans'][0]['text'],'I support this policy.')
        self.assertEqual(self.call('POST',self.base+'/comparisons',body)[0],200)
        self.assertEqual(self.call('POST',self.base+'/comparisons',{**body,'request_id':'compare-again'})[0],200)
        self.assertEqual(len(self.calls),1)
        self.call('PUT',self.base+'/opinions/initial',{'text':'Another view.','expected_revision':1,'request_id':'edit1'})
        self.assertTrue(self.job(first[1])['stale'])

    def test_group_opens_replies_and_keeps_message_references(self):
        room=self.room();rid=room['room_id'];path='/api/v1/rooms/'+rid
        body={'opening_question':'Your position?','expected_revision':room['revision'],'request_id':'start1'}
        job=self.call('POST',path+'/start',body)[1]
        self.assertEqual(self.job(job)['state'],'succeeded')
        value=self.call('GET',path)[1]
        self.assertEqual(value['state'],'awaiting_user')
        messages=value['messages'];agents=[m for m in messages if m['author_kind']=='agent']
        self.assertEqual(len(agents),4)
        self.assertEqual(agents[2]['reply_to_message_id'],agents[1]['message_id'])
        self.assertEqual(agents[3]['reply_to_message_id'],agents[2]['message_id'])
        self.assertEqual(self.call('POST',path+'/start',body)[0],200)
        self.assertEqual(len(self.calls),4)
        self.assertTrue(any('PEER_CONTEXT_ONLY' in c['data'] for c in self.calls))
        self.assertNotIn('I support this policy.',json.dumps(self.calls))

    def test_group_pause_settles_current_turn_and_resume_does_not_repeat(self):
        entered=threading.Event();release=threading.Event();original=self.app.model
        def delayed(stage,request):
            entered.set();release.wait(3);return original(stage,request)
        self.app.model=delayed
        room=self.room();path='/api/v1/rooms/'+room['room_id']
        first=self.call('POST',path+'/start',{'opening_question':'Your position?',
            'expected_revision':room['revision'],'request_id':'start1'})[1]
        self.assertTrue(entered.wait(2))
        current=self.call('GET',path)[1]
        self.call('POST',path+'/control',{'action':'pause','expected_revision':current['revision'],'request_id':'pause1'})
        release.set();self.job(first)
        current=self.call('GET',path)[1]
        self.assertEqual(current['state'],'paused');self.assertEqual(current['turn_count'],1)
        resumed=self.call('POST',path+'/control',{'action':'resume','expected_revision':current['revision'],'request_id':'resume1'})[1]
        self.job(resumed)
        self.assertEqual(self.call('GET',path)[1]['turn_count'],4)
        self.assertEqual(len(self.calls),4)

    def test_reflection_analysis_edit_manual_save_and_reload(self):
        current=self.call('PUT',self.base+'/opinions/current',{'text':'I still support it.',
            'expected_revision':0,'request_id':'current1'})[1]
        args={'initial_revision':1,'current_revision':current['revision'],
              'context_message_ids':[],'request_id':'reflect1'}
        job=self.call('POST',self.base+'/reflection-analyses',args)[1]
        self.assertEqual(self.job(job)['state'],'succeeded')
        user_items={key:[] for key in ('stayed','changed','newly_learned','worth_more_thought')}
        user_items['stayed']=[{'text':'My own wording.','initial_span_ids':[],
                              'current_span_ids':[],'related_message_ids':[]}]
        saved=self.call('POST',self.base+'/reflections',{'initial_revision':1,'current_revision':1,
            'analysis_job_id':job['job_id'],'user_items':user_items,'expected_revision':0,'request_id':'save1'})[1]
        calls=len(self.calls)
        self.app.close();self.app=self.build()
        value=self.call('GET',self.base+'/reflections/'+saved['reflection_id'])[1]
        self.assertEqual(value['user_items'],user_items);self.assertEqual(len(self.calls),calls)
        self.call('PUT',self.base+'/opinions/current',{'text':'Now uncertain.',
            'expected_revision':1,'request_id':'current2'})
        with self.assertRaises(WebError):
            self.call('POST',self.base+'/reflections',{'initial_revision':1,'current_revision':2,
                'analysis_job_id':job['job_id'],'user_items':user_items,'expected_revision':0,'request_id':'save2'})

    def test_partial_group_failure_retains_posts_and_never_retries(self):
        original=self.app.model;count=0
        def fail_second(stage,request):
            nonlocal count
            count+=1
            if count==2:return {'output':None,'errors':['invalid_model_selection'],'new_cost_usd':'0'}
            return original(stage,request)
        self.app.model=fail_second
        room=self.room();path='/api/v1/rooms/'+room['room_id']
        body={'opening_question':'Your position?','expected_revision':room['revision'],'request_id':'start1'}
        job=self.call('POST',path+'/start',body)[1]
        self.assertEqual(self.job(job)['state'],'failed')
        value=self.call('GET',path)[1]
        self.assertEqual(value['state'],'error');self.assertEqual(value['turn_count'],1)
        self.call('POST',path+'/start',body);self.assertEqual(count,2)

    def test_unsupported_ids_and_stale_revisions_refuse_before_model(self):
        for body in ({'perspective_id':'foreign','initial_revision':1,'request_id':'bad1'},
                     {'perspective_id':'P1','initial_revision':9,'request_id':'bad2'}):
            with self.assertRaises(WebError):self.call('POST',self.base+'/comparisons',body)
        self.assertFalse(self.calls)

    def test_close_during_call_withholds_late_output_and_does_not_reopen(self):
        entered=threading.Event();release=threading.Event();original=self.app.model
        def delayed(stage,request):entered.set();release.wait(3);return original(stage,request)
        self.app.model=delayed
        room=self.room();path='/api/v1/rooms/'+room['room_id']
        job=self.call('POST',path+'/start',{'opening_question':'Your position?',
            'expected_revision':room['revision'],'request_id':'start'})[1]
        self.assertTrue(entered.wait(2));current=self.call('GET',path)[1]
        self.call('POST',path+'/control',{'action':'close','expected_revision':current['revision'],'request_id':'close'})
        release.set();self.assertEqual(self.job(job)['state'],'cancelled')
        current=self.call('GET',path)[1]
        self.assertEqual(current['state'],'closed');self.assertEqual(current['turn_count'],0)

    def test_unknown_comparison_reference_fails_without_publishing_a_result(self):
        original=self.app.model
        def bad(stage,request):
            value=original(stage,request);value['output']['items'][0]['perspective_claim_ids']=['foreign'];return value
        self.app.model=bad
        job=self.call('POST',self.base+'/comparisons',{'perspective_id':'P1','initial_revision':1,'request_id':'bad'})[1]
        value=self.job(job);self.assertEqual(value['state'],'failed');self.assertIsNone(value['result'])

    def test_failed_round_is_not_relabelled_complete_after_acknowledgement(self):
        self.app.model=lambda *args:{'output':None,'errors':['invalid'],'new_cost_usd':'0'}
        room=self.room();path='/api/v1/rooms/'+room['room_id']
        job=self.call('POST',path+'/start',{'opening_question':'Your position?',
            'expected_revision':room['revision'],'request_id':'start'})[1]
        self.assertEqual(self.job(job)['state'],'failed')
        current=self.call('GET',path)[1]
        self.call('POST',path+'/control',{'action':'acknowledge_error','expected_revision':current['revision'],'request_id':'ack'})
        current=self.call('GET',path)[1]
        self.assertFalse(current['rounds'][0]['completed'])
        self.assertTrue(current['partial_round'])

    def test_process_restart_holds_unfinished_job_without_new_model_dispatch(self):
        from commentscope.product.store import encode
        self.app.close()
        with self.app.store.transaction() as db:
            value={'job_id':'Junfinished','session_id':self.sid,'operation':'comparison','state':'running',
                'args':{},'result':None,'error':None,'room_id':None}
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',('Junfinished',self.sid,'comparison','running',encode(value)))
        self.app=self.build()
        self.assertEqual(self.call('GET','/api/v1/jobs/Junfinished')[1]['state'],'needs_reconciliation')
        with self.assertRaises(WebError):
            self.call('POST',self.base+'/comparisons',{'perspective_id':'P1','initial_revision':1,'request_id':'after-crash'})
        self.call('PUT',self.base+'/opinions/current',{'text':'My saved draft.','expected_revision':0,'request_id':'draft'})
        self.assertFalse(self.calls)

    def test_blank_initial_comparison_is_unavailable_without_model_call(self):
        self.call('PUT',self.base+'/opinions/initial',{'text':'  ',
            'expected_revision':1,'request_id':'blank'})
        job=self.call('POST',self.base+'/comparisons',{'perspective_id':'P1',
            'initial_revision':2,'request_id':'compare-blank'})[1]
        result=self.job(job)
        self.assertEqual(result['state'],'succeeded')
        self.assertFalse(result['result']['available'])
        self.assertFalse(self.calls)

    def test_manual_empty_categories_need_no_analysis_and_foreign_dialogue_is_rejected(self):
        items={key:[] for key in ('stayed','changed','newly_learned','worth_more_thought')}
        body={'initial_revision':1,'current_revision':0,'analysis_job_id':None,
            'user_items':items,'expected_revision':0,'request_id':'manual'}
        saved=self.call('POST',self.base+'/reflections',body)[1]
        self.assertEqual(saved['user_items'],items)
        items['stayed']=[{'text':'My note.','initial_span_ids':[],
            'current_span_ids':[],'related_message_ids':['foreign']}]
        with self.assertRaises(WebError):
            self.call('POST',self.base+'/reflections',{**body,'user_items':items,'request_id':'foreign-note'})
        self.assertFalse(self.calls)


class ComparisonPremiseTests(unittest.TestCase):
    def test_conditional_claim_keeps_its_exact_required_premise_and_empty_result_is_valid(self):
        from commentscope.product import contracts as c
        initial=c.segments('I support review if a device has high risk.','I')
        allowed={'allowed_entries':[
            {'claim_id':'claim','text':'If risk is high, require a review.',
             'kind':'value','role':'core','requires':['condition'],'citations':{}},
            {'claim_id':'condition','text':'Only devices with high risk are in scope.',
             'kind':'value','role':'prerequisite','requires':[],'citations':{}}]}
        req=c.comparison_request(initial,allowed)
        row={'relation':'additional_condition','user_span_ids':['I000'],
             'perspective_claim_ids':['claim'],'explanation':'Both texts condition support on risk.',
             'consideration_question':None}
        result=c.bind_comparison(req,{'output':{'items':[row]}},initial,allowed)[0]
        self.assertEqual(result['required_premises'],[allowed['allowed_entries'][1]])
        self.assertEqual(result['user_spans'],initial)
        self.assertEqual(c.bind_comparison(req,{'output':{'items':[]}},initial,allowed),[])
