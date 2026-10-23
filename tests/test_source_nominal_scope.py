from copy import deepcopy
import unittest

from commentscope.factory import source_nominal_scope as ns, scoped_comparison as sc
from commentscope.factory import contextual_witness as cw, contextual_qualifications as cq
from test_contextual_dependencies import fixture, scope


class NominalScopeTests(unittest.TestCase):
    def test_inherited_modifier_addresses_across_unrelated_topics(self):
        for left, right, head in [('Library', 'Transit', 'cards'), ('School', 'Office', 'meals'),
                                  ('Park', 'Road', 'permits'), ('Lab', 'Factory', 'inspections')]:
            for prefix in [left, right]:
                text=f'Some people say "{prefix} {head} should be mandatory." I disagree: {head} should remain optional.'
                pair=fixture(text,'s',1);bound=scope(*pair,links={'DISCOURSE':'C1'});row=ns.record(bound)
                self.assertEqual(row['inherited_subject_proposal']['subject']['text'],prefix+' '+head)
                self.assertEqual(ns.packet(bound)['subject'],prefix+' '+head)
                self.assertEqual(ns.packet(bound)['surface_subject'],head)
                self.assertEqual(bound['bundle']['source']['text'],text)
                for part in [row['own_subject']['subject'],row['inherited_subject_proposal']['subject']]:
                    self.assertEqual(text[part['start']:part['end']],part['text'])
                self.assertFalse(row['assertion_rewritten']);self.assertFalse(row['semantic_coreference_verified'])

    def test_unquoted_report_target_and_whitespace_preserve_whole_subject(self):
        for text in ['Some people say that School meals should be free. I disagree: meals should cost money.',
                     'Some people claim School   meals should be free. I disagree: meals should cost money.']:
            pair=fixture(text,'s',1);row=ns.record(scope(*pair,links={'DISCOURSE':'C1'}))
            self.assertEqual(' '.join(row['inherited_subject_proposal']['subject']['text'].split()),'School meals')

    def test_multiple_matching_antecedents_are_not_arbitrarily_selected(self):
        text='People say "School meals should be free" and "Office meals should be free". I disagree: meals should cost money.'
        pair=fixture(text,'s',1);s=scope(*pair,links={'DISCOURSE':'C1'});row=ns.record(s)
        self.assertEqual(len(row['antecedent_candidates']),2)
        self.assertIsNone(row['inherited_subject_proposal'])
        self.assertIn('nominal_antecedent_not_unique',row['guards'])
        other=fixture('School meals should cost money.','other')
        w=sc.bind(s,other[0],scope(*other),{'output':{'relation':'supported','interpretation':'clear'}})
        self.assertEqual(w['relation'],'uncertain')
        other=fixture(text,'other',1);other_scope=scope(*other,links={'DISCOURSE':'C1'})
        old=cw.scoped_identity(s,other[0],other_scope,cw.LEGACY_SCOPED_IDENTITY)
        cw.validate(old);self.assertEqual(old['relation'],'supported')
        new=cw.scoped_identity(s,other[0],other_scope)
        self.assertEqual(new['relation'],'uncertain');cw.validate(new)
        self.assertFalse(cq.assessment(new,pair[1],other[1])['passed'])

    def test_quantifiers_negation_and_full_subjects_are_not_silently_restricted(self):
        for subject in ['All cards','No cards','Some cards','Transit cards']:
            pair=fixture('People say "Library cards should be mandatory." I disagree: '+subject+' should remain optional.','s',1)
            row=ns.record(scope(*pair,links={'DISCOURSE':'C1'}))
            self.assertIsNone(row['inherited_subject_proposal'])
            self.assertEqual(row['own_subject']['subject']['text'],subject)
        pair=fixture('People say "All library cards should be mandatory." I disagree: cards should not be mandatory.','s',1)
        row=ns.record(scope(*pair,links={'DISCOURSE':'C1'}))
        self.assertIn('nominal_antecedent_quantifier_scope_unresolved',row['guards'])
        self.assertEqual(row['own_subject']['predicate']['text'],'should not be mandatory.')

    def test_no_head_guess_for_prepositional_or_unsupported_subject(self):
        pair=fixture('People say "Access to archives should be free." I disagree: archives should be free.','s',1)
        row=ns.record(scope(*pair,links={'DISCOURSE':'C1'}))
        self.assertIsNone(row['inherited_subject_proposal']);self.assertTrue(row['guards'])
        pair=fixture('If lunch fees disappeared, I would start attending.')
        p=ns.packet(scope(*pair,world='hypothetical'))
        self.assertIsNone(p['subject']);self.assertIn('unparsed_position',p)
        self.assertIn('If lunch fees disappeared',str(p))

    def test_whole_policy_dependencies_survive_reference_focusing(self):
        packets=[]
        for policy in ['Archive access should be free.','Archive access should cost money.']:
            pair=fixture(policy+' This rule should begin tomorrow.','s',1)
            packets.append(ns.packet(scope(*pair,links={'R1':'C1'})))
        self.assertEqual(packets[0]['subject'],packets[1]['subject'])
        self.assertNotEqual(packets[0]['other_dependencies'],packets[1]['other_dependencies'])

    def test_referent_request_exposes_inherited_modifier_and_legacy_replays(self):
        f=fixture('Library cards should remain optional.','f')
        ab=fixture('People say "Transit cards should be mandatory." I disagree: cards should remain optional.','ab',1)
        sf,sab=scope(*f),scope(*ab,links={'DISCOURSE':'C1'});value={'relation':'supported','interpretation':'clear'}
        old=sc.bind(sf,ab[0],sab,{'output':value},sc.MODALITY);sc.validate(old)
        self.assertIn('CANDIDATE_POSITION',sc.alignment_request(old)['data'])
        w=sc.bind(sf,ab[0],sab,{'output':value});req=sc.alignment_request(w)
        self.assertEqual(req['data']['SOURCE_REFERENTS']['subject'],'Library cards')
        self.assertEqual(req['data']['CANDIDATE_REFERENTS']['subject'],'Transit cards')
        self.assertNotIn('mandatory',str(req['data']))
        self.assertNotIn('SOURCE_POSITION',req['data'])
        self.assertIsNone(sc.exact_alignment(w))

    def test_literal_alignment_requires_whole_direct_predicate_and_dependencies(self):
        a=fixture('School meals should be free.','a');b=fixture('School meals should be free.','b')
        sa,sb=scope(*a),scope(*b);w=sc.bind(sa,b[0],sb,{'output':{'relation':'supported','interpretation':'clear'}})
        proof=sc.exact_alignment(w);self.assertEqual(proof['model_calls'],0);self.assertNotIn('output',proof)
        shape=sc.bind_shape(b[0],sb,{'output':{'status':'complete','qualifications':[]}})
        assessment=sc.assessment(w,proof,shape);self.assertTrue(assessment['passed']);sc.validate_assessment(assessment)
        changed=deepcopy(proof);changed['left_scope_sha256']='different'
        with self.assertRaises(ValueError):sc.assessment(w,changed,shape)
        c=fixture('School meals should be free for children.','c')
        self.assertFalse(ns.exact_direct_retention(sa,scope(*c)))
        d=fixture('People say "School meals should cost money." I disagree: meals should be free.','d',1)
        self.assertFalse(ns.exact_direct_retention(sa,scope(*d,links={'DISCOURSE':'C1'})))

    def test_parent_antecedent_and_mutated_scope_are_not_reply_evidence(self):
        parent={'id':'p','text':'People say "School meals should cost money."'}
        pair=fixture('I disagree: meals should be free.','reply',parent=parent)
        s=scope(*pair,links={'DISCOURSE':'C1'});row=ns.record(s)
        self.assertEqual(row['inherited_subject_proposal']['origin'],'parent')
        self.assertEqual(row['own_subject']['origin'],'source')
        changed=deepcopy(s);changed['bundle']['source']['parent']['text']='Changed.'
        with self.assertRaises(ValueError):ns.record(changed)


if __name__=='__main__':unittest.main()
