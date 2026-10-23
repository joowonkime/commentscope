from copy import deepcopy
import unittest

from commentscope.factory import qualification_ownership as qo, proposition_requirements as pr


class QualificationOwnershipTests(unittest.TestCase):
    def check(self,source,text,**changes):
        return [qo.bind_pair(source,text,p,{'output':{'parent_relation':'equivalent','ground_relation':'equivalent',
            'authorship':'yes',**changes}}) for p in qo.pairs(source,text)]

    def test_generic_topics_preserve_parent_and_reject_temporal_transfer(self):
        for topic in ('park access','school meals','film ratings','safety checks','transit service','tax reform'):
            text=f'Adopt {topic} because fairness matters.'
            right={'id':'s','text':text,'parent':None}
            self.assertTrue(qo.assessment(right,text,self.check(right,text))['passed'])
            wrong={'id':'s','text':f'Adopt {topic}. Start immediately because fairness matters.','parent':None}
            rows=self.check(wrong,text)
            self.assertTrue(rows[0]['temporal_presence_mismatch'])
            self.assertFalse(qo.assessment(wrong,text,rows)['passed'])
            req=qo.pair_request(wrong,text,qo.pairs(wrong,text)[0])
            self.assertEqual(req['data']['SOURCE_PARENT'],'Start immediately')

    def test_missing_or_rejected_witness_never_approves_even_empty_model_inventory(self):
        text='Adopt P because fairness matters.'
        source={'id':'s','text':text,'parent':None}
        shape=pr.bind_shape(text,{'output':{'status':'complete','qualifications':[]}})
        self.assertFalse(pr.assessment(source,shape,[])['passed'])
        for changes in ({'parent_relation':'different'},{'ground_relation':'uncertain'},{'authorship':'no'}):
            bound=qo.assessment(source,text,self.check(source,text,**changes))
            self.assertFalse(pr.assessment(source,shape,[],bound)['passed'])
        bound=qo.assessment(source,text,self.check(source,text))
        self.assertTrue(pr.assessment(source,shape,[],bound)['passed'])

    def test_no_explicit_edge_or_quoted_ground_does_not_supply_witness(self):
        text='Adopt P because fairness matters.'
        for original in ('Adopt P. Fairness matters.','They said "Adopt P because fairness matters." I disagree.'):
            source={'id':'s','text':original,'parent':None}
            self.assertEqual(qo.pairs(source,text),[])
            self.assertFalse(qo.assessment(source,text,[])['passed'])

    def test_unresolved_candidate_syntax_is_held(self):
        text='Adopt P because fairness matters although costs rise.'
        self.assertFalse(qo.assessment({'id':'s','text':text,'parent':None},text,[])['passed'])

    def test_provenance_mutations_and_duplicate_witnesses_rejected(self):
        text='Adopt P only if funding is available.';source={'id':'s','text':text,'parent':None}
        rows=self.check(source,text);bound=qo.assessment(source,text,rows);qo.validate(bound)
        with self.assertRaises(ValueError):qo.assessment(source,text,rows*2)
        changed=deepcopy(bound);changed['checks'][0]['pair']['source_edge_id']='foreign'
        with self.assertRaises(ValueError):qo.validate(changed)
        changed=deepcopy(bound);changed['source']['id']='other'
        with self.assertRaises(ValueError):qo.validate(changed)
