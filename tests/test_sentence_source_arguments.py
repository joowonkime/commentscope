"""Sentence preservation and selected-scope gates; fixtures are not real Agents."""
from copy import deepcopy
import unittest
from commentscope.factory import sentence_source_arguments as sentence,literal_source_arguments as literal
from commentscope.factory import source_closed_policy as closed
from commentscope.factory.automatic_contract import digest
from commentscope.providers import local_nli
from experiments.grounding_contract_demo import MODEL
from test_literal_source_arguments import LiteralRunner
from test_semantic_source_closure import SemanticSourceClosureTests
from test_source_entailment import nli_response

class SentenceRunner(LiteralRunner):
    def call(self,stage,req):
        if req['system'].startswith(sentence.SYSTEM):
            self.calls.append((stage,req))
            return {'raw':'fixed sentence relation fixture','errors':[],'output':{
                'source_language':'en','status':'partial' if self.partial else 'complete',
                'relations':[{'local_id':u['local_id'],'parent':'root','relation':'position',
                              'voice':'reported' if u['quoted_only'] else 'own'} for u in req['data']['SENTENCES']]}}
        return super().call(stage,req)

class SentenceArgumentTests(unittest.TestCase):
    setUp=SemanticSourceClosureTests.setUp
    configure=SemanticSourceClosureTests.configure

    def process(self,runner=None):
        self.configure();runner=runner or SentenceRunner()
        return closed.process(self.snapshot,self.record,[(self.req,self.res)],runner,
            lambda req:{'request_sha256':digest(req),'fits':True},nli_response,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION},
            interpret_unparsed=True,sentence_arguments=True)

    def test_full_path_retains_conditional_sentence_and_existing_audit_gates(self):
        out=self.process();self.assertFalse(out['errors']);self.assertEqual(len(out['accepted']),3)
        for a in out['accepted']:
            record=a['record']['extraction_record'];literal.validate(record)
            self.assertEqual(record['graph']['artifact_kind'],sentence.VERSION)
            self.assertEqual(record['units'][0]['text'],record['source']['text'])
        for runner in (SentenceRunner(partial=True),SentenceRunner(kind='mixed'),SentenceRunner(audit_bad=True)):
            self.assertFalse(self.process(runner)['accepted'])

    def test_actual_fragmentation_counterexamples_preserve_coordinated_effects(self):
        self.configure();base=self.sources[0]
        for text in ('UBI would create instantaneous mass inflation, mass laziness and worsen our national debt by many times.',
                     'If everyone received income, demand would increase and prices would also increase.'):
            source={**deepcopy(base),'text':text};request=sentence.request(source)
            graph=sentence.bind(source,SentenceRunner().call('relations',request))
            self.assertEqual([u['text'] for u in graph['units']],[text])
            self.assertNotIn('range',request['schema']['properties']['relations']['items']['anyOf'][0]['properties'])
            self.assertEqual(set(request['data']),{'OWN_ORIGINAL','SENTENCES'})

    def test_selected_unknown_type_blocks_but_unselected_context_stays_visible(self):
        record=self.process()['accepted'][0]['record']['extraction_record'];graph=record['graph']
        raw=deepcopy(record['typings'][0]['output']);raw.update(kind='mixed',scope_complete='unclear')
        typing=literal.bind_typing(graph,'U1',{'output':raw})
        kept=literal.declare(graph,[typing],record['batch_candidates'],record['support_batches'],
            {'output':record['association_output']})
        self.assertEqual(kept['status'],'unresolved')
        association=deepcopy(record['association_output']);association['roots'][0]['links']=[]
        context=literal.declare(graph,[typing],record['batch_candidates'],record['support_batches'],{'output':association})
        self.assertEqual(context['status'],'complete')
        self.assertEqual(len(context['units']),1)
        self.assertFalse(context['units'][0]['candidate_ids'])
        self.assertEqual(context['units'][0]['kind'],'uncertain')
        self.assertFalse(context['semantic_approval'])

    def test_missing_changed_or_parent_text_cannot_replace_a_fixed_sentence(self):
        self.configure();source=self.sources[0];req=sentence.request(source)
        output=SentenceRunner().call('relations',req);output['output']['relations']=[]
        with self.assertRaises(ValueError):sentence.bind(source,output)
        output=SentenceRunner().call('relations',req);output['output']['relations'][0]['text']='foreign claim'
        with self.assertRaises(ValueError):sentence.bind(source,output)

    def test_quoted_sentence_cannot_become_own_assertion(self):
        self.configure();source={**deepcopy(self.sources[0]),'text':'"The policy will work." I disagree.'}
        req=sentence.request(source);out=SentenceRunner().call('relations',req)
        quote=next(u['local_id'] for u in req['data']['SENTENCES'] if u['quoted_only'])
        next(r for r in out['output']['relations'] if r['local_id']==quote)['voice']='own'
        with self.assertRaises(ValueError):sentence.bind(source,out)

if __name__=='__main__':unittest.main()
